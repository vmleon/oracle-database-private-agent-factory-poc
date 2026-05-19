#!/usr/bin/env python3
"""CLI for managing the Oracle PAF Decisioning Engine PoC."""

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import click
from dotenv import load_dotenv
from InquirerPy import inquirer
from rich.console import Console
from rich.panel import Panel

console = Console()

PROJECT_ROOT = Path(__file__).parent
ENV_FILE = PROJECT_ROOT / ".env"
PODMAN_COMPOSE = PROJECT_ROOT / "deploy" / "podman" / "compose.local.yml"
ANSIBLE_DIR = PROJECT_ROOT / "deploy" / "ansible" / "database-setup"
ANSIBLE_VARS_FILE = ANSIBLE_DIR / ".vars.local.yml"

PAF_KIT_DIR = PROJECT_ROOT / "paf-kit"
PAF_VERSION_FILE = PAF_KIT_DIR / "applied-ai" / "kit" / "agent_factory" / "internal" / "version.json"
PAF_BUILD_SCRIPT = PAF_KIT_DIR / "build-image.sh"
PAF_IMAGE_REPO = "localhost/applied-ai-label"

LOCAL_PREREQS = {
    "podman": "Install: https://podman.io/docs/installation",
    "podman-compose": "Install: `brew install podman-compose` (macOS) or `pip install podman-compose` (OL8). Required by `podman compose`.",
    "ansible-playbook": "Install: `brew install ansible` (macOS) or `dnf install ansible-core` (OL8)",
    "liquibase": "Install: `brew install liquibase` (macOS) or download from https://www.liquibase.org/download",
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
        console.print("[red].env not found.[/red] Run `python manage.py setup local` first.")
        sys.exit(1)
    load_dotenv(ENV_FILE)


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


def _wait_for_db(container: str = "paf-oracle-free-26ai", timeout: int = 900) -> None:
    """Wait until FREEPDB1 is READ WRITE and max_string_size=EXTENDED.

    The startup hook runs a SHUTDOWN/STARTUP/utl32k dance after the initial
    'DATABASE IS READY TO USE!'. We poll the SQL state directly rather than
    checkDBStatus.sh — the image's healthcheck also gates on PDB$SEED's
    open_mode, which transitions through MOUNTED during the dance.
    """
    sql = (
        "SET HEAD OFF FEEDBACK OFF PAGES 0 ECHO OFF\n"
        "SELECT value || '|' || open_mode FROM v$parameter, v$pdbs\n"
        " WHERE v$parameter.name='max_string_size' AND v$pdbs.name='FREEPDB1';\n"
        "EXIT;\n"
    )
    deadline = time.time() + timeout
    last_state = None
    while time.time() < deadline:
        check = subprocess.run(
            ["podman", "exec", "-i", container, "sqlplus", "-s", "-L", "/", "as", "sysdba"],
            input=sql, capture_output=True, text=True,
        )
        output = check.stdout.strip().replace(" ", "") if check.returncode == 0 else ""
        if output == "EXTENDED|READWRITE":
            console.print("[green]✓[/green] max_string_size=EXTENDED, FREEPDB1=READ WRITE. Ready.")
            return
        state = output or "starting"
        if state != last_state:
            console.print(f"[dim]Waiting for Oracle DB ({state})...[/dim]")
            last_state = state
        time.sleep(5)
    console.print(
        f"[red]Timed out after {timeout}s waiting for Oracle DB.[/red] "
        "See `manage.py local logs oracle-free-26ai`."
    )
    sys.exit(1)


def _check_max_string_size(container: str = "paf-oracle-free-26ai") -> None:
    sql = (
        "SET HEAD OFF FEEDBACK OFF PAGES 0 ECHO OFF\n"
        "SELECT value FROM v$parameter WHERE name='max_string_size';\n"
        "EXIT;\n"
    )
    result = subprocess.run(
        ["podman", "exec", "-i", container, "sqlplus", "-s", "-L", "/", "as", "sysdba"],
        input=sql,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Failed to query max_string_size:[/red]\n{result.stderr}")
        sys.exit(1)
    value = result.stdout.strip()
    if value != "EXTENDED":
        console.print(
            f"[red]max_string_size is '{value}', expected 'EXTENDED'.[/red] "
            "PAF requires EXTENDED (per PAF §5.1)."
        )
        console.print(
            "[yellow]The first-boot init hook only runs on a fresh volume. "
            "Run [cyan]python manage.py local down --purge && python manage.py local up[/cyan] "
            "to re-init the DB.[/yellow]"
        )
        sys.exit(1)
    console.print("[green]✓[/green] max_string_size is EXTENDED.")


def _paf_app_version() -> str | None:
    """Read PAF_APP_VERSION from .env, or fall back to the kit's version.json."""
    val = os.getenv("PAF_APP_VERSION")
    if val:
        return val
    if PAF_VERSION_FILE.exists():
        try:
            return json.loads(PAF_VERSION_FILE.read_text())["app_version"]
        except (json.JSONDecodeError, KeyError):
            return None
    return None


def _paf_image_tag() -> str | None:
    v = _paf_app_version()
    return f"{PAF_IMAGE_REPO}:{v}" if v else None


def _paf_image_present(tag: str) -> bool:
    return subprocess.run(
        ["podman", "image", "exists", tag], capture_output=True
    ).returncode == 0


def _compute_ollama_hosts_entry() -> str | None:
    """Resolve OLLAMA_HOST on the host (which can do mDNS) and return the
    `hostname:ip` string for compose's extra_hosts. Returns None when the
    host already resolves inside the container (IP literal, localhost,
    host.containers.internal) or can't be resolved.
    """
    host = os.getenv("OLLAMA_HOST", "").strip()
    if not host or host in ("localhost", "127.0.0.1", "host.containers.internal"):
        return None
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return None
    try:
        import socket
        ip = socket.gethostbyname(host)
        return f"{host}:{ip}"
    except OSError:
        console.print(
            f"[yellow]Could not resolve {host} on this host.[/yellow] "
            "PAF will not be able to reach Ollama by name; "
            "paste the IP into the PAF UI instead."
        )
        return None


def _grant_sysdba_only_privs(container: str = "paf-oracle-free-26ai") -> None:
    """Grant SYS-owned privileges Liquibase can't grant as SYSTEM. PAF's
    `testInstallationDatabaseConnection` reads V$PARAMETER to detect the
    DB compatibility level — without SELECT on SYS.V_$PARAMETER it returns
    HTTP 400 with `ORA-00942 SYS.V_$PARAMETER does not exist`.

    SYSTEM also needs TABLE RETENTION to create blockchain/immutable tables
    with retention longer than the default 16 days (ORA-05807 otherwise);
    APP.decision uses NO DROP UNTIL 2555 DAYS IDLE (~7 years).

    Re-granting is a no-op, so this is safe to run every `local up`.
    """
    sql = (
        "ALTER SESSION SET CONTAINER=FREEPDB1;\n"
        "GRANT SELECT ON SYS.V_$PARAMETER TO AGENT_FACTORY;\n"
        "GRANT TABLE RETENTION TO SYSTEM;\n"
        "EXIT;\n"
    )
    result = subprocess.run(
        ["podman", "exec", "-i", container, "sqlplus", "-s", "-L", "/", "as", "sysdba"],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode != 0 or "ORA-" in result.stdout:
        console.print(f"[red]sysdba grant failed:[/red]\n{result.stdout}\n{result.stderr}")
        sys.exit(1)
    console.print("[green]✓[/green] SYS-only grants applied to AGENT_FACTORY.")


def _paf_post_start(container: str = "paf-agent-factory") -> None:
    """Reproduce the post-start steps the kit's `deploy.sh` performs:

    1. Start crond inside the container.
    2. Drop `/mount/.config_complete.marker` so `startup.sh` stops polling and
       proceeds with the install (without this PAF crash-loops every ~120 s).
    3. Seed `/mount/data/app/latest/version/version.json` from the kit's
       `internal/version.json` — `db_migrate.py` reads this during the UI
       installer and fails the install otherwise.
    All steps are idempotent.
    """
    deadline = time.time() + 60
    while time.time() < deadline:
        check = subprocess.run(
            ["podman", "inspect", container], capture_output=True
        )
        if check.returncode == 0:
            break
        time.sleep(2)
    else:
        console.print(f"[red]PAF container '{container}' never appeared.[/red]")
        sys.exit(1)

    subprocess.run(["podman", "exec", container, "crond", "start"], check=False)

    marker = PAF_KIT_DIR / "applied-ai" / "volume" / ".config_complete.marker"
    if marker.exists():
        console.print("[dim]PAF config marker already present.[/dim]")
    else:
        marker.touch()
        console.print("[green]✓[/green] PAF config marker written.")

    subprocess.run(
        ["podman", "exec", container, "sh", "-c",
         "mkdir -p /mount/data/app/latest/version && "
         "cp -f /home/aaiuser/install/agent_factory/internal/version.json "
         "/mount/data/app/latest/version/version.json"],
        check=False,
    )
    console.print("[green]✓[/green] PAF version.json seeded into /mount/data/app/latest/version/.")


def _write_env_key(key: str, value: str) -> None:
    """Update or append KEY=value in .env, preserving everything else."""
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


def _provision_local() -> None:
    load_dotenv(ENV_FILE)
    _check_max_string_size()
    vars_content = (
        "---\n"
        f"project_root: \"{PROJECT_ROOT}\"\n"
        f"db_host: \"{os.getenv('DB_HOST')}\"\n"
        f"db_port: \"{os.getenv('DB_PORT')}\"\n"
        f"db_service: \"{os.getenv('DB_SERVICE')}\"\n"
        f"db_admin_user: \"{os.getenv('DB_ADMIN_USER')}\"\n"
        f"db_admin_password: \"{os.getenv('DB_PASSWORD')}\"\n"
        f"db_password: \"{os.getenv('DB_PASSWORD')}\"\n"
    )
    ANSIBLE_VARS_FILE.write_text(vars_content)
    ANSIBLE_VARS_FILE.chmod(0o600)
    _run([
        "ansible-playbook",
        "-i", str(ANSIBLE_DIR / "inventory.local.yml"),
        str(ANSIBLE_DIR / "playbook.yml"),
        "-e", f"@{ANSIBLE_VARS_FILE}",
    ])


@click.group()
def cli() -> None:
    """Oracle PAF Decisioning Engine PoC."""


# ---------------------------------------------------------------- setup

@cli.group()
def setup() -> None:
    """Configure environment for local or cloud deployment."""


@setup.command("local")
def setup_local() -> None:
    """Interactive local-deployment configuration."""
    console.print(Panel.fit("[bold]Oracle PAF PoC — Local Setup[/bold]"))
    _check_prereqs(LOCAL_PREREQS)

    existing = {}
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
        existing = dict(os.environ)

    db_password = inquirer.secret(
        message="Oracle DB password (leave blank to auto-generate):",
        default="",
    ).execute()
    if not db_password:
        db_password = _generate_password()
        console.print(f"[green]✓[/green] Generated DB password (saved to .env)")

    ollama_host = inquirer.text(
        message="Ollama host:",
        default=existing.get("OLLAMA_HOST", "host.containers.internal"),
    ).execute()
    ollama_port = inquirer.text(
        message="Ollama port:",
        default=existing.get("OLLAMA_PORT", "11434"),
    ).execute()
    ollama_llm = inquirer.text(
        message="Ollama LLM model:",
        default="llama3.3:70b-instruct-q4_K_M",
    ).execute()
    ollama_embed = inquirer.text(
        message="Ollama embedding model:",
        default="bge-m3",
    ).execute()
    ollama_embed_dim = inquirer.text(
        message="Embedding dimension:",
        default="1024",
    ).execute()
    ocr_host = inquirer.text(
        message="OCR host:",
        default=existing.get("OCR_HOST", "127.0.0.1"),
    ).execute()
    ocr_port = inquirer.text(
        message="OCR port:",
        default=existing.get("OCR_PORT", "8500"),
    ).execute()

    env_content = (
        "# Generated by manage.py setup local — do not edit by hand\n"
        "DEPLOYMENT_TARGET=local\n"
        "\n"
        "# Database (Oracle Database Free 26ai in podman)\n"
        "DB_MODE=local-free-26ai\n"
        "DB_HOST=localhost\n"
        "DB_PORT=1521\n"
        "DB_SERVICE=FREEPDB1\n"
        "DB_ADMIN_USER=SYSTEM\n"
        f"DB_PASSWORD={db_password}\n"
        "\n"
        "# Models (Ollama)\n"
        f"OLLAMA_HOST={ollama_host}\n"
        f"OLLAMA_PORT={ollama_port}\n"
        f"OLLAMA_LLM_MODEL={ollama_llm}\n"
        f"OLLAMA_EMBED_MODEL={ollama_embed}\n"
        f"OLLAMA_EMBED_DIM={ollama_embed_dim}\n"
        "\n"
        "# OCR\n"
        f"OCR_HOST={ocr_host}\n"
        f"OCR_PORT={ocr_port}\n"
    )
    ENV_FILE.write_text(env_content)
    ENV_FILE.chmod(0o600)
    console.print(f"[green]✓[/green] Wrote {ENV_FILE}")
    console.print("\nNext: [cyan]python manage.py local up[/cyan]")


@setup.command("cloud")
def setup_cloud() -> None:
    """Interactive cloud-deployment configuration (not yet implemented)."""
    console.print("[yellow]setup cloud[/yellow] is not yet implemented (planned for a later PR).")
    sys.exit(2)


# ---------------------------------------------------------------- local

@cli.group()
def local() -> None:
    """Local podman lifecycle."""


@local.command("up")
def local_up() -> None:
    """Bring the local stack up and provision the database."""
    _ensure_env()
    paf_tag = _paf_image_tag()
    paf_ready = bool(paf_tag) and PAF_KIT_DIR.exists()
    if paf_ready and not _paf_image_present(paf_tag):
        console.print(f"[bold]PAF image {paf_tag} missing — building from kit...[/bold]")
        _run(["bash", str(PAF_BUILD_SCRIPT), "aai"], cwd=str(PAF_KIT_DIR))
    services = ["oracle-free-26ai"]
    # Always export so compose substitution succeeds even when paf isn't started.
    os.environ["PAF_APP_VERSION"] = _paf_app_version() or "unset"
    os.environ.setdefault("HOST_OS", platform.system())
    hosts_entry = _compute_ollama_hosts_entry()
    if hosts_entry:
        os.environ["OLLAMA_HOSTS_ENTRY"] = hosts_entry
        console.print(f"[dim]Injecting extra_hosts: {hosts_entry}[/dim]")
    if paf_ready:
        services.append("paf")
    console.print("[bold]Starting podman containers...[/bold]")
    _run([
        "podman", "compose", "-f", str(PODMAN_COMPOSE),
        "up", "-d", *services,
    ])
    console.print("[bold]Waiting for Oracle DB to be healthy (up to 5 min)...[/bold]")
    _wait_for_db()
    console.print("[bold]Provisioning database (Ansible → Liquibase)...[/bold]")
    _provision_local()
    console.print("[bold]Applying SYS-only grants...[/bold]")
    _grant_sysdba_only_privs()
    if paf_ready:
        console.print("[bold]Configuring PAF container (post-start handshake)...[/bold]")
        _paf_post_start()
    if not paf_ready:
        console.print(
            "\n[yellow]PAF not started.[/yellow] "
            "Run [cyan]python manage.py paf prepare <path-to-tar>[/cyan] "
            "and re-run [cyan]local up[/cyan]."
        )
    console.print("\n[green]✓ Local stack up.[/green] Run [cyan]python manage.py info[/cyan].")


@local.command("down")
@click.option("--purge", is_flag=True, help="Remove volumes as well.")
def local_down(purge: bool) -> None:
    """Stop and remove the local stack."""
    args = ["podman", "compose", "-f", str(PODMAN_COMPOSE), "down"]
    if purge:
        args.append("-v")
    _run(args)


@local.command("logs")
@click.argument("service", required=False)
def local_logs(service: str | None) -> None:
    """Stream logs for one service, or all if omitted."""
    args = ["podman", "compose", "-f", str(PODMAN_COMPOSE), "logs", "-f"]
    if service:
        args.append(service)
    _run(args)


@local.command("provision")
def local_provision() -> None:
    """Apply Liquibase + grants against the local DB (idempotent)."""
    _ensure_env()
    _provision_local()
    _grant_sysdba_only_privs()


# ---------------------------------------------------------------- info

@cli.command("info")
def info() -> None:
    """Print URLs and connection strings."""
    _ensure_env()
    target = os.getenv("DEPLOYMENT_TARGET", "unknown")
    console.print(Panel.fit(f"[bold]Deployment: {target}[/bold]"))
    if target == "local":
        console.print(
            f"Oracle DB JDBC: jdbc:oracle:thin:@{os.getenv('DB_HOST')}:"
            f"{os.getenv('DB_PORT')}/{os.getenv('DB_SERVICE')}"
        )
        console.print(f"Admin user:     {os.getenv('DB_ADMIN_USER')}")
        console.print(f"App schemas:    APP, REPORTING, AGENT_TOOLS, AGENT_FACTORY")
        console.print(f"Ollama:         http://{os.getenv('OLLAMA_HOST')}:{os.getenv('OLLAMA_PORT')}")
        console.print(f"OCR:            http://{os.getenv('OCR_HOST')}:{os.getenv('OCR_PORT')}")
        paf_version = _paf_app_version()
        if paf_version:
            console.print(f"PAF installer:  https://localhost:8080/agentFactory/installation")
            console.print(f"PAF version:    {paf_version}")
        else:
            console.print(f"PAF:            [yellow]not prepared[/yellow] "
                          f"(run `manage.py paf prepare <tar>`)")


# ---------------------------------------------------------------- paf

@cli.group()
def paf() -> None:
    """Private Agent Factory operations."""


@paf.command("prepare")
@click.argument("tarball", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def paf_prepare(tarball: Path) -> None:
    """Extract the PAF kit tarball into ./paf-kit/ and record its version in .env."""
    if PAF_KIT_DIR.exists():
        console.print(f"[yellow]Removing existing {PAF_KIT_DIR}...[/yellow]")
        shutil.rmtree(PAF_KIT_DIR)
    PAF_KIT_DIR.mkdir()
    console.print(f"[bold]Extracting {tarball.name} → {PAF_KIT_DIR}...[/bold]")
    with tarfile.open(tarball, "r:gz") as tf:
        # Filter is required from Python 3.14; harmless on earlier versions.
        try:
            tf.extractall(PAF_KIT_DIR, filter="tar")
        except TypeError:
            tf.extractall(PAF_KIT_DIR)
    if not PAF_VERSION_FILE.exists():
        console.print(
            f"[red]Extracted kit is missing {PAF_VERSION_FILE.relative_to(PROJECT_ROOT)}.[/red] "
            "Is this the right tarball?"
        )
        sys.exit(1)
    # The tar ships ./applied-ai/volume but not ./applied-ai/dev-shared;
    # the compose mounts both, so create the missing one as an empty dir.
    (PAF_KIT_DIR / "applied-ai" / "dev-shared").mkdir(exist_ok=True)
    version = json.loads(PAF_VERSION_FILE.read_text())["app_version"]
    _write_env_key("PAF_APP_VERSION", version)
    console.print(f"[green]✓[/green] PAF kit extracted. PAF_APP_VERSION={version}")
    console.print("Next: [cyan]python manage.py paf build[/cyan] (or just [cyan]local up[/cyan])")


@paf.command("build")
def paf_build() -> None:
    """Build the PAF container image from the extracted kit (idempotent)."""
    if not PAF_BUILD_SCRIPT.exists():
        console.print("[red]paf-kit/ not found.[/red] Run `manage.py paf prepare <tar>` first.")
        sys.exit(1)
    _ensure_env()
    tag = _paf_image_tag()
    if not tag:
        console.print("[red]PAF_APP_VERSION not set.[/red] Re-run `manage.py paf prepare`.")
        sys.exit(1)
    if _paf_image_present(tag):
        console.print(f"[green]✓[/green] {tag} already built.")
        return
    console.print(f"[bold]Building {tag} (this can take 10+ min)...[/bold]")
    _run(["bash", str(PAF_BUILD_SCRIPT), "aai"], cwd=str(PAF_KIT_DIR))


def _resolve_ollama_host() -> tuple[str, str | None]:
    """Return (host-to-paste, advisory). If .env's OLLAMA_HOST is a `.local`
    mDNS name, resolve it to an IPv4 and return that — containers can't do
    mDNS, so pasting the .local hostname into the PAF form leads to
    `ConnectError: Name or service not known`.
    """
    host = os.getenv("OLLAMA_HOST", "")
    if not host.endswith(".local"):
        return host, None
    try:
        import socket
        ip = socket.gethostbyname(host)
        return ip, (
            f".local hostname `{host}` won't resolve inside the PAF container; "
            f"using its IPv4 ({ip}) instead."
        )
    except OSError:
        return host, (
            f".local hostname `{host}` cannot be resolved from this machine. "
            "Find its LAN IP manually and paste that."
        )


@paf.command("bootstrap")
def paf_bootstrap() -> None:
    """Print the PAF UI installer URL and the connection details to paste into it."""
    _ensure_env()
    console.print(Panel.fit("[bold]PAF UI Installer[/bold]"))
    console.print(
        "Open the installer in a browser and accept the self-signed certificate:\n"
        "  [cyan]https://localhost:8080/agentFactory/installation[/cyan]\n"
    )
    console.print("[bold]Step 1 — admin user[/bold]")
    console.print("  Create an admin user (username + password — record them yourself).\n")

    console.print("[bold]Step 2 — database configuration[/bold]")
    console.print(f"  Connection type:  [cyan]Basic[/cyan]")
    console.print(f"  Protocol:         [cyan]TCP[/cyan]")
    console.print(f"  Host:             [cyan]oracle-free-26ai[/cyan]   (compose service DNS)")
    console.print(f"  Port:             [cyan]1521[/cyan]")
    console.print(f"  Service name:     [cyan]{os.getenv('DB_SERVICE')}[/cyan]")
    console.print(f"  Username:         [cyan]AGENT_FACTORY[/cyan]")
    console.print(f"  Password:         same as DB_PASSWORD in .env")
    console.print(f"  Air-gapped?       [cyan]No[/cyan]   (DB has outbound NAT via podman)")
    console.print(f"  Uses a wallet?    [cyan]No[/cyan]   (TCP listener, not ADB mTLS)\n")

    console.print("[bold]Step 3 — installation[/bold]")
    console.print("  Click Install. PAF creates its metadata tables under AGENT_FACTORY")
    console.print("  and a read-only user AAI_RO_AGENT_FACTORY.\n")

    ollama_host, advisory = _resolve_ollama_host()
    console.print("[bold]Step 4 — LLM configuration[/bold]")
    if advisory:
        console.print(f"  [yellow]Note:[/yellow] {advisory}")
    console.print(f"  [bold]Generative model[/bold]")
    console.print(f"    Provider:       [cyan]Ollama[/cyan]")
    console.print(f"    Configuration:  [cyan]ollama-llm[/cyan]   (any name; this is just a label)")
    console.print(f"    Model ID:       [cyan]{os.getenv('OLLAMA_LLM_MODEL')}[/cyan]")
    console.print(f"    URL:            [cyan]{ollama_host}[/cyan]")
    console.print(f"    Port:           [cyan]{os.getenv('OLLAMA_PORT')}[/cyan]")
    console.print(f"  [bold]Embedding model[/bold]")
    console.print(f"    Provider:       [cyan]Ollama[/cyan]")
    console.print(f"    Configuration:  [cyan]ollama-embedding[/cyan]")
    console.print(f"    Model ID:       [cyan]{os.getenv('OLLAMA_EMBED_MODEL')}[/cyan]")
    console.print(f"    URL:            [cyan]{ollama_host}[/cyan]")
    console.print(f"    Port:           [cyan]{os.getenv('OLLAMA_PORT')}[/cyan]\n")

    console.print("[bold]After install[/bold] — sign in as the admin user and:")
    console.print("  - Verify LLM Management shows both configurations.")
    console.print("  - Agent Builder → build a trivial Chat→Prompt→LLM→Chat flow to smoke-test.")
    console.print(
        "\n[yellow]Note:[/yellow] API automation for these UI steps is intentionally out of "
        "scope (Playwright-style driving is fragile across PAF versions)."
    )


# ---------------------------------------------------------------- stubs

@cli.command("build")
def build() -> None:
    """Build artefacts (not yet implemented)."""
    console.print("[yellow]build[/yellow] is not yet implemented (planned for a later PR).")
    sys.exit(2)


@cli.command("tf")
def tf() -> None:
    """Render Terraform tfvars (not yet implemented)."""
    console.print("[yellow]tf[/yellow] is not yet implemented (planned for a later PR).")
    sys.exit(2)


@cli.command("clean")
def clean() -> None:
    """Cloud teardown safeguard (not yet implemented)."""
    console.print("[yellow]clean[/yellow] is not yet implemented (planned for a later PR).")
    sys.exit(2)


if __name__ == "__main__":
    cli()
