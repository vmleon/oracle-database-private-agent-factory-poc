#!/usr/bin/env python3
"""CLI for managing the Oracle PAF Decisioning Engine PoC on OCI."""

import configparser
import json
import os
import re
import secrets
import shlex
import shutil
import string
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import click
import requests
import urllib3
from dotenv import load_dotenv
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel

console = Console()

# The public load balancer terminates TLS with a self-signed certificate.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_ROOT = Path(__file__).parent
ENV_FILE = PROJECT_ROOT / ".env"

ANSIBLE_ROOT = PROJECT_ROOT / "deploy" / "ansible"

TF_DIR = PROJECT_ROOT / "deploy" / "tf" / "app"
TF_VARS_TEMPLATE = TF_DIR / "terraform.tfvars.tpl"
TF_VARS_FILE = TF_DIR / "terraform.tfvars"

TF_IAM_DIR = PROJECT_ROOT / "deploy" / "tf" / "iam"
TF_IAM_VARS_TEMPLATE = TF_IAM_DIR / "terraform.tfvars.tpl"
TF_IAM_VARS_FILE = TF_IAM_DIR / "terraform.tfvars"

OCI_CONFIG = Path.home() / ".oci" / "config"

KIT_DIST_DIR = PROJECT_ROOT / "paf" / "dist"



def _tf_output(name: str) -> str | None:
    """Read one Terraform output from the workload root, or None if unavailable."""
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={TF_DIR}", "output", "-raw", name],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _tf_output_json(name: str):
    """Read a structured Terraform output, or None when unavailable."""
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={TF_DIR}", "output", "-json", name],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    raw = result.stdout.strip() if result.returncode == 0 else ""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None



def _ops_python(script: str) -> subprocess.CompletedProcess:
    """Run a Python snippet on the ops bastion.

    Autonomous Database sits on a private endpoint, so the bastion is the only
    host that can reach it. It already has python3-oracledb, the wallet and the
    connection parameters the bootstrap wrote.
    """
    ip = _tf_output("ops_public_ip")
    if not ip:
        console.print("[red]No bastion address.[/red] Apply deploy/tf/app first.")
        sys.exit(1)
    key_path = Path(os.getenv("OCI_SSH_KEY_PATH", "")).expanduser()
    private_key = key_path.with_suffix("") if key_path.suffix == ".pub" else key_path
    if not private_key.exists():
        console.print(f"[red]No private key at {private_key}.[/red]")
        sys.exit(1)
    return subprocess.run(
        ["ssh", "-i", str(private_key), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
         "-o", "ConnectTimeout=20", f"opc@{ip}", "sudo python3 -"],
        input=script, capture_output=True, text=True, timeout=180,
    )




def _paf_base_url() -> str:
    """Where PAF's admin API lives: behind the public load balancer, so the
    address is only known from Terraform."""
    lb_ip = _tf_output("lb_ip")
    if not lb_ip:
        console.print("[red]No load balancer address.[/red] Apply deploy/tf/app first.")
        sys.exit(1)
    return f"https://{lb_ip}"


CLOUD_PREREQS = {
    "terraform": "Install: `brew install terraform` (macOS) or https://developer.hashicorp.com/terraform/install",
    "oci": "Install: `brew install oci-cli` (macOS) or https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm",
}


def _generate_password(length: int = 20) -> str:
    """Oracle-compliant: starts with letter, includes specials and digits."""
    letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "0123456789"
    specials = "#_-"
    password = [
        secrets.choice(letters),
        secrets.choice(specials),
        secrets.choice(specials),
        secrets.choice(digits),
        secrets.choice(digits),
    ]
    alphabet = letters + digits + specials
    password.extend(secrets.choice(alphabet) for _ in range(length - 5))
    tail = password[1:]
    secrets.SystemRandom().shuffle(tail)
    password[1:] = tail
    return "".join(password)


def _check_prereqs(prereqs: dict) -> None:
    missing = [(name, hint) for name, hint in prereqs.items() if not shutil.which(name)]
    if not missing:
        return
    console.print("[red]Missing prerequisites:[/red]")
    for name, hint in missing:
        console.print(f"  • [bold]{name}[/bold] — {hint}")
    sys.exit(1)


def _ensure_env() -> None:
    if not ENV_FILE.exists():
        console.print("[red].env not found.[/red] Run `python manage.py setup` first.")
        sys.exit(1)
    load_dotenv(ENV_FILE)


def _stage(source: Path, dest: Path) -> None:
    """Replace dest with a fresh copy of source, so a rebuild leaves nothing stale."""
    if not source.exists():
        console.print(f"[red]{source} not found.[/red]")
        sys.exit(1)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


# The kit spells its architecture differently between builds, so each target
# matches on any of the tokens that mean it.
KIT_ARCH_ALIASES = {
    "x86_64": ("x86_64", "x86-64", "x86", "amd64"),
    "arm64": ("arm64", "aarch64"),
}


def _resolve_kit_tarball(arch: str) -> str:
    """Path to the kit tarball in paf/dist/ built for `arch`."""
    aliases = KIT_ARCH_ALIASES[arch]
    other = {a for key, names in KIT_ARCH_ALIASES.items() if key != arch for a in names}
    candidates = sorted(KIT_DIST_DIR.glob("*.tar.gz"))
    for candidate in candidates:
        name = candidate.name.lower()
        # An arm64 build must not match on "x86" appearing elsewhere in a name,
        # so a file naming the other architecture is rejected outright.
        if any(a in name for a in other):
            continue
        if any(a in name for a in aliases):
            return str(candidate)

    console.print(
        f"[red]No {arch} PAF kit tarball in {KIT_DIST_DIR}.[/red]\n"
        f"Download it from Oracle Software Delivery and place it there — "
        f"see paf/dist/README.md."
    )
    if candidates:
        console.print("[dim]Present, but not for this architecture:[/dim]")
        for candidate in candidates:
            console.print(f"[dim]  • {candidate.name}[/dim]")
    sys.exit(1)


def _write_env_key(key: str, value: str) -> None:
    """Update or append KEY=value in .env, preserving everything else.

    The running process is updated too: `load_dotenv` will not overwrite a
    variable that is already set, so a value written here would otherwise be
    invisible to the rest of this command.
    """
    os.environ[key] = value
    content = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(line, content)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += line + "\n"
    ENV_FILE.write_text(content)
    ENV_FILE.chmod(0o600)


def _paf_session() -> requests.Session:
    """Administrator-authenticated session against the active PAF instance."""
    load_dotenv(ENV_FILE, override=True)
    user = os.getenv("PAF_ADMIN_USER", "").strip()
    password = os.getenv("PAF_ADMIN_PASS", "").strip()
    if not user or not password:
        console.print(
            "[red]PAF_ADMIN_USER / PAF_ADMIN_PASS are not set in .env.[/red] "
            "They are the credentials created in the PAF install wizard."
        )
        sys.exit(1)
    session = requests.Session()
    session.verify = False
    try:
        r = session.get(
            f"{_paf_base_url()}/agentFactory/v1/loginValidation",
            auth=(user, password),
            headers={"Origin": _paf_base_url()},
            timeout=30,
        )
    except requests.RequestException as exc:
        console.print(f"[red]Cannot reach PAF at {_paf_base_url()}:[/red] {exc}")
        sys.exit(1)
    if r.status_code != 200:
        console.print(
            f"[red]PAF login failed: HTTP {r.status_code}.[/red] The credentials in .env "
            "are what setup asked for before PAF existed. Run "
            "[cyan]python manage.py paf admin[/cyan] to record the admin the install "
            f"wizard created.\n{r.text[:200]}"
        )
        sys.exit(1)
    return session


def _discover_chat_flow_id(session: requests.Session) -> str:
    """Resolve CHAT_FLOW's agent id by name."""
    r = session.get(f"{_paf_base_url()}/agentFactory/v1/agents", timeout=30)
    if r.status_code != 200:
        console.print(f"[red]Could not list agents: HTTP {r.status_code}.[/red]\n{r.text[:300]}")
        sys.exit(1)
    body = r.json()
    data = body.get("data") if isinstance(body, dict) else body
    agents = data.get("items", []) if isinstance(data, dict) else data
    for agent in agents or []:
        if agent.get("name") == "CHAT_FLOW":
            agent_id = agent.get("agentId") or agent.get("agent_id")
            if agent_id:
                return str(agent_id)
    console.print(
        "[red]CHAT_FLOW not found in PAF's agent list.[/red] "
        "Import and publish it per paf/flows/CHAT_FLOW.md."
    )
    sys.exit(1)


@click.group()
def cli() -> None:
    """Oracle PAF Decisioning Engine PoC."""


# ---------------------------------------------------------------- setup

@cli.command("setup")
def setup() -> None:
    """Interactive deployment configuration; writes .env."""
    console.print(Panel.fit("[bold]Oracle PAF PoC — Setup (OCI)[/bold]"))
    _check_prereqs(CLOUD_PREREQS)

    existing = {}
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
        existing = dict(os.environ)

    profiles = _oci_profiles()
    if not profiles:
        console.print("[red]No profiles found in ~/.oci/config.[/red] Run `oci setup config` first.")
        sys.exit(1)
    oci_profile = inquirer.select(
        message="OCI config profile:",
        choices=profiles,
        default=existing.get("OCI_PROFILE", profiles[0]),
    ).execute()

    tenancy_ocid = _oci_tenancy_ocid(oci_profile)
    if not tenancy_ocid:
        console.print(f"[red]No tenancy OCID for profile {oci_profile} in ~/.oci/config.[/red]")
        sys.exit(1)

    console.print("[dim]Listing subscribed regions…[/dim]")
    subscriptions = _oci_json(["iam", "region-subscription", "list"], oci_profile)
    if not subscriptions:
        console.print("[red]Could not list region subscriptions.[/red] Check the profile's credentials.")
        sys.exit(1)
    regions = sorted(r["region-name"] for r in subscriptions)

    # Identity resources exist only in the home region, which is often not the
    # region the workload runs in, so the two are tracked separately.
    home_region = next(
        (r["region-name"] for r in subscriptions if r.get("is-home-region")), None
    )
    if not home_region:
        console.print("[red]Could not determine the tenancy home region.[/red]")
        sys.exit(1)
    console.print(f"[green]✓[/green] Home region: {home_region}")

    region = inquirer.fuzzy(
        message=f"Workload region — VCN, computes, ADB ({len(regions)} subscribed):",
        choices=regions,
        default=existing.get("OCI_REGION", _oci_profile_region(oci_profile) or ""),
        max_height="60%",
    ).execute()

    # Generative AI runs in a minority of regions, so the list is probed rather
    # than assumed. The workload region and the model region may differ.
    console.print(f"[dim]Probing {len(regions)} regions for Generative AI…[/dim]")
    genai_regions = _genai_regions(oci_profile, regions, tenancy_ocid)
    if not genai_regions:
        console.print(
            "[red]Generative AI does not answer in any subscribed region.[/red]\n"
            "Subscribe to a region that offers it, then re-run."
        )
        sys.exit(1)
    console.print(f"[green]✓[/green] Generative AI in {len(genai_regions)} of {len(regions)}: {', '.join(genai_regions)}")

    genai_region = inquirer.select(
        message="Generative AI region (serves the models):",
        choices=genai_regions,
        default=existing.get("OCI_GENAI_REGION", region if region in genai_regions else genai_regions[0]),
    ).execute()

    compartment_ocid = _select_compartment(oci_profile, tenancy_ocid, existing)

    genai_model, genai_embed_model, genai_embed_dim = _select_genai_models(
        oci_profile, genai_region, tenancy_ocid, existing
    )

    label = inquirer.text(
        message="Resource name prefix:",
        default=existing.get("OCI_LABEL", "paf-poc"),
    ).execute()
    compute_shape = inquirer.text(
        message="Compute shape for the workload instances:",
        default=existing.get("OCI_COMPUTE_SHAPE", "VM.Standard.E5.Flex"),
    ).execute()

    ssh_key_path = inquirer.text(
        message="Public SSH key to install on the computes:",
        default=existing.get("OCI_SSH_KEY_PATH", str(Path.home() / ".ssh" / "id_rsa.pub")),
    ).execute()
    ssh_public_key = Path(ssh_key_path).expanduser()
    if not ssh_public_key.exists():
        console.print(f"[red]{ssh_public_key} not found.[/red]")
        sys.exit(1)

    admin_cidr = inquirer.text(
        message="CIDR allowed to SSH into the bastion:",
        default=existing.get("OCI_ADMIN_CIDR", "0.0.0.0/0"),
    ).execute()

    db_name = inquirer.text(
        message="ADB database name (letters and digits, max 14):",
        default=existing.get("DB_NAME", "pafpoc"),
    ).execute()
    db_password = inquirer.secret(
        message="ADB ADMIN password (leave blank to auto-generate):",
        default="",
    ).execute()
    if not db_password:
        db_password = _generate_password()
        console.print("[green]✓[/green] Generated ADB ADMIN password (saved to .env)")
    wallet_password = inquirer.secret(
        message="ADB wallet password (leave blank to auto-generate):",
        default="",
    ).execute()
    if not wallet_password:
        wallet_password = _generate_password()
        console.print("[green]✓[/green] Generated wallet password (saved to .env)")

    paf_tarball = _resolve_kit_tarball("x86_64")
    console.print(f"[green]✓[/green] PAF kit: {Path(paf_tarball).name}")

    paf_admin_user = inquirer.text(
        message="PAF admin username (entered in the install wizard):",
        default=existing.get("PAF_ADMIN_USER", ""),
    ).execute()
    paf_admin_pass = inquirer.secret(
        message="PAF admin password (leave blank to keep existing):",
        default="",
    ).execute()
    if not paf_admin_pass:
        paf_admin_pass = existing.get("PAF_ADMIN_PASS", "")

    env_content = (
        "# Generated by manage.py setup — do not edit by hand\n"
        "\n"
        "# OCI targeting\n"
        f"OCI_PROFILE={oci_profile}\n"
        f"OCI_TENANCY_OCID={tenancy_ocid}\n"
        f"OCI_HOME_REGION={home_region}\n"
        f"OCI_REGION={region}\n"
        f"OCI_GENAI_REGION={genai_region}\n"
        f"OCI_COMPARTMENT_OCID={compartment_ocid}\n"
        f"OCI_LABEL={label}\n"
        f"OCI_COMPUTE_SHAPE={compute_shape}\n"
        f"OCI_SSH_KEY_PATH={ssh_key_path}\n"
        f"OCI_SSH_PUBLIC_KEY={ssh_public_key.read_text().strip()}\n"
        f"OCI_ADMIN_CIDR={admin_cidr}\n"
        "\n"
        "# Database (Autonomous Database)\n"
        "DB_MODE=adb\n"
        f"DB_NAME={db_name}\n"
        f"DB_SERVICE={db_name}_high\n"
        "DB_ADMIN_USER=ADMIN\n"
        f"DB_PASSWORD={db_password}\n"
        f"DB_WALLET_PASSWORD={wallet_password}\n"
        "\n"
        "# Models (OCI Generative AI — no self-hosted inference on this target).\n"
        "# PAF connects with the oci_instance_principal provider, which carries\n"
        "# model_id, service_endpoint and compartment_id, and no key material.\n"
        "MODEL_PROVIDER=oci_instance_principal\n"
        f"GENAI_ENDPOINT=https://inference.generativeai.{genai_region}.oci.oraclecloud.com\n"
        f"GENAI_MODEL={genai_model}\n"
        f"GENAI_EMBED_MODEL={genai_embed_model}\n"
        f"GENAI_EMBED_DIM={genai_embed_dim}\n"
        "\n"
        "# PAF kit tarball — Terraform uploads it for the paf tier\n"
        f"PAF_TARBALL={paf_tarball}\n"
        "\n"
        "# PAF admin login (used by manage.py's own `paf trust-ca` and\n"
        "# `paf api-key` commands to authenticate against PAF as an\n"
        "# administrator; not used by the backend or the test harness)\n"
        f"PAF_ADMIN_USER={paf_admin_user}\n"
        f"PAF_ADMIN_PASS={paf_admin_pass}\n"
    )
    ENV_FILE.write_text(env_content)
    ENV_FILE.chmod(0o600)
    console.print(f"[green]✓[/green] Wrote {ENV_FILE}")
    console.print("\nNext: [cyan]python manage.py build[/cyan]")


# ---------------------------------------------------------------- OCI discovery

# Generative AI does not report an embedding model's output dimension through
# the API, so the mapping is curated. The vector columns are fixed-width, so a
# mismatch is a hard failure at insert time rather than a warning.
# A value of None means the model's width is configurable and has no fixed
# native size.
EMBEDDING_DIMENSIONS = {
    "cohere.embed-english-v3.0": 1024,
    "cohere.embed-multilingual-v3.0": 1024,
    "cohere.embed-english-light-v3.0": 384,
    "cohere.embed-multilingual-light-v3.0": 384,
    "cohere.embed-v4.0": None,
}


def _oci_json(args: list, profile: str, region: str | None = None,
              timeout: int = 120) -> dict | list | None:
    """Run an OCI CLI query and return its parsed `data`, or None if it failed.

    A region that does not host the service being queried can hang rather than
    refuse, so a timeout counts as "not available" like any other failure.
    """
    cmd = ["oci", *args, "--profile", profile, "--output", "json"]
    if region:
        cmd += ["--region", region]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout).get("data")
    except json.JSONDecodeError:
        return None


def _oci_tenancy_ocid(profile: str) -> str | None:
    config = Path.home() / ".oci" / "config"
    if not config.exists():
        return None
    section = re.search(
        rf"^\[{re.escape(profile)}\](.*?)(?=^\[|\Z)",
        config.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    if not section:
        return None
    match = re.search(r"^tenancy\s*=\s*(\S+)", section.group(1), flags=re.MULTILINE)
    return match.group(1) if match else None


def _schema_embedding_dim() -> int:
    """Vector width the changelog declares, so setup cannot drift from the schema."""
    changelog = PROJECT_ROOT / "database" / "liquibase" / "008-vector-rag.yaml"
    dims = set(re.findall(r"VECTOR\((\d+),", changelog.read_text()))
    if len(dims) != 1:
        console.print(f"[red]Expected one vector width in {changelog.name}, found {dims or 'none'}.[/red]")
        sys.exit(1)
    return int(dims.pop())


def _genai_regions(profile: str, regions: list, tenancy: str) -> list:
    """Subset of `regions` where Generative AI actually answers.

    The service runs in a minority of regions, and a region being subscribed
    says nothing about it — so each is probed rather than assumed.
    """
    def probe(region: str) -> tuple:
        data = _oci_json(
            ["generative-ai", "model-collection", "list-models", "--compartment-id", tenancy],
            profile, region, timeout=45,
        )
        return region, bool(data and data.get("items"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(probe, regions))
    return sorted(r for r, ok in results if ok)


def _genai_models(profile: str, region: str, tenancy: str, capability: str) -> list:
    """Model names in `region` that are ACTIVE and still served on demand.

    ACTIVE alone is not enough: a model whose on-demand serving has retired
    stays ACTIVE and is only reachable through a paid dedicated cluster.
    """
    data = _oci_json(
        ["generative-ai", "model-collection", "list-models", "--compartment-id", tenancy, "--all"],
        profile, region,
    )
    if not data:
        return []

    now = datetime.now(timezone.utc)
    live = set()
    for model in data.get("items", []):
        if model.get("lifecycle-state") != "ACTIVE":
            continue
        if capability not in (model.get("capabilities") or []):
            continue
        retired = model.get("time-on-demand-retired")
        if retired:
            try:
                if datetime.fromisoformat(retired.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                continue
        live.add(model["display-name"])
    return sorted(live)



def _compartment_choices(compartments: list, tenancy: str) -> list:
    """Active compartments as `Parent/Child` paths, so duplicate leaf names stay distinct."""
    by_id = {c["id"]: c for c in compartments}

    def path(ocid: str, seen: frozenset = frozenset()) -> str:
        node = by_id.get(ocid)
        if node is None or ocid in seen:
            return ""
        parent = node.get("compartment-id")
        if parent == tenancy or parent not in by_id:
            return node["name"]
        prefix = path(parent, seen | {ocid})
        return f"{prefix}/{node['name']}" if prefix else node["name"]

    choices = [
        {"name": path(c["id"]), "value": c["id"]}
        for c in compartments
        if c.get("lifecycle-state") == "ACTIVE"
    ]
    choices.sort(key=lambda c: c["name"].lower())
    # Deploying straight into the root is legitimate, so it is offered too.
    return [{"name": "(tenancy root)", "value": tenancy}] + choices


def _select_compartment(profile: str, tenancy: str, existing: dict) -> str:
    """Pick a compartment by typing part of its name.

    A tenancy can hold hundreds, so this filters as you type rather than
    scrolling one screen at a time.
    """
    console.print("[dim]Listing compartments…[/dim]")
    compartments = _oci_json(
        ["iam", "compartment", "list", "--compartment-id", tenancy,
         "--compartment-id-in-subtree", "true", "--all"],
        profile,
    ) or []

    choices = _compartment_choices(compartments, tenancy)
    if len(choices) == 1:
        console.print("[yellow]No compartments listed.[/yellow] Enter the OCID directly.")
        return inquirer.text(
            message="Compartment OCID:",
            default=existing.get("OCI_COMPARTMENT_OCID", ""),
        ).execute()

    # For a fuzzy prompt `default` is the starting search text, so a previous
    # choice comes back as a pre-filled filter rather than a pre-selection.
    previous = existing.get("OCI_COMPARTMENT_OCID")
    prefill = next((c["name"] for c in choices if c["value"] == previous), "")

    return inquirer.fuzzy(
        message=f"Compartment ({len(choices) - 1} available — type to filter):",
        choices=choices,
        default=prefill,
        max_height="60%",
    ).execute()


def _select_genai_models(profile: str, region: str, tenancy: str, existing: dict) -> tuple:
    """Pick a chat and an embedding model, and hold the embedding width to the schema."""
    console.print(f"[dim]Listing on-demand models in {region}…[/dim]")
    chat_models = _genai_models(profile, region, tenancy, "CHAT")
    embed_models = _genai_models(profile, region, tenancy, "TEXT_EMBEDDINGS")

    if not chat_models:
        console.print(f"[red]No on-demand chat model in {region}.[/red]")
        sys.exit(1)
    if not embed_models:
        console.print(
            f"[red]No on-demand embedding model in {region}.[/red] "
            "Pick a Generative AI region that serves one — the RAG path needs it."
        )
        sys.exit(1)

    # PAF streams every agent turn, and two of its OCI Generative AI stream
    # parsers are incomplete: a cohere.* manager never delegates (its text tool
    # call is returned as the reply) and a meta.* stream ends in a bare [DONE]
    # that fails json.loads. Models on the generic format that end their stream
    # with finishReason work as-is; gpt-oss-120b is the verified default.
    # See issues/14-oci-genai-stream-parsers-incomplete.md.
    def streams_through_paf(model: str) -> bool:
        return not model.startswith(("cohere.", "meta."))

    preferred = "openai.gpt-oss-120b"
    supported = [m for m in chat_models if streams_through_paf(m)]
    chat_choices = [
        {"name": m if streams_through_paf(m) else f"{m}  (streaming unsupported by PAF)", "value": m}
        for m in chat_models
    ]
    previous = existing.get("GENAI_MODEL")
    if previous in supported:
        default = previous
    elif preferred in chat_models:
        default = preferred
    else:
        default = supported[0] if supported else None
    genai_model = inquirer.select(
        message="Generation model:",
        choices=chat_choices,
        default=default,
    ).execute()

    if not streams_through_paf(genai_model):
        console.print(
            f"[yellow]{genai_model} streams in a shape PAF does not fully parse.[/yellow]\n"
            "A cohere.* manager agent never delegates to its workers, and a meta.* stream\n"
            "fails with a JSONDecodeError. Pick a model on the generic format unless you\n"
            "have verified otherwise."
        )
        if not inquirer.confirm(message="Use it anyway?", default=False).execute():
            sys.exit(1)

    # The vector columns are fixed-width, so an embedding model of the wrong
    # width fails on insert rather than at deploy. Steer the choice by width.
    schema_dim = _schema_embedding_dim()
    choices = []
    for name in embed_models:
        dim = EMBEDDING_DIMENSIONS.get(name, "unknown")
        if dim == schema_dim:
            label = f"{name}  ({dim} dims — matches the schema)"
        elif dim is None:
            label = f"{name}  (configurable width, no fixed native size)"
        elif dim == "unknown":
            label = f"{name}  (width unknown)"
        else:
            label = f"{name}  ({dim} dims — schema needs {schema_dim})"
        choices.append({"name": label, "value": name})

    native = [n for n in embed_models if EMBEDDING_DIMENSIONS.get(n) == schema_dim]
    genai_embed_model = inquirer.select(
        message=f"Embedding model (schema declares {schema_dim} dimensions):",
        choices=choices,
        default=native[0] if native else None,
    ).execute()

    dim = EMBEDDING_DIMENSIONS.get(genai_embed_model, "unknown")
    if dim == schema_dim:
        console.print(f"[green]✓[/green] {genai_embed_model} emits {schema_dim} dimensions")
    elif isinstance(dim, int):
        console.print(
            f"[red]{genai_embed_model} emits {dim} dimensions; the schema declares {schema_dim}.[/red]\n"
            "Choose a matching model, or change the VECTOR width in "
            "database/liquibase/008-vector-rag.yaml and reseed."
        )
        sys.exit(1)
    else:
        # PAF's instance-principal connection carries only model_id,
        # service_endpoint and compartment_id — there is no output_dimension to
        # pin, so a configurable model cannot be held to the schema's width.
        console.print(
            f"[yellow]{genai_embed_model} has no fixed output width.[/yellow] PAF's "
            "instance-principal connection has no output_dimension field, so it cannot be "
            f"pinned to {schema_dim}. Prefer a model with a native {schema_dim}-dimension "
            "output; regions differ in which ones they serve."
        )
        if not inquirer.confirm(message="Use it anyway?", default=False).execute():
            sys.exit(1)

    return genai_model, genai_embed_model, schema_dim


# ---------------------------------------------------------------- terraform


def _oci_profiles() -> list:
    """Profile names from the OCI CLI config, DEFAULT first. Empty when absent."""
    if not OCI_CONFIG.exists():
        return []
    parser = configparser.ConfigParser()
    parser.read(OCI_CONFIG)
    return (["DEFAULT"] if parser.defaults() else []) + parser.sections()


def _oci_profile_region(profile: str) -> str | None:
    """The region already configured for a profile, used as the prompt default."""
    config = Path.home() / ".oci" / "config"
    if not config.exists():
        return None
    section = re.search(
        rf"^\[{re.escape(profile)}\](.*?)(?=^\[|\Z)",
        config.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    if not section:
        return None
    match = re.search(r"^region\s*=\s*(\S+)", section.group(1), flags=re.MULTILINE)
    return match.group(1) if match else None


@cli.command("tf")
def tf() -> None:
    """Render the tfvars for both Terraform roots from .env."""
    _ensure_env()

    roots = {
        TF_VARS_TEMPLATE: (TF_VARS_FILE, [
            "OCI_PROFILE", "OCI_REGION", "OCI_GENAI_REGION", "OCI_COMPARTMENT_OCID",
            "OCI_LABEL", "OCI_SSH_PUBLIC_KEY", "OCI_ADMIN_CIDR", "OCI_COMPUTE_SHAPE",
            "DB_NAME", "DB_PASSWORD", "DB_WALLET_PASSWORD", "PAF_TARBALL", "GENAI_MODEL",
        ]),
        TF_IAM_VARS_TEMPLATE: (TF_IAM_VARS_FILE, [
            "OCI_PROFILE", "OCI_HOME_REGION", "OCI_TENANCY_OCID", "OCI_COMPARTMENT_OCID", "OCI_LABEL",
        ]),
    }

    for template_path, (out_path, keys) in roots.items():
        missing = [k for k in keys if not os.environ.get(k)]
        if missing:
            console.print(f"[red]Missing in .env:[/red] {', '.join(missing)}")
            console.print("Re-run [cyan]python manage.py setup[/cyan].")
            sys.exit(1)
        rendered = string.Template(template_path.read_text()).substitute(
            {k: os.environ[k] for k in keys}
        )
        out_path.write_text(rendered)
        out_path.chmod(0o600)
        console.print(f"[green]✓[/green] Wrote {out_path}")

    console.print("\nNext: [cyan]python manage.py cloud iam[/cyan] then [cyan]python manage.py cloud up[/cyan]")


# ---------------------------------------------------------------- info

TIERS = ("ops", "paf", "backend", "frontend")


def _tier_readiness(tier: str) -> tuple[str, str]:
    """Where a tier stands: its bootstrap sentinel, or why it cannot be read.

    Cloud-init writes /var/lib/<label>/bootstrap.ok only after the tier's play
    returns success, so the sentinel is the one trustworthy readiness signal.
    """
    label = os.getenv("OCI_LABEL", "paf-poc")
    result = _tier_ssh(
        tier,
        f"test -f /var/lib/{label}/bootstrap.ok && echo built || echo building",
        timeout=40,
    )
    out = (result.stdout or "").strip()
    if "built" in out:
        return "green", "ready"
    if "building" in out:
        return "yellow", "building — the play has not finished"
    if "timed out" in (result.stderr or ""):
        return "red", "no answer — still booting, or unreachable"
    return "red", "unreachable"


@cli.command("info")
def info() -> None:
    """Print URLs, connection strings, and whether every tier has finished building."""
    _ensure_env()
    lb_ip = _tf_output("lb_ip")
    if not lb_ip:
        console.print(
            "[yellow]No Terraform output yet.[/yellow] Apply deploy/tf/app first."
        )
        return

    console.print(f"Load balancer:  {lb_ip}")
    console.print(f"Chat UI:        https://{lb_ip}/")
    console.print(f"Backoffice UI:  https://{lb_ip}/backoffice")
    console.print(f"Application API:https://{lb_ip}/v1")
    console.print(f"PAF:            https://{lb_ip}/agentFactory")
    console.print(f"Bastion:        ssh opc@{_tf_output('ops_public_ip') or '<unknown>'}")
    console.print(f"ADB service:    {os.getenv('DB_SERVICE')}   (wallet: {_tf_output('adb_wallet_path') or 'not generated'})")
    console.print(f"App schemas:    APP, REPORTING, AGENT_TOOLS, AGENT_FACTORY")
    console.print(f"Models:         {os.getenv('GENAI_MODEL')} / {os.getenv('GENAI_EMBED_MODEL')}")
    console.print(f"                via {os.getenv('GENAI_ENDPOINT')}")
    console.print(f"                instance principal — no key material")

    # Checked over the bastion rather than the load balancer: a tier answers on
    # the load balancer only once its play has finished, so the sentinel says
    # "building" where a health check would just say "down".
    console.print("\n[bold]Tiers[/bold]")
    with ThreadPoolExecutor(max_workers=len(TIERS)) as pool:
        states = dict(zip(TIERS, pool.map(_tier_readiness, TIERS)))
    for tier in TIERS:
        colour, note = states[tier]
        mark = "\u2713" if colour == "green" else "\u00b7"
        console.print(f"  [{colour}]{mark}[/{colour}] [cyan]{tier:<9}[/cyan] {note}")

    if all(colour == "green" for colour, _ in states.values()):
        console.print("\n[green]The stack is ready.[/green] Next: "
                      "[cyan]python manage.py paf bootstrap[/cyan]")
    else:
        console.print(
            "\n[yellow]Not ready yet.[/yellow] Cloud-init retries every 60s; re-run "
            "this. A tier stuck for longer than a few minutes is diagnosed from "
            "[cyan]/var/log/" + os.getenv("OCI_LABEL", "paf-poc") + "-bootstrap.log[/cyan] on that instance."
        )


# ---------------------------------------------------------------- cloud


def _tf_args(root: Path, *args: str) -> list:
    """Terraform invoked against a root with -chdir, never by cd-ing into it."""
    return ["terraform", f"-chdir={root}", *args]


def _tf_run(root: Path, *args: str) -> None:
    _run(_tf_args(root, *args))


def _require_tfvars(path: Path) -> None:
    if not path.exists():
        console.print(f"[red]{path} not found.[/red] Run `python manage.py tf` first.")
        sys.exit(1)


@cli.group()
def cloud() -> None:
    """Cloud (OCI) lifecycle."""


@cloud.command("iam")
def cloud_iam() -> None:
    """Create the dynamic groups and Generative AI policy. Needs tenancy-admin rights."""
    _ensure_env()
    _require_tfvars(TF_IAM_VARS_FILE)
    console.print(Panel.fit("[bold]Tenancy IAM[/bold]"))
    console.print(
        f"[dim]Identity resources are created in the home region "
        f"({os.getenv('OCI_HOME_REGION')}), not the workload region.[/dim]"
    )
    _tf_run(TF_IAM_DIR, "init", "-input=false")
    _tf_run(TF_IAM_DIR, "apply", "-input=false", "-auto-approve")
    console.print("\n[green]✓[/green] Next: [cyan]python manage.py cloud up[/cyan]")


# Terraform zips the Ansible directories at apply time, so a tier whose payload
# was never staged fetches an artifact with no application in it and fails
# during its own play — on the instance, long after the apply reported success.
STAGED_PAYLOADS = (
    ANSIBLE_ROOT / "backend" / "roles" / "appstack" / "files" / "app.jar",
    ANSIBLE_ROOT / "frontend" / "roles" / "webstack" / "files" / "customer",
    ANSIBLE_ROOT / "frontend" / "roles" / "webstack" / "files" / "backoffice",
    ANSIBLE_ROOT / "ops" / "roles" / "opstools" / "files" / "database" / "liquibase",
)


def _require_build() -> None:
    missing = [p for p in STAGED_PAYLOADS if not p.exists()]
    if missing:
        console.print("[red]Tier payloads are not staged.[/red] Missing:")
        for path in missing:
            console.print(f"  • {path.relative_to(PROJECT_ROOT)}")
        console.print("Run [cyan]python manage.py build[/cyan] first.")
        sys.exit(1)


@cloud.command("up")
def cloud_up() -> None:
    """Provision the workload stack: network, ADB, the four tiers and the load balancer."""
    _ensure_env()
    _require_tfvars(TF_VARS_FILE)
    _require_build()
    console.print(Panel.fit("[bold]Cloud stack[/bold]"))
    # Cheap, and keeps an edited changelog or policy bundle from being missed.
    _stage_sources()
    _tf_run(TF_DIR, "init", "-input=false")
    _tf_run(TF_DIR, "apply", "-input=false", "-auto-approve")
    console.print(
        "\n[green]✓[/green] Applied. Each tier now builds itself from cloud-init; "
        "watch for the bootstrap sentinel before using it.\n"
        "Next: [cyan]python manage.py info[/cyan], then [cyan]python manage.py paf bootstrap[/cyan]"
    )


@cloud.command("plan")
def cloud_plan() -> None:
    """Show what the workload stack would change, without applying it."""
    _ensure_env()
    _require_tfvars(TF_VARS_FILE)
    _tf_run(TF_DIR, "init", "-input=false")
    _tf_run(TF_DIR, "plan")



def _ops_ssh(command: str, *, stream: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command on the ops bastion."""
    ip = _tf_output("ops_public_ip")
    if not ip:
        console.print("[red]No bastion address.[/red] Apply deploy/tf/app first.")
        sys.exit(1)
    key_path = Path(os.getenv("OCI_SSH_KEY_PATH", "")).expanduser()
    private_key = key_path.with_suffix("") if key_path.suffix == ".pub" else key_path
    argv = ["ssh", "-i", str(private_key), "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=20", f"opc@{ip}", command]
    if stream:
        return subprocess.run(argv)
    return subprocess.run(argv, capture_output=True, text=True, timeout=300)


def _tier_host(tier: str) -> str:
    """A tier's VCN address.

    The VCN's DNS label is the resource label with dashes removed, so tiers
    resolve each other at <tier>.private.<label>.oraclevcn.com.
    """
    vcn_dns = os.getenv("OCI_LABEL", "paf-poc").replace("-", "")
    return f"{tier}.private.{vcn_dns}.oraclevcn.com"


def _backend_host() -> str:
    return _tier_host("backend")


def _tier_ssh(tier: str, command: str, *, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a shell command on a tier, jumping through the bastion.

    Only the bastion has a public address; the rest of the tiers are reachable
    from it, and every instance accepts the same key.
    """
    ip = _tf_output("ops_public_ip")
    if not ip:
        console.print("[red]No bastion address.[/red] Apply deploy/tf/app first.")
        sys.exit(1)
    key_path = Path(os.getenv("OCI_SSH_KEY_PATH", "")).expanduser()
    private_key = key_path.with_suffix("") if key_path.suffix == ".pub" else key_path
    opts = ["-i", str(private_key), "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
    jump = " ".join(["ssh", "-i", shlex.quote(str(private_key)),
                     "-o", "StrictHostKeyChecking=no",
                     "-o", "UserKnownHostsFile=/dev/null",
                     "-o", "LogLevel=ERROR", "-W", "%h:%p", f"opc@{ip}"])
    argv = ["ssh", *opts, "-o", "ConnectTimeout=20"]
    # The bastion is reached directly; every other tier through it.
    if tier == "ops":
        argv += [f"opc@{ip}", command]
    else:
        argv += ["-o", f"ProxyCommand={jump}", f"opc@{_tier_host(tier)}", command]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 255, "", "timed out")


def _backend_ssh(command: str) -> subprocess.CompletedProcess:
    return _tier_ssh("backend", command)


def _ops_push_tests() -> None:
    """Copy the repository's tests/ to the bastion, so a run exercises the current
    harness rather than the copy that shipped in the tier's artifact."""
    ip = _tf_output("ops_public_ip")
    key_path = Path(os.getenv("OCI_SSH_KEY_PATH", "")).expanduser()
    private_key = key_path.with_suffix("") if key_path.suffix == ".pub" else key_path
    result = subprocess.run(
        ["scp", "-q", "-r", "-i", str(private_key), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
         str(PROJECT_ROOT / "tests"), f"opc@{ip}:/home/opc/artifact/roles/opstools/files/"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        console.print(f"[red]Could not copy tests/ to the bastion.[/red]\n{result.stderr.strip()[:300]}")
        sys.exit(1)


# Unknown options belong to pytest, not to click.
@cloud.command("test", context_settings={"ignore_unknown_options": True})
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cloud_test(pytest_args: tuple) -> None:
    """Run the end-to-end harness from the ops bastion.

    The tests assert against `hitl_task` rows as well as the agent's reply, and
    Autonomous Database is on a private endpoint — so they run where both PAF
    and the database are reachable, not from here.
    """
    _ensure_env()
    for key in ("PAF_API_KEY", "PAF_AGENT_ID"):
        if not os.getenv(key):
            console.print(
                f"[red]{key} is not set.[/red] Publish CHAT_FLOW, then run "
                "[cyan]python manage.py paf api-key[/cyan]."
            )
            sys.exit(1)

    # Written on the bastion for the run and removed afterwards; it carries the
    # integration key and the database password.
    env_lines = "\n".join([
        f"PAF_API_KEY={os.environ['PAF_API_KEY']}",
        f"PAF_AGENT_ID={os.environ['PAF_AGENT_ID']}",
        f"DB_SERVICE={os.getenv('DB_SERVICE', '')}",
        f"DB_PASSWORD={os.getenv('DB_PASSWORD', '')}",
        f"DB_WALLET_PASSWORD={os.getenv('DB_WALLET_PASSWORD', '')}",
    ])
    remote_env = "/home/opc/.poc-test-env"
    # The unit tests import from src/, which stays on the host, so the bastion
    # runs the end-to-end suite only; extra arguments (-k, -x, -vv) pass through.
    # The public load balancer terminates TLS with a self-signed certificate —
    # there is no DNS name to issue against — so the harness calls PAF with
    # verification off and urllib3 warns once per turn. The filter rides on the
    # command rather than in conftest, because pytest resets the warning filters
    # around every test item, and rather than in pytest.ini, because only
    # `tests/` is copied to the bastion.
    # Quoted: a multi-word selector (-k "alice or frank") reaches the bastion as
    # one pytest argument instead of three shell words.
    args = " ".join([
        "tests/test_chat_workflow.py",
        "-W", "ignore::urllib3.exceptions.InsecureRequestWarning",
        *(shlex.quote(a) for a in pytest_args),
    ])
    script = (
        f"set -e; umask 077; cat > {remote_env} <<'EOF'\n{env_lines}\nEOF\n"
        f"cd /home/opc/artifact/roles/opstools/files && "
        f"POC_ENV_FILE={remote_env} "
        f"PAF_BASE={_paf_base_url()} "
        f"TNS_ADMIN=/opt/paf-poc/wallet "
        f"{'{{ tests_venv }}'} -m pytest {args} -q; rc=$?; rm -f {remote_env}; exit $rc"
    ).replace("{{ tests_venv }}", "/opt/paf-poc/tests-venv/bin/python")

    console.print(Panel.fit("[bold]End-to-end tests (from the bastion)[/bold]"))
    console.print(f"[dim]PAF: {_paf_base_url()}   database: {os.getenv('DB_SERVICE')} via wallet[/dim]")
    _ops_push_tests()
    result = _ops_ssh(script, stream=True)
    if result.returncode != 0:
        sys.exit(result.returncode)


@cloud.command("sql")
@click.argument("statement")
def cloud_sql(statement: str) -> None:
    """Run one SQL statement or PL/SQL block against ADB as ADMIN from the
    bastion. Prints the rows of a query, the row count of a DML statement, and
    anything the block wrote with DBMS_OUTPUT. A DML statement is committed."""
    _ensure_env()
    script = """
import json, oracledb
p = json.load(open("/home/opc/ansible_params.json"))
con = oracledb.connect(user="ADMIN", password=p["adb_admin_password"], dsn=p["adb_service"],
                       config_dir="/opt/paf-poc/wallet", wallet_location="/opt/paf-poc/wallet",
                       wallet_password=p["wallet_password"])
cur = con.cursor()
cur.callproc("dbms_output.enable", [None])
text = STATEMENT.strip()
if not text.rstrip().endswith("/") and text.lstrip().upper()[:7] not in ("DECLARE", "BEGIN"):
    text = text.rstrip().rstrip(";")
cur.execute(text.rstrip().rstrip("/"))
if cur.description:
    print(" | ".join(d[0] for d in cur.description))
    for row in cur:
        print(" | ".join("" if v is None else str(v) for v in row))
else:
    con.commit()
    if cur.rowcount:
        print(f"{cur.rowcount} row(s)")
line = cur.var(str); status = cur.var(int)
while True:
    cur.callproc("dbms_output.get_line", (line, status))
    if status.getvalue() != 0:
        break
    print(line.getvalue())
"""
    result = _ops_python(script.replace("STATEMENT", repr(statement)))
    out = (result.stdout or "").rstrip()
    if result.returncode != 0:
        err = [l[l.index("ORA-"):] for l in (result.stderr or "").splitlines() if "ORA-" in l]
        console.print("[red]" + (err[0] if err else "Statement failed.") + "[/red]")
        if out:
            console.print(out)
        sys.exit(1)
    console.print(out or "[dim]done[/dim]")


@cloud.command("reset")
def cloud_reset() -> None:
    """Empty the reviewer queue, both chat histories, the login sessions and the
    tool traces, so a test run or a demo starts from the seeded state.

    The seeded customers and their applications are untouched, so a customer
    already processed can be run again. APP.decision is left alone: it is a
    blockchain table declared NO DELETE LOCKED, and outliving a reset is the
    property the demo exists to show.
    """
    _ensure_env()
    script = """
import json, oracledb
p = json.load(open("/home/opc/ansible_params.json"))
con = oracledb.connect(user="ADMIN", password=p["adb_admin_password"], dsn=p["adb_service"],
                       config_dir="/opt/paf-poc/wallet", wallet_location="/opt/paf-poc/wallet",
                       wallet_password=p["wallet_password"])
cur = con.cursor()
# Nothing references hitl_task, and the rest hang off customer and
# loan_application, so no order is forced on these.
for table in ("hitl_task", "chat_message", "auth_session", "decision_audit"):
    cur.execute("DELETE FROM APP." + table)
    print(table, cur.rowcount)
con.commit()
cur.execute("SELECT COUNT(*) FROM APP.decision")
print("decision", cur.fetchone()[0])
"""
    console.print(Panel.fit("[bold]Resetting the demo data[/bold]"))
    result = _ops_python(script)
    if result.returncode != 0:
        err = [l[l.index("ORA-"):] for l in (result.stderr or "").splitlines() if "ORA-" in l]
        console.print("[red]" + (err[0] if err else "Reset failed.") + "[/red]")
        console.print((result.stdout or "").strip()[:400])
        sys.exit(1)

    labels = {
        "hitl_task": "reviewer queue",
        "chat_message": "chat messages",
        "auth_session": "login sessions",
        "decision_audit": "tool traces",
    }
    kept = 0
    for line in (result.stdout or "").splitlines():
        name, _, count = line.rpartition(" ")
        if name in labels:
            console.print(f"  [cyan]{labels[name]:<16}[/cyan] {count} removed")
        elif name == "decision":
            kept = count
    console.print(f"[green]\u2713[/green] Queue and chats are clear.")
    console.print(
        f"[dim]  APP.decision keeps its {kept} row(s) — a blockchain table declared "
        f"NO DELETE LOCKED.[/dim]"
    )


@cloud.command("down")
def cloud_down() -> None:
    """Destroy the workload stack. The IAM root is left alone for the next deployment."""
    _ensure_env()
    console.print(Panel.fit("[bold]Destroying the cloud stack[/bold]"))

    # The database's private endpoint VNIC is released asynchronously, so its
    # network security group still reports attached VNICs for a few seconds
    # after the database itself is gone and the delete fails with a 412. The
    # ordering is already correct; the API is just behind. Destroy skips what
    # has gone, so a second pass finishes the job.
    for attempt in (1, 2, 3):
        console.print(f"[dim]$ {' '.join(_tf_args(TF_DIR, 'destroy'))}[/dim]")
        result = subprocess.run(_tf_args(TF_DIR, "destroy", "-input=false", "-auto-approve"))
        if result.returncode == 0:
            break
        if attempt < 3:
            console.print(
                f"[yellow]Destroy incomplete (pass {attempt}).[/yellow] "
                "Usually a resource whose dependant is still detaching — retrying in 30s."
            )
            time.sleep(30)
    else:
        console.print(
            "[red]Destroy did not complete after three passes.[/red] "
            "Re-run, or check the OCI console for what is still attached."
        )
        sys.exit(1)

    console.print("\n[green]✓[/green] Destroyed. Run [cyan]python manage.py clean[/cyan] to remove generated files.")


# ---------------------------------------------------------------- paf

@cli.group()
def paf() -> None:
    """Private Agent Factory operations."""


@paf.command("allow-internal-mcp")
def paf_allow_internal_mcp() -> None:
    """Relax PAF's outbound-URL guard so the internal load balancer can be
    registered: sets BLOCK_PRIVATE_OUTBOUND_URLS=false in PAF's app settings.

    The MCP servers sit on a private address, which PAF blocks by default even
    over https. ALLOW_INSECURE_HTTP_URLS stays false. Applied to Autonomous
    Database through the bastion; run once after the install wizard completes.
    """
    _ensure_env()
    script = """
import json, oracledb
p = json.load(open("/home/opc/ansible_params.json"))
con = oracledb.connect(user="ADMIN", password=p["adb_admin_password"], dsn=p["adb_service"],
                       config_dir="/opt/paf-poc/wallet", wallet_location="/opt/paf-poc/wallet",
                       wallet_password=p["wallet_password"])
cur = con.cursor()
try:
    cur.execute("UPDATE AGENT_FACTORY.AAI_APPLICATION_SETTINGS SET value='false' "
                "WHERE field='BLOCK_PRIVATE_OUTBOUND_URLS'")
    con.commit()
except Exception as exc:
    print("SETTINGS_TABLE_MISSING", exc); raise SystemExit(0)
cur.execute("SELECT field||'='||value FROM AGENT_FACTORY.AAI_APPLICATION_SETTINGS "
            "WHERE field IN ('BLOCK_PRIVATE_OUTBOUND_URLS','ALLOW_INSECURE_HTTP_URLS')")
for (row,) in cur:
    print(row)
"""
    result = _ops_python(script)
    out = (result.stdout or "") + (result.stderr or "")
    if "BLOCK_PRIVATE_OUTBOUND_URLS=false" in out:
        console.print("[green]\u2713[/green] BLOCK_PRIVATE_OUTBOUND_URLS=false")
        for line in out.splitlines():
            if "ALLOW_INSECURE_HTTP_URLS" in line:
                console.print(f"[dim]  {line.strip()}[/dim]")
        return
    if "SETTINGS_TABLE_MISSING" in out:
        console.print(
            "[red]PAF's settings table does not exist yet.[/red] "
            "Finish the install wizard first — it creates the table."
        )
        sys.exit(1)
    console.print(f"[red]Could not apply the setting.[/red]\n{out.strip()[:400]}")
    sys.exit(1)



@paf.command("admin")
def paf_admin() -> None:
    """Record the PAF admin credentials created in the install wizard.

    `setup` has to ask for these before PAF exists, so whatever it stored is a
    guess. This writes what the wizard actually created, which is what the
    `trust-ca` and `api-key` commands authenticate with.
    """
    _ensure_env()
    user = inquirer.text(
        message="PAF admin username (as created in the install wizard):",
        default=os.getenv("PAF_ADMIN_USER", ""),
    ).execute()
    password = inquirer.secret(message="PAF admin password:").execute()
    if not user or not password:
        console.print("[red]Both are required.[/red]")
        sys.exit(1)
    _write_env_key("PAF_ADMIN_USER", user)
    _write_env_key("PAF_ADMIN_PASS", password)
    console.print(f"[green]\u2713[/green] Saved to {ENV_FILE}")

    session = _paf_session()
    if session:
        console.print(f"[green]\u2713[/green] Signed in to PAF at {_paf_base_url()}")


@paf.command("trust-ca")
def paf_trust_ca() -> None:
    """Register the MCP gateway CA in PAF's administrator certificate store.

    PAF's outbound HTTP clients read this store when they dial MCP servers, so
    the internal load balancer's https URLs verify. The store lives on PAF's
    mounted volume. Run once per install, after the wizard.
    """
    _ensure_env()
    crt = TF_DIR / "generated" / "mcp-ca.pem"
    if not crt.exists():
        console.print(f"[red]{crt} not found.[/red] Run `python manage.py cloud up` first.")
        sys.exit(1)
    session = _paf_session()
    with crt.open("rb") as handle:
        r = session.post(
            f"{_paf_base_url()}/agentFactory/v1/certs",
            headers={"Origin": _paf_base_url()},
            files={"certificate": (crt.name, handle, "application/x-pem-file")},
            timeout=30,
        )
    if r.status_code == 201:
        console.print("[green]✓[/green] MCP gateway CA registered in PAF's trust store.")
    elif r.status_code == 200:
        console.print("[green]✓[/green] MCP gateway CA already registered.")
    else:
        console.print(
            f"[red]Certificate upload failed: HTTP {r.status_code}[/red]\n{r.text[:500]}"
        )
        sys.exit(1)
    console.print(
        "[dim]MCP connection tests pick up the new trust store on the next test.[/dim]"
    )


def _live_mcp_source_ids(session: requests.Session) -> dict:
    """Map each registered MCP server name to its numeric source id."""
    r = session.get(f"{_paf_base_url()}/agentFactory/v1/tools/mcp/sources", timeout=30)
    if r.status_code != 200:
        console.print(
            f"[red]Could not list MCP servers: HTTP {r.status_code}.[/red]\n{r.text[:300]}"
        )
        sys.exit(1)
    body = r.json()
    items = body if isinstance(body, list) else body.get("data") or body.get("items") or []
    if isinstance(items, dict):
        items = items.get("items", [])
    return {i["SERVER_NAME"]: i["ID"] for i in items if i.get("SERVER_NAME")}


def _iter_server_source_fields(node):
    """Yield every `serverSource` template field in a flow graph."""
    if isinstance(node, dict):
        field = node.get("serverSource")
        if isinstance(field, dict) and "componentProps" in field:
            yield field
        for value in node.values():
            yield from _iter_server_source_fields(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_server_source_fields(value)


@paf.command("link-flow")
def paf_link_flow() -> None:
    """Bind each MCP tool node in CHAT_FLOW to the right MCP server.

    A flow stores its MCP servers as numeric source ids, which depend on the
    order the servers were registered. This rebinds every node by server name,
    so the flow works whatever ids this instance assigned. Run after importing
    the flow, and again after re-registering any MCP server.
    """
    _ensure_env()
    session = _paf_session()
    agent_id = _discover_chat_flow_id(session)

    r = session.get(f"{_paf_base_url()}/agentFactory/v1/agents/{agent_id}", timeout=30)
    if r.status_code != 200:
        console.print(f"[red]Could not read the flow: HTTP {r.status_code}.[/red]\n{r.text[:300]}")
        sys.exit(1)
    payload = r.json()
    record = payload.get("data", payload)
    graph = record.get("data")
    if not isinstance(graph, dict):
        console.print(
            "[red]The flow has no visual graph to rebind.[/red] "
            "Import it per paf/flows/CHAT_FLOW.md first."
        )
        sys.exit(1)

    live = _live_mcp_source_ids(session)
    changes, unknown = [], set()
    for field in _iter_server_source_fields(graph):
        options = field.get("componentProps", {}).get("options") or []
        name = next((o.get("label") for o in options if o.get("label")), None)
        if not name:
            continue
        target = live.get(name)
        if target is None:
            unknown.add(name)
            continue
        if field.get("value") != target:
            changes.append((name, field.get("value"), target))
        field["value"] = target
        for option in options:
            option["value"] = target

    if unknown:
        console.print(
            f"[red]These MCP servers are not registered:[/red] {', '.join(sorted(unknown))}\n"
            f"Registered: {', '.join(sorted(live)) or '(none)'}\n"
            "Register them per `paf bootstrap` step 8, then re-run."
        )
        sys.exit(1)

    if not changes:
        console.print("[green]✓[/green] Every MCP node already points at the right server.")
        return

    r = session.put(
        f"{_paf_base_url()}/agentFactory/v1/agents/{agent_id}/data",
        headers={"Origin": _paf_base_url()},
        json={"data": graph},
        timeout=60,
    )
    if r.status_code != 200:
        console.print(f"[red]Could not save the flow: HTTP {r.status_code}.[/red]\n{r.text[:500]}")
        sys.exit(1)

    for name, before, after in changes:
        console.print(f"  [cyan]{name}[/cyan]: {before} → {after}")
    console.print(f"[green]✓[/green] Rebound {len(changes)} MCP node(s) in CHAT_FLOW.")
    console.print("[dim]Publish the flow so the change reaches the integration endpoint.[/dim]")


@paf.command("gen-model")
def paf_gen_model() -> None:
    """Point PAF's `gen-model` configuration at the GENAI_MODEL in .env.

    The model id is the only field that changes when swapping generation
    models on OCI Generative AI, and CHAT_FLOW references the configuration
    by name, so the flow needs no edit.
    """
    _ensure_env()
    model_id = os.getenv("GENAI_MODEL", "").strip()
    if not model_id:
        console.print("[red]GENAI_MODEL is not set in .env.[/red] Run [cyan]python manage.py setup[/cyan].")
        sys.exit(1)
    session = _paf_session()
    r = session.get(f"{_paf_base_url()}/agentFactory/v1/getSavedLLMConfigurations", timeout=30)
    if r.status_code != 200:
        console.print(f"[red]Could not list LLM configurations: HTTP {r.status_code}.[/red]\n{r.text[:300]}")
        sys.exit(1)
    items = r.json().get("data", {}).get("savedConfiguration", [])
    entry = next((i for i in items if i.get("name") == "gen-model"), None)
    if entry is None:
        console.print("[red]No LLM configuration named gen-model.[/red] Create it per `paf bootstrap` step 4.")
        sys.exit(1)
    details = entry.get("connectionDetails") or {}
    if isinstance(details, str):
        details = json.loads(details)
    current = details.get("model_id")
    if current == model_id:
        console.print(f"[green]✓[/green] gen-model already uses [cyan]{model_id}[/cyan].")
        return
    details["model_id"] = model_id
    r = session.put(
        f"{_paf_base_url()}/agentFactory/v1/saveLLMConfig",
        headers={"Origin": _paf_base_url()},
        data={"name": "gen-model", "provider": entry.get("provider"),
              "connectionDetails": json.dumps(details)},
        timeout=60,
    )
    if r.status_code != 200:
        console.print(f"[red]Could not save gen-model: HTTP {r.status_code}.[/red]\n{r.text[:500]}")
        sys.exit(1)
    console.print(f"[green]✓[/green] gen-model: [cyan]{current}[/cyan] → [cyan]{model_id}[/cyan]")


@paf.command("api-key")
def paf_api_key() -> None:
    """Mint an integration API key for CHAT_FLOW and store it in .env.

    Writes PAF_AGENT_ID and PAF_API_KEY. The flow must be published first — PAF
    refuses to run an unpublished workflow through an integration key. Keys last
    at most 90 days; re-run this to mint a replacement.
    """
    _ensure_env()
    session = _paf_session()
    agent_id = _discover_chat_flow_id(session)
    r = session.post(
        f"{_paf_base_url()}/agentFactory/v1/integrations/agents/{agent_id}/keys",
        headers={"Origin": _paf_base_url()},
        json={"name": "application-backend"},
        timeout=30,
    )
    if r.status_code != 201:
        console.print(
            f"[red]Key creation failed: HTTP {r.status_code}[/red]\n{r.text[:500]}"
        )
        sys.exit(1)
    body = r.json()
    key = body.get("key")
    if not key:
        console.print(f"[red]PAF returned no key value.[/red] {body}")
        sys.exit(1)
    _write_env_key("PAF_AGENT_ID", agent_id)
    _write_env_key("PAF_API_KEY", key)
    console.print(
        f"[green]✓[/green] Key minted for agent [cyan]{agent_id}[/cyan] "
        f"(prefix [cyan]{body.get('keyPrefix', '')}[/cyan]), expires "
        f"[cyan]{body.get('expiresAt', 'in 90 days')}[/cyan]."
    )
    console.print(
        "[dim]PAF_AGENT_ID and PAF_API_KEY written to .env. The backend tier reads "
        "them at deploy time, so re-run [cyan]python manage.py cloud up[/cyan] to "
        "hand them over — or [cyan]python manage.py cloud test[/cyan], which passes "
        "them to the harness directly.[/dim]"
    )



@paf.command("openapi")
def paf_openapi() -> None:
    """Save the Company Registry's OpenAPI document for PAF's importer.

    The registry listens on a private address, and PAF's data-source form takes
    an uploaded file rather than a URL. The bastion is the only host that can
    reach both, so it fetches the spec and the response is written here.
    """
    _ensure_env()
    url = f"http://{_backend_host()}:8600/openapi.json"
    console.print(f"Fetching [cyan]{url}[/cyan] from the bastion")

    result = _ops_ssh(f"curl -sS --max-time 20 {url}")
    if result.returncode != 0 or not result.stdout.strip():
        console.print(
            f"[red]Could not fetch the spec.[/red]\n{(result.stderr or '').strip()[:400]}\n"
            "The registry runs on the backend tier — check paf-poc-registry there."
        )
        sys.exit(1)

    try:
        spec = json.loads(result.stdout)
    except json.JSONDecodeError:
        console.print(f"[red]The response is not JSON.[/red]\n{result.stdout.strip()[:400]}")
        sys.exit(1)

    KIT_DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = KIT_DIST_DIR / "company-registry-openapi.json"
    target.write_text(json.dumps(spec, indent=2) + "\n")

    servers = ", ".join(s.get("url", "") for s in spec.get("servers", []))
    console.print(f"[green]✓[/green] {target}")
    console.print(f"[dim]  servers: {servers}[/dim]")
    console.print("[dim]  Upload this file in PAF: Data Sources → Rest API → "
                  "OpenAPI specification.[/dim]")


def _print_run(command: str) -> None:
    """Print a command to run in its own block, so it cannot be skimmed past."""
    console.print(f"\n  Run:\n\n      [bold cyan]{command}[/bold cyan]\n")


@paf.command("push-key")
def paf_push_key() -> None:
    """Hand CHAT_FLOW's integration key to the backend tier and restart it.

    The Spring backend calls the published flow with PAF_AGENT_ID and
    PAF_API_KEY, and neither exists until the flow is published — long after
    the tier built itself. They arrive as a systemd drop-in over the shipped
    unit, so `api-key` is followed by this rather than by a rebuild.
    """
    _ensure_env()
    for key in ("PAF_AGENT_ID", "PAF_API_KEY"):
        if not os.getenv(key):
            console.print(
                f"[red]{key} is not set.[/red] Publish CHAT_FLOW, then run "
                "[cyan]python manage.py paf api-key[/cyan]."
            )
            sys.exit(1)

    script = f"""set -e
sudo install -d -m 0755 /etc/systemd/system/paf-poc-backend.service.d
sudo tee /etc/systemd/system/paf-poc-backend.service.d/paf-key.conf > /dev/null <<'UNIT'
[Service]
EnvironmentFile=/etc/paf-poc-backend.env
UNIT
sudo tee /etc/paf-poc-backend.env > /dev/null <<'ENVF'
PAF_AGENT_ID={os.environ['PAF_AGENT_ID']}
PAF_API_KEY={os.environ['PAF_API_KEY']}
ENVF
sudo chmod 0600 /etc/paf-poc-backend.env
sudo systemctl daemon-reload
sudo systemctl restart paf-poc-backend
sleep 4
systemctl is-active paf-poc-backend
"""
    console.print(f"Handing the key to [cyan]{_backend_host()}[/cyan] through the bastion")
    result = _backend_ssh(script)
    out = ((result.stderr or "") + (result.stdout or "")).strip()
    if "not found" in out:
        console.print(
            "[red]The backend tier is still building.[/red] Its service unit does not "
            "exist yet — wait for [cyan]/var/lib/paf-poc/bootstrap.ok[/cyan] on the "
            "backend, then re-run."
        )
        sys.exit(1)
    if result.returncode != 0 or "active" not in (result.stdout or ""):
        console.print(f"[red]Could not hand over the key.[/red]\n{out[:400]}")
        sys.exit(1)

    console.print(f"[green]\u2713[/green] Backend restarted with agent {os.environ['PAF_AGENT_ID']}")
    console.print("[dim]  The customer chat UI reaches CHAT_FLOW from here on.[/dim]")


@paf.command("bootstrap")
def paf_bootstrap() -> None:
    """Print the PAF UI installer URL and the connection details to paste into it."""
    _ensure_env()
    console.print(Panel.fit("[bold]PAF UI Installer[/bold]"))

    lb_ip = _tf_output("lb_ip")
    # Terraform reports this relative to its own module directory, which is not
    # a path anyone can paste into a file picker.
    wallet_rel = _tf_output("adb_wallet_path") or "./generated/adb-wallet.zip"
    wallet = (TF_DIR / wallet_rel).resolve()
    compartment = os.getenv("OCI_COMPARTMENT_OCID", "")
    endpoint = os.getenv("GENAI_ENDPOINT", "")
    db_service = str(os.getenv("DB_SERVICE", "")).lower()
    admin_user = os.getenv("PAF_ADMIN_USER", "")

    console.print("This sheet walks the whole PAF install, browser steps and commands")
    console.print("alike, in order. It ends by handing you back to CLOUD.md §9.\n")

    if lb_ip:
        console.print(f"Open the installer:\n  [cyan]https://{lb_ip}/agentFactory/installation[/cyan]\n"
                      "  [dim](self-signed certificate — accept the browser warning)[/dim]\n")
    else:
        console.print(
            "[yellow]No Terraform output yet.[/yellow] Apply deploy/tf/app first, then re-run.\n"
            "  The installer is at [cyan]https://<lb_ip>/agentFactory/installation[/cyan]\n"
        )

    console.print("[bold]Step 1 — admin user[/bold]")
    console.print(f"  Username:  [cyan]{admin_user}[/cyan]")
    console.print("  Password:  same as PAF_ADMIN_PASS in .env")
    console.print("  [dim]setup stored these; trust-ca, link-flow and api-key sign in with them.[/dim]")
    console.print("  [dim]If you create the admin with different credentials, record them afterwards:[/dim]")
    _print_run("python manage.py paf admin")

    console.print("[bold]Step 2 — database configuration[/bold] (ADB wallet)")
    console.print("  Connection type:  [cyan]Wallet[/cyan]")
    console.print(f"  Wallet file:      drop [cyan]{wallet}[/cyan]")
    console.print(f"  Network alias:    [cyan]{db_service}[/cyan]   (from the wallet's tnsnames)")
    console.print("  Username:         [cyan]AGENT_FACTORY[/cyan]")
    console.print("  Password:         same as DB_PASSWORD in .env")
    console.print("  [bold]PAF then asks two more questions:[/bold]")
    console.print("    Air-gapped environment?            [cyan]No[/cyan]")
    console.print("    OCI certificates added to wallet?  [cyan]Yes[/cyan]   (an ADB wallet carries them,")
    console.print("        so the Knowledge Assistant installs)\n")

    console.print("[bold]Step 3 — installation[/bold]")
    console.print("  Click Install. PAF creates its metadata tables under AGENT_FACTORY.")
    console.print("  Sign in as the admin user for the remaining steps.\n")

    console.print("[bold]Step 4 — LLM configuration[/bold]   (LLM Management — no key material; the compute")
    console.print("  authenticates as an instance principal through its dynamic group)")
    console.print("  [bold]Generative model[/bold]   (Model type radio: [cyan]Generative model[/cyan])")
    console.print("    LLM provider:        [cyan]OCI Generative AI — instance principal[/cyan]")
    console.print("    Configuration name:  [cyan]gen-model[/cyan]   (generic — CHAT_FLOW references it)")
    console.print(f"    Model ID:            [cyan]{os.getenv('GENAI_MODEL', '')}[/cyan]")
    console.print(f"    Service endpoint:    [cyan]{endpoint}[/cyan]")
    console.print(f"    Compartment OCID:    [cyan]{compartment}[/cyan]")
    console.print("    Serving mode:        [cyan]On-demand[/cyan]")
    console.print("  [bold]Embedding model[/bold]   (Model type radio: [cyan]Embedding model[/cyan])")
    console.print("    LLM provider:        [cyan]OCI Generative AI — instance principal[/cyan]")
    console.print("    Configuration name:  [cyan]emb-model[/cyan]")
    console.print(f"    Model ID:            [cyan]{os.getenv('GENAI_EMBED_MODEL', '')}[/cyan]")
    console.print(f"    Service endpoint:    [cyan]{endpoint}[/cyan]")
    console.print(f"    Compartment OCID:    [cyan]{compartment}[/cyan]")
    console.print(
        f"    [dim]Emits {os.getenv('GENAI_EMBED_DIM', '')} dimensions, matching the VECTOR width "
        f"in the changelog.[/dim]"
    )
    console.print("  Run a test call on each. A failure here is almost always the dynamic group")
    console.print("  or policy: re-apply deploy/tf/iam with a tenancy-admin profile.\n")

    console.print("[bold]Step 5 — data sources[/bold]   (Data Sources)")
    console.print("  The connection entered in step 2 is PAF's own repository. Select AI and the")
    console.print("  flows read through registered data sources, which are separate — without the")
    console.print("  database registered here, Select AI's database list is empty.")
    console.print("  [bold]Database[/bold]   (Add new data source → Source type: Database)")
    console.print("    Name:             [cyan]Banking Application DB[/cyan]")
    console.print("    Description:      [cyan]Read-only REPORTING views[/cyan]   (mandatory field)")
    console.print("    Connection type:  [cyan]Wallet[/cyan]")
    console.print(f"    Wallet file:      [cyan]{wallet}[/cyan]")
    console.print(f"    Database alias:   [cyan]{db_service}[/cyan]")
    console.print("    User:             [cyan]AGENT_FACTORY[/cyan]   (holds the Select AI package grants)")
    console.print("    Password:         same as DB_PASSWORD in .env")
    console.print("  [bold]HTTP — company registry[/bold]   (Source type: Rest API → OpenAPI specification)")
    console.print("    The form asks for the spec file and nothing else: the name and description")
    console.print("    come from the document's `info` block ([cyan]Company Registry[/cyan]), and PAF calls")
    console.print("    the URL in its `servers` block, which the backend tier sets to its own VCN")
    console.print("    address. The registry answers on that private address only, so the command")
    console.print("    below fetches the spec through the bastion. Upload the file it writes.")
    _print_run("python manage.py paf openapi")

    console.print("[bold]Step 6 — trust the gateway[/bold]")
    console.print("  Registers the internal load balancer's certificate in PAF's trust store.")
    console.print("  [dim]Skip it and every MCP server fails its connection test with \"could not[/dim]")
    console.print("  [dim]connect\" — a TLS failure, not a reachability one.[/dim]")
    _print_run("python manage.py paf trust-ca")

    console.print("[bold]Step 7 — allow private addresses[/bold]")
    console.print("  The MCP servers sit on a private address (10.0.x.x), which PAF refuses")
    console.print("  by default.")
    console.print("  [dim]Skip it and the first registration is rejected outright.[/dim]")
    _print_run("python manage.py paf allow-internal-mcp")

    console.print("[bold]Step 8 — MCP servers[/bold]   (Admin → MCP Servers → Add MCP server)")
    console.print("  Four registrations, [cyan]Direct[/cyan] authentication (no auth — they are reachable")
    console.print("  only inside the VCN). The flow references them by these names, so they")
    console.print("  must match.")
    mcp_urls = _tf_output_json("mcp_server_urls") or {}
    for name, label in (("opa", "opa-mcp"), ("hitl", "hitl-mcp"),
                        ("banking", "banking-mcp"), ("application", "application-mcp")):
        url = mcp_urls.get(name, "(apply deploy/tf/app to learn the address)")
        console.print(f"    [cyan]{label:<16}[/cyan] {url}")
    console.print("  [dim]Each should report connected, and its tools surface inside the Agent node.[/dim]\n")

    console.print("[bold]Done here.[/bold] Continue at [cyan]CLOUD.md §9 — Load CHAT_FLOW[/cyan].")
    console.print(
        "\n[yellow]Note:[/yellow] API automation for these UI steps is intentionally out of "
        "scope (Playwright-style driving is fragile across PAF versions)."
    )


# ---------------------------------------------------------------- stubs

@cli.command("build")
def build() -> None:
    """Compile the UIs and backend, then stage every tier's payload."""
    _ensure_env()

    # Each tier's Ansible directory is what Terraform zips and publishes, so
    # every build output is staged into the role that installs it.
    frontend_files = ANSIBLE_ROOT / "frontend" / "roles" / "webstack" / "files"
    backend_files = ANSIBLE_ROOT / "backend" / "roles" / "appstack" / "files"
    ops_files = ANSIBLE_ROOT / "ops" / "roles" / "opstools" / "files"

    for ui, dest in (("customer-ui", "customer"), ("backoffice-ui", "backoffice")):
        src = PROJECT_ROOT / "src" / ui
        console.print(f"[cyan]Building {ui}[/cyan]")
        _run(["npm", "ci"], cwd=src)
        _run(["npm", "run", "build"], cwd=src)
        _stage(src / "dist", frontend_files / dest)

    console.print("[cyan]Building the application backend[/cyan]")
    backend_src = PROJECT_ROOT / "src" / "backend"
    _run(["./gradlew", "build", "-x", "test"], cwd=backend_src)
    jars = sorted((backend_src / "build" / "libs").glob("*.jar"))
    jars = [j for j in jars if not j.name.endswith("-plain.jar")]
    if not jars:
        console.print("[red]No runnable jar in src/backend/build/libs.[/red]")
        sys.exit(1)
    backend_files.mkdir(parents=True, exist_ok=True)
    shutil.copy2(jars[0], backend_files / "app.jar")

    _stage_sources()

    console.print(f"[green]✓[/green] Staged every tier payload under {ANSIBLE_ROOT}")
    console.print("\nNext: [cyan]python manage.py tf[/cyan]")


def _stage_sources() -> None:
    """Stage the payloads that are copied rather than compiled.

    These come straight from the repository, so `cloud up` repeats it: editing a
    changelog and applying without rebuilding would otherwise ship the copy
    staged by the last `build`, and the change would silently not run.
    """
    backend_files = ANSIBLE_ROOT / "backend" / "roles" / "appstack" / "files"
    ops_files = ANSIBLE_ROOT / "ops" / "roles" / "opstools" / "files"
    _stage(PROJECT_ROOT / "opa", backend_files / "opa")
    _stage(PROJECT_ROOT / "src" / "api" / "registry", backend_files / "registry")
    for wrapper in ("opa-mcp", "hitl-mcp", "banking-mcp", "application-mcp"):
        _stage(PROJECT_ROOT / "src" / "ai" / wrapper, backend_files / "mcp" / wrapper)
    _stage(PROJECT_ROOT / "database" / "liquibase", ops_files / "database" / "liquibase")
    # The bastion is the only host that can reach both PAF and the database, so
    # the end-to-end harness runs from there.
    _stage(PROJECT_ROOT / "tests", ops_files / "tests")


@cli.command("clean")
def clean() -> None:
    """Remove generated cloud artefacts once Terraform state is empty."""
    state = TF_DIR / "terraform.tfstate"
    if state.exists():
        try:
            resources = json.loads(state.read_text()).get("resources", [])
        except json.JSONDecodeError:
            resources = []
        if resources:
            console.print(
                f"[red]Terraform state still holds {len(resources)} resource(s).[/red] "
                "Run `terraform destroy` in deploy/tf/app first."
            )
            sys.exit(1)

    removed = []
    generated = TF_DIR / "generated"
    if generated.exists():
        shutil.rmtree(generated)
        removed.append(str(generated))
    for tfvars in (TF_VARS_FILE, TF_IAM_VARS_FILE):
        if tfvars.exists():
            tfvars.unlink()
            removed.append(str(tfvars))

    # Staged tier payloads are build output; `build` recreates them.
    for staged in ANSIBLE_ROOT.glob("*/roles/*/files/*"):
        if staged.name == ".gitkeep":
            continue
        shutil.rmtree(staged) if staged.is_dir() else staged.unlink()
        removed.append(str(staged))

    for path in removed:
        console.print(f"[dim]removed {path}[/dim]")
    console.print(f"[green]✓[/green] Cleaned {len(removed)} path(s)")


if __name__ == "__main__":
    cli()