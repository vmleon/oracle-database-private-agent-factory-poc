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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import click
import requests
import urllib3
from dotenv import load_dotenv
from InquirerPy import inquirer
from jinja2 import StrictUndefined, Template
from rich.console import Console
from rich.panel import Panel

console = Console()

# PAF terminates TLS with a self-signed certificate on the local instance.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_ROOT = Path(__file__).parent
ENV_FILE = PROJECT_ROOT / ".env"
PODMAN_COMPOSE = PROJECT_ROOT / "deploy" / "podman" / "compose.local.yml"
# Recreates application-backend with its current environment substitution
# (container env is fixed at creation, so `podman restart` alone would keep
# stale/empty PAF_AGENT_ID / PAF_API_KEY).
RECREATE_BACKEND_CMD = [
    "podman", "compose", "-f", str(PODMAN_COMPOSE),
    "up", "-d", "--force-recreate", "--no-deps", "application-backend",
]
ANSIBLE_DIR = PROJECT_ROOT / "deploy" / "ansible" / "database-setup"
ANSIBLE_VARS_FILE = ANSIBLE_DIR / ".vars.local.yml"

ANSIBLE_ROOT = PROJECT_ROOT / "deploy" / "ansible"

TF_DIR = PROJECT_ROOT / "deploy" / "tf" / "app"
TF_VARS_TEMPLATE = TF_DIR / "terraform.tfvars.j2"
TF_VARS_FILE = TF_DIR / "terraform.tfvars"

TF_IAM_DIR = PROJECT_ROOT / "deploy" / "tf" / "iam"
TF_IAM_VARS_TEMPLATE = TF_IAM_DIR / "terraform.tfvars.j2"
TF_IAM_VARS_FILE = TF_IAM_DIR / "terraform.tfvars"

KIT_DIST_DIR = PROJECT_ROOT / "paf" / "dist"
PAF_KIT_DIR = PROJECT_ROOT / "paf-kit"
PAF_VERSION_FILE = PAF_KIT_DIR / "applied-ai" / "kit" / "agent_factory" / "internal" / "version.json"
PAF_BUILD_SCRIPT = PAF_KIT_DIR / "build-image.sh"
PAF_IMAGE_REPO = "localhost/applied-ai-label"
PAF_BASE_URL = "https://localhost:8080"

# TCPS (encrypted SQL*Net) for the PAF → Oracle connection. The Free image's
# /opt/oracle/configTcps.sh generates a self-signed server cert (CN = the host
# PAF dials) plus a ready client wallet; we export that wallet for the PAF
# install wizard's "Wallet" connection type. TCP/1521 stays up alongside, so
# Liquibase / grants / sqlcl keep working unchanged.
DB_HOST_DNS = "oracle-free-26ai"          # compose service DNS = the cert CN
TCPS_PORT = "2484"
TCPS_CLIENT_WALLET = "/opt/oracle/oradata/clientWallet/FREE"   # in the container
TCPS_WALLET_DIR = PROJECT_ROOT / "tcps-wallet"                 # exported to host
TCPS_WALLET_ZIP = PROJECT_ROOT / "tcps-wallet.zip"            # upload into PAF

# TLS gateway for the MCP servers. A Caddy proxy (mcp-proxy) terminates TLS and
# forwards to each plain-HTTP MCP app. PAF trusts the self-signed certificate
# through its administrator certificate store — see `paf trust-ca`.
MCP_TLS_DIR = PROJECT_ROOT / "mcp-tls"
MCP_PROXY_HOST = "mcp-proxy"
MCP_PROXY_PORT = "8443"
# path-prefix -> internal MCP app, used both by Caddyfile.mcp and the URL hints.
MCP_ROUTES = {
    "banking": "banking-mcp:8503",
    "opa": "opa-mcp:8500",
    "hitl": "hitl-mcp:8502",
    "application": "application-mcp:8504",
}

# Snapshot of the kit-shipped initial state of `applied-ai/{volume,dev-shared}`,
# captured at `paf prepare` time. `local down --purge` restores from this so
# runtime accretions (admin user records, .config_complete.marker, /mount/data)
# are wiped while kit-shipped seed content is preserved.
PAF_PURGE_TEMPLATE_DIR = PAF_KIT_DIR / ".purge-template"
PAF_BIND_MOUNTS = ("volume", "dev-shared")

LOCAL_PREREQS = {
    "podman": "Install: https://podman.io/docs/installation",
    "podman-compose": "Install: `brew install podman-compose` (macOS) or `pip install podman-compose` (OL8). Required by `podman compose`.",
    "ansible-playbook": "Install: `brew install ansible` (macOS) or `dnf install ansible-core` (OL8)",
    "liquibase": "Install: `brew install liquibase` (macOS) or download from https://www.liquibase.org/download",
}

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
        console.print("[red].env not found.[/red] Run `python manage.py setup local` first.")
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


def _host_kit_arch() -> str:
    """Kit architecture matching the machine running podman locally."""
    return "ARM64" if platform.machine().lower() in ("arm64", "aarch64") else "X86_64"


def _resolve_kit_tarball(arch: str) -> str:
    """Path to the kit tarball in paf/dist/ built for `arch`.

    The kit ships one tarball per architecture and the two deployment targets
    do not share one, so each target resolves the file matching what it runs.
    """
    candidates = sorted(KIT_DIST_DIR.glob("*.tar.gz"))
    for candidate in candidates:
        if arch.lower() in candidate.name.lower():
            return str(candidate)

    console.print(
        f"[red]No {arch} PAF kit tarball in {KIT_DIST_DIR}.[/red]\n"
        f"Download it from Oracle Software Delivery and place it there "
        f"(e.g. oracle_agent_factory_{arch}_26.7.0.tar.gz) — see paf/dist/README.md."
    )
    if candidates:
        console.print("[dim]Present, but not for this architecture:[/dim]")
        for candidate in candidates:
            console.print(f"[dim]  • {candidate.name}[/dim]")
    sys.exit(1)


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


def _compute_vllm_hosts_entry() -> str | None:
    """Resolve VLLM_HOST on the host (which can do mDNS) and return the
    `hostname:ip` string for compose's extra_hosts. Returns None when the
    host already resolves inside the container (IP literal, localhost,
    host.containers.internal) or can't be resolved.
    """
    host = os.getenv("VLLM_HOST", "").strip()
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
            "PAF will not be able to reach the vLLM endpoint by name; "
            "paste the IP into the PAF UI instead."
        )
        return None


def _run_sysdba_sql(sql: str, label: str, container: str = "paf-oracle-free-26ai") -> None:
    result = subprocess.run(
        ["podman", "exec", "-i", container, "sqlplus", "-s", "-L", "/", "as", "sysdba"],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode != 0 or "ORA-" in result.stdout:
        console.print(f"[red]{label} failed:[/red]\n{result.stdout}\n{result.stderr}")
        sys.exit(1)


def _grant_sysdba_pre_liquibase(container: str = "paf-oracle-free-26ai") -> None:
    """Grants that must be in place BEFORE Liquibase runs.

    SYSTEM needs TABLE RETENTION to create blockchain/immutable tables with
    retention longer than the default 16 days (ORA-05807 otherwise);
    APP.decision uses NO DROP UNTIL 2555 DAYS IDLE (~7 years), so without
    this grant the `CREATE BLOCKCHAIN TABLE` changeset fails. Re-granting
    is a no-op, so this is safe to run every `local up`.
    """
    sql = (
        "ALTER SESSION SET CONTAINER=FREEPDB1;\n"
        "GRANT TABLE RETENTION TO SYSTEM;\n"
        "EXIT;\n"
    )
    _run_sysdba_sql(sql, "Pre-Liquibase sysdba grant", container)
    console.print("[green]✓[/green] TABLE RETENTION granted to SYSTEM (pre-Liquibase).")


def _grant_sysdba_post_liquibase(container: str = "paf-oracle-free-26ai") -> None:
    """Grants that depend on users created by Liquibase.

    PAF's `testInstallationDatabaseConnection` reads V$PARAMETER to detect
    the DB compatibility level — without SELECT on SYS.V_$PARAMETER it
    returns HTTP 400 with `ORA-00942 SYS.V_$PARAMETER does not exist`.
    AGENT_FACTORY is created by `001-users-and-grants.yaml`, so this grant
    must run after Liquibase. Re-granting is a no-op.

    Also grants EXECUTE on DBMS_CLOUD / DBMS_CLOUD_AI to AGENT_FACTORY
    (the packages are installed by `_install_dbms_cloud` earlier).

    Also creates the read-only worker user AAI_RO_AGENT_FACTORY. PAF
    requires this user to pre-exist before the install wizard's DB step;
    without it the DB step fails with "Required read-only user
    AAI_RO_AGENT_FACTORY does not exist". It needs only CREATE SESSION and
    a password equal to the runtime user's (AGENT_FACTORY = DB_PASSWORD);
    PAF grants the read-only SELECTs itself.

    Note: Select AI is not wired locally, so no outbound-HTTPS network ACL
    is added here. Wiring Select AI locally would also need an ACL to the
    HTTPS endpoint fronting vLLM — see the note in `_bootstrap_select_ai_profiles`.
    """
    db_password = os.getenv("DB_PASSWORD", "")
    sql_lines = [
        "SET DEFINE OFF",
        "ALTER SESSION SET CONTAINER=FREEPDB1;",
        "GRANT SELECT ON SYS.V_$PARAMETER TO AGENT_FACTORY;",
        "GRANT EXECUTE ON DBMS_CLOUD TO AGENT_FACTORY;",
        "GRANT EXECUTE ON DBMS_CLOUD_AI TO AGENT_FACTORY;",
        "DECLARE n NUMBER; BEGIN",
        "  SELECT COUNT(*) INTO n FROM dba_users WHERE username = 'AAI_RO_AGENT_FACTORY';",
        f"  IF n = 0 THEN EXECUTE IMMEDIATE 'CREATE USER AAI_RO_AGENT_FACTORY IDENTIFIED BY \"{db_password}\"';",
        f"  ELSE EXECUTE IMMEDIATE 'ALTER USER AAI_RO_AGENT_FACTORY IDENTIFIED BY \"{db_password}\"'; END IF;",
        "  EXECUTE IMMEDIATE 'GRANT CREATE SESSION TO AAI_RO_AGENT_FACTORY';",
        "END;",
        "/",
        "EXIT;",
    ]
    sql = "\n".join(sql_lines) + "\n"
    _run_sysdba_sql(sql, "Post-Liquibase sysdba grant", container)
    console.print("[green]✓[/green] SYS-only grants applied to AGENT_FACTORY; AAI_RO_AGENT_FACTORY ensured.")


def _tcps_configured(container: str = "paf-oracle-free-26ai") -> bool:
    """True if the Free image's TCPS client wallet already exists in the DB."""
    return subprocess.run(
        ["podman", "exec", container, "bash", "-lc",
         f"test -f {TCPS_CLIENT_WALLET}/cwallet.sso"],
        capture_output=True,
    ).returncode == 0


def _export_tcps_wallet(container: str = "paf-oracle-free-26ai") -> None:
    """Copy the in-container client wallet to the host and zip it for the PAF
    install wizard's Wallet upload. The wallet carries tnsnames aliases (FREE /
    FREEPDB1) pointing at oracle-free-26ai:2484 plus the trusted server cert."""
    if TCPS_WALLET_DIR.exists():
        shutil.rmtree(TCPS_WALLET_DIR)
    TCPS_WALLET_DIR.mkdir()
    _run(["podman", "cp", f"{container}:{TCPS_CLIENT_WALLET}/.", str(TCPS_WALLET_DIR)])
    if TCPS_WALLET_ZIP.exists():
        TCPS_WALLET_ZIP.unlink()
    shutil.make_archive(str(TCPS_WALLET_ZIP.with_suffix("")), "zip", TCPS_WALLET_DIR)
    # Both are an auto-login (SSO) wallet = a private-key store. Keep them
    # owner-only and out of git (.gitignore) — never commit a wallet.
    TCPS_WALLET_DIR.chmod(0o700)
    TCPS_WALLET_ZIP.chmod(0o600)


def _configure_tcps(container: str = "paf-oracle-free-26ai") -> None:
    """Enable TCPS on the Oracle Free listener and export a client wallet.

    Idempotent: the server-side config (self-signed cert, listener endpoint on
    2484, sqlnet/listener edits) is generated once by `configTcps.sh` and lives
    in the persistent oradata volume. Re-running would mint a *new* cert and
    invalidate a wallet PAF already holds, so we skip the regen when the client
    wallet is already present — but always refresh the host-side export.
    """
    if _tcps_configured(container):
        console.print("[dim]TCPS already configured in the DB; reusing existing wallet.[/dim]")
    else:
        console.print(f"[bold]Configuring TCPS (port {TCPS_PORT}, cert CN={DB_HOST_DNS})...[/bold]")
        # Positional args: <tcps_port> <hostname-for-cert-CN-and-tnsnames>.
        _run(["podman", "exec", container, "bash", "-lc",
              f"/opt/oracle/configTcps.sh {TCPS_PORT} {DB_HOST_DNS}"])
    _export_tcps_wallet(container)
    console.print(
        f"[green]✓[/green] TCPS ready on {DB_HOST_DNS}:{TCPS_PORT}; "
        f"wallet → [cyan]{TCPS_WALLET_ZIP.name}[/cyan] (upload it in the PAF wizard)."
    )


def _configure_mcp_tls() -> None:
    """Generate the self-signed certificate for the MCP TLS gateway (mcp-proxy).

    Idempotent: the certificate is generated once and reused — regenerating it
    would invalidate the copy PAF already trusts. Runs before `podman compose up`
    because the files are bind-mounted into mcp-proxy at container start.
    """
    crt = MCP_TLS_DIR / "mcp-proxy.crt"
    key = MCP_TLS_DIR / "mcp-proxy.key"
    MCP_TLS_DIR.mkdir(exist_ok=True)

    if crt.exists() and key.exists():
        console.print("[dim]MCP TLS cert already present; reusing.[/dim]")
    else:
        console.print(f"[bold]Generating self-signed MCP TLS cert (SAN={MCP_PROXY_HOST})...[/bold]")
        cfg = MCP_TLS_DIR / "openssl.cnf"
        cfg.write_text(
            "[req]\n"
            "distinguished_name = dn\n"
            "x509_extensions = v3_req\n"
            "prompt = no\n"
            "[dn]\n"
            f"CN = {MCP_PROXY_HOST}\n"
            "[v3_req]\n"
            "basicConstraints = critical, CA:false\n"
            "keyUsage = critical, digitalSignature, keyEncipherment\n"
            "extendedKeyUsage = serverAuth\n"
            "subjectAltName = @alt\n"
            "[alt]\n"
            f"DNS.1 = {MCP_PROXY_HOST}\n"
            "DNS.2 = localhost\n"
        )
        _run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(crt),
            "-days", "825", "-config", str(cfg),
        ])
        cfg.unlink()

    key.chmod(0o600)
    console.print(
        f"[green]✓[/green] MCP TLS ready: gateway [cyan]{MCP_PROXY_HOST}:{MCP_PROXY_PORT}[/cyan]. "
        f"Register the CA with [cyan]python manage.py paf trust-ca[/cyan]."
    )


def _is_dbms_cloud_installed(container: str = "paf-oracle-free-26ai") -> bool:
    """Detect whether DBMS_CLOUD has been installed in the PDB."""
    sql = (
        "SET HEAD OFF FEEDBACK OFF PAGES 0 ECHO OFF\n"
        "ALTER SESSION SET CONTAINER=FREEPDB1;\n"
        "SELECT COUNT(*) FROM dba_objects "
        "  WHERE owner='C##CLOUD$SERVICE' AND object_name='DBMS_CLOUD';\n"
        "EXIT;\n"
    )
    result = subprocess.run(
        ["podman", "exec", "-i", container, "sqlplus", "-s", "-L", "/", "as", "sysdba"],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line) > 0
    return False


def _install_dbms_cloud(container: str = "paf-oracle-free-26ai") -> None:
    """Install DBMS_CLOUD family of packages (incl. DBMS_CLOUD_AI / Select AI).

    Oracle Database Free 26ai ships the install scripts in
    `$ORACLE_HOME/rdbms/admin/` but does not pre-install the packages. We
    run `catclouduser.sql` (creates the `C##CLOUD$SERVICE` common user)
    then `dbms_cloud_install.sql` (installs the packages + public
    synonyms) via `catcon.pl` across CDB$ROOT and every PDB.

    First run takes ~5 minutes. Idempotent: skipped if DBMS_CLOUD is
    already present in `C##CLOUD$SERVICE`. Uses `$ORACLE_PWD` from inside
    the container so the SYS password never crosses the podman boundary.
    """
    if _is_dbms_cloud_installed(container):
        console.print("[green]✓[/green] DBMS_CLOUD already installed.")
        return
    console.print("[bold]Installing DBMS_CLOUD packages (one-time, ~5 min)...[/bold]")
    for script in ("catclouduser.sql", "dbms_cloud_install.sql"):
        console.print(f"[dim]Running {script}...[/dim]")
        bash_cmd = (
            "$ORACLE_HOME/perl/bin/perl $ORACLE_HOME/rdbms/admin/catcon.pl "
            "-u SYS/$ORACLE_PWD "
            "--force_pdb_mode 'READ WRITE' "
            f"-b dbms_cloud_install_{script.replace('.sql', '')} "
            "-d $ORACLE_HOME/rdbms/admin/ "
            "-l /tmp "
            f"{script}"
        )
        result = subprocess.run(
            ["podman", "exec", container, "bash", "-c", bash_cmd]
        )
        if result.returncode != 0:
            console.print(f"[red]{script} failed (exit {result.returncode}).[/red]")
            console.print(
                "[yellow]Check the install log at /tmp inside the container:[/yellow]\n"
                "  podman exec paf-oracle-free-26ai ls -lt /tmp | head"
            )
            sys.exit(1)
    console.print("[green]✓[/green] DBMS_CLOUD packages installed.")


def _drop_select_ai_artefacts(container: str = "paf-oracle-free-26ai") -> None:
    """Drop any leftover Select AI credential + profiles under AGENT_FACTORY.

    Called when local skips profile creation (DBMS_CLOUD_AI constraint —
    see `_bootstrap_select_ai_profiles`). Keeps the DB tidy: no half-wired
    artefacts to confuse demo viewers. Errors are ignored — the artefacts
    may not exist on a fresh install. Both `VLLM_CRED` and `OLLAMA_CRED`
    aliases are dropped so any prior state under either name is removed.
    """
    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        return
    sql = (
        "BEGIN BEGIN DBMS_CLOUD_AI.DROP_PROFILE('chat_profile'); "
        "EXCEPTION WHEN OTHERS THEN NULL; END; END;\n/\n"
        "BEGIN BEGIN DBMS_CLOUD_AI.DROP_PROFILE('research_profile'); "
        "EXCEPTION WHEN OTHERS THEN NULL; END; END;\n/\n"
        "BEGIN BEGIN DBMS_CLOUD.DROP_CREDENTIAL('VLLM_CRED'); "
        "EXCEPTION WHEN OTHERS THEN NULL; END; END;\n/\n"
        "BEGIN BEGIN DBMS_CLOUD.DROP_CREDENTIAL('OLLAMA_CRED'); "
        "EXCEPTION WHEN OTHERS THEN NULL; END; END;\n/\n"
        "EXIT;\n"
    )
    subprocess.run(
        ["podman", "exec", "-i", container, "sqlplus", "-s", "-L",
         f"AGENT_FACTORY/{db_password}@localhost:1521/FREEPDB1"],
        input=sql, capture_output=True, text=True,
    )


def _bootstrap_select_ai_profiles(container: str = "paf-oracle-free-26ai") -> None:
    """Create / replace `chat_profile` and `research_profile` under AGENT_FACTORY.

    Both profiles share the same vLLM generation backend (model from .env).
    Each pins its own NL2SQL object list to a `REPORTING.*` view set:
      - chat_profile    → REPORTING.chat_v_*    (customer-safe)
      - research_profile → REPORTING.research_v_* (broader read-only)

    Uses the `openai` provider with a `provider_endpoint` pointed at an
    HTTPS endpoint in front of vLLM (`VLLM_HOST:VLLM_GEN_PORT`).

    NOTE: DBMS_CLOUD requires an HTTPS callout in front of vLLM (see LOCAL
    CONSTRAINT below for why this isn't wired locally). Wiring Select AI
    locally requires TLS termination in front of vLLM, its CA added to the
    Oracle wallet, and a network ACL granted to it.

    A `credential_name` is mandatory on every DBMS_CLOUD_AI profile;
    vLLM doesn't enforce auth by default, so we create a dummy `VLLM_CRED`
    with placeholder username/password.

    Idempotent: credential and profiles are dropped (ignore-if-missing)
    and recreated, so .env changes propagate cleanly.

    LOCAL CONSTRAINT (`DEPLOYMENT_TARGET=local`): Oracle Database Free
    26ai (23.26.x) rejects `provider: ollama` / `provider: openai-compatible`
    (ORA-20046) and rejects HTTP `provider_endpoint` values (ORA-20047).
    Even via HTTPS, `provider: openai` then fails pre-flight with ORA-20401 —
    the on-prem build appears to allow-list the OpenAI hostname and reject
    custom endpoints at validation time, before the request leaves the DB.
    See the operational note in `docs/DEPLOYMENT.md`. The function therefore
    drops any leftover credential / profiles on local and skips creation.
    Select AI is the cloud/ADB path — `DEPLOYMENT_TARGET=cloud` runs the
    full body.
    """
    deployment_target = (os.getenv("DEPLOYMENT_TARGET") or "").strip().lower()
    if deployment_target == "local":
        _drop_select_ai_artefacts(container)
        console.print(
            "[yellow]Select AI profile bootstrap skipped on local.[/yellow] "
            "Oracle Free 26ai's DBMS_CLOUD_AI rejects custom provider_endpoint "
            "values pre-flight (ORA-20401). The CHAT_FLOW flow uses a generic "
            "SQL Query node + LLM locally; full Select AI is the ADB path. "
            "See docs/DEPLOYMENT.md §7."
        )
        return

    db_password = os.getenv("DB_PASSWORD")
    vllm_host = os.getenv("VLLM_HOST")
    vllm_model = os.getenv("VLLM_GEN_MODEL")
    if not all([db_password, vllm_host, vllm_model]):
        console.print(
            "[yellow]Skipping Select AI profile bootstrap — "
            "DB_PASSWORD / VLLM_HOST / VLLM_GEN_MODEL missing in .env.[/yellow]"
        )
        return

    vllm_gen_port = os.getenv("VLLM_GEN_PORT", "8000")
    # Cloud/ADB path: an HTTPS endpoint must front vLLM for the DB callout
    # (see NOTE in the docstring). Override via VLLM_TLS_ENDPOINT if a
    # dedicated TLS terminator is used.
    provider_endpoint = os.getenv(
        "VLLM_TLS_ENDPOINT", f"https://{vllm_host}:{vllm_gen_port}/v1"
    )
    credential_name = "VLLM_CRED"

    chat_views = [
        "chat_v_applicant_profile",
        "chat_v_transactions_summary",
        "chat_v_credit_bureau",
        "chat_v_existing_facilities",
        "chat_v_loan_application",
        "chat_v_application_document",
    ]
    research_views = [
        "research_v_full_transactions",
        "research_v_decision_history",
        "research_v_decision_audit",
        "research_v_research_audit",
        "research_v_policy_parameter_history",
        "research_v_hitl_task",
    ]

    def _object_list_json(views: list[str]) -> str:
        return ", ".join(
            f'{{"owner": "REPORTING", "name": "{v}"}}' for v in views
        )

    def _profile_block(profile: str, views: list[str]) -> str:
        attrs = (
            "{"
            '"provider": "openai", '
            f'"credential_name": "{credential_name}", '
            f'"provider_endpoint": "{provider_endpoint}", '
            f'"model": "{vllm_model}", '
            '"temperature": "0", '
            '"conversation": "true", '
            f'"object_list": [{_object_list_json(views)}]'
            "}"
        )
        return (
            "BEGIN\n"
            "  BEGIN\n"
            f"    DBMS_CLOUD_AI.DROP_PROFILE(profile_name => '{profile}');\n"
            "  EXCEPTION WHEN OTHERS THEN NULL;\n"
            "  END;\n"
            "  DBMS_CLOUD_AI.CREATE_PROFILE(\n"
            f"    profile_name => '{profile}',\n"
            f"    attributes   => q'!{attrs}!'\n"
            "  );\n"
            "END;\n"
            "/\n"
        )

    sql = (
        "WHENEVER SQLERROR EXIT SQL.SQLCODE\n"
        # (Re)create the placeholder credential — vLLM doesn't enforce auth
        # by default, but DBMS_CLOUD_AI requires `credential_name` to be set
        # on the profile.
        "BEGIN\n"
        "  BEGIN\n"
        f"    DBMS_CLOUD.DROP_CREDENTIAL(credential_name => '{credential_name}');\n"
        "  EXCEPTION WHEN OTHERS THEN NULL;\n"
        "  END;\n"
        "  DBMS_CLOUD.CREATE_CREDENTIAL(\n"
        f"    credential_name => '{credential_name}',\n"
        "    username        => 'vllm',\n"
        "    password        => 'none'\n"
        "  );\n"
        "END;\n"
        "/\n"
        + _profile_block("chat_profile", chat_views)
        + _profile_block("research_profile", research_views)
        + "EXIT;\n"
    )

    result = subprocess.run(
        ["podman", "exec", "-i", container, "sqlplus", "-s", "-L",
         f"AGENT_FACTORY/{db_password}@localhost:1521/FREEPDB1"],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode != 0 or "ORA-" in result.stdout:
        console.print(
            f"[red]Select AI profile bootstrap failed:[/red]\n"
            f"{result.stdout}\n{result.stderr}"
        )
        sys.exit(1)
    console.print(
        f"[green]✓[/green] Select AI credential [cyan]{credential_name}[/cyan] + profiles "
        "[cyan]chat_profile[/cyan], [cyan]research_profile[/cyan] created "
        f"({provider_endpoint})."
    )


def _snapshot_paf_bind_mounts() -> None:
    """Capture the kit-shipped initial state of `applied-ai/{volume,dev-shared}`
    into a sidecar template directory. Called once at `paf prepare` time,
    immediately after the tar is extracted. `local down --purge` restores
    from this snapshot.

    The kit ships seed content (config templates, startup scripts) in
    `applied-ai/volume` that PAF's startup.sh expects to find on first boot.
    Wiping the bind mount empty would crash PAF; resetting to this snapshot
    keeps the kit's seed while clearing every runtime accretion.
    """
    if PAF_PURGE_TEMPLATE_DIR.exists():
        shutil.rmtree(PAF_PURGE_TEMPLATE_DIR)
    PAF_PURGE_TEMPLATE_DIR.mkdir()
    for sub in PAF_BIND_MOUNTS:
        src = PAF_KIT_DIR / "applied-ai" / sub
        if src.exists():
            shutil.copytree(src, PAF_PURGE_TEMPLATE_DIR / sub)
    console.print(
        f"[green]✓[/green] Snapshotted kit bind-mount state into "
        f"{PAF_PURGE_TEMPLATE_DIR.relative_to(PROJECT_ROOT)}/."
    )


def _reset_paf_bind_mount_state() -> None:
    """Reset PAF's bind-mounted directories to the kit-shipped initial state
    captured at `paf prepare` time.

    The Oracle data volume is a named podman volume and gets wiped by
    `compose down -v`. PAF's installed-state markers (admin user records,
    `.config_complete.marker`, `/mount/data/...` contents) live in
    `paf-kit/applied-ai/{volume,dev-shared}` — host bind mounts that
    compose can't reach. Without this cleanup, `down --purge` followed by
    `local up` lands the user on PAF's login screen instead of the
    installer wizard, because PAF reads the marker + persisted config and
    skips re-installation.

    The kit binaries under `paf-kit/applied-ai/kit/` are NOT touched —
    no re-extract of the tar is needed.
    """
    if not PAF_PURGE_TEMPLATE_DIR.exists():
        console.print(
            "[yellow]No purge template found.[/yellow] "
            "Re-run [cyan]python manage.py paf prepare <tar>[/cyan] to capture "
            "the kit's initial state, then `local down --purge` will work."
        )
        return
    for sub in PAF_BIND_MOUNTS:
        path = PAF_KIT_DIR / "applied-ai" / sub
        if path.exists():
            shutil.rmtree(path)
        template = PAF_PURGE_TEMPLATE_DIR / sub
        if template.exists():
            shutil.copytree(template, path)
        else:
            path.mkdir(parents=True, exist_ok=True)
        console.print(
            f"[green]✓[/green] Reset {path.relative_to(PROJECT_ROOT)} to kit defaults."
        )


def _wait_for_container(container: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if subprocess.run(["podman", "inspect", container], capture_output=True).returncode == 0:
            return True
        time.sleep(2)
    return False


def _paf_bind_mounts_visible(container: str) -> bool:
    """Return True if PAF's `/mount` bind from the host is populated.

    On podman+macOS (applehv + virtiofs), multiple bind mounts from
    related host paths can collapse onto a single empty virtiofs share.
    When that happens `/mount` looks empty inside the container even
    though `paf-kit/applied-ai/volume/` on the host has the kit-seeded
    config — nginx then can't load its config and PAF serves an
    error-page SPA. We probe for the `config/app` subtree because the
    kit ships it and `startup.sh` populates more under it; if that
    isn't there, the mount is broken.
    """
    probe = subprocess.run(
        ["podman", "exec", container, "test", "-d", "/mount/config/app"],
        capture_output=True,
    )
    return probe.returncode == 0


def _paf_post_start(container: str = "paf-agent-factory") -> None:
    """Reproduce the post-start steps the kit's `deploy.sh` performs:

    1. Verify the `/mount` bind from the host is actually populated;
       if not, recreate the container once to work around the podman
       virtiofs collapse.
    2. Start crond inside the container.
    3. Drop `/mount/.config_complete.marker` so `startup.sh` stops polling and
       proceeds with the install (without this PAF crash-loops every ~120 s).
    4. Seed `/mount/data/app/latest/version/version.json` from the kit's
       `internal/version.json` — `db_migrate.py` reads this during the UI
       installer and fails the install otherwise.
    All steps are idempotent.
    """
    if not _wait_for_container(container):
        console.print(f"[red]PAF container '{container}' never appeared.[/red]")
        sys.exit(1)

    if not _paf_bind_mounts_visible(container):
        console.print(
            "[yellow]PAF bind mount is empty inside the container "
            "(podman virtiofs share collapsed). Recreating the container...[/yellow]"
        )
        subprocess.run(["podman", "stop", container], check=False)
        subprocess.run(["podman", "rm", container], check=False)
        _run([
            "podman", "compose", "-f", str(PODMAN_COMPOSE),
            "up", "-d", "paf",
        ])
        if not _wait_for_container(container):
            console.print(f"[red]PAF container '{container}' did not come back after recreate.[/red]")
            sys.exit(1)
        if not _paf_bind_mounts_visible(container):
            console.print(
                "[red]PAF bind mount still empty after recreate. "
                "Try `podman machine stop && podman machine start` "
                "and re-run `local up`.[/red]"
            )
            sys.exit(1)
        console.print("[green]✓[/green] PAF bind mount restored after container recreate.")

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


def _paf_session() -> requests.Session:
    """Administrator-authenticated session against the local PAF instance."""
    load_dotenv(ENV_FILE)
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
            f"{PAF_BASE_URL}/agentFactory/v1/loginValidation",
            auth=(user, password),
            headers={"Origin": PAF_BASE_URL},
            timeout=30,
        )
    except requests.RequestException as exc:
        console.print(f"[red]Cannot reach PAF at {PAF_BASE_URL}:[/red] {exc}")
        sys.exit(1)
    if r.status_code != 200:
        console.print(
            f"[red]PAF login failed: HTTP {r.status_code}.[/red] "
            f"Check PAF_ADMIN_USER / PAF_ADMIN_PASS in .env.\n{r.text[:300]}"
        )
        sys.exit(1)
    return session


def _discover_chat_flow_id(session: requests.Session) -> str:
    """Resolve CHAT_FLOW's agent id by name."""
    r = session.get(f"{PAF_BASE_URL}/agentFactory/v1/agents", timeout=30)
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

    vllm_host = inquirer.text(
        message="vLLM host (e.g. gpu-host.local or its IPv4):",
        default=existing.get("VLLM_HOST", ""),
    ).execute()
    vllm_gen_port = inquirer.text(
        message="vLLM generation port:",
        default=existing.get("VLLM_GEN_PORT", "8000"),
    ).execute()
    vllm_embed_port = inquirer.text(
        message="vLLM embedding port:",
        default=existing.get("VLLM_EMBED_PORT", "8001"),
    ).execute()
    vllm_gen_model = inquirer.text(
        message="vLLM generation model (HuggingFace handle):",
        default=existing.get("VLLM_GEN_MODEL", "Qwen/Qwen2.5-72B-Instruct-AWQ"),
    ).execute()
    vllm_embed_model = inquirer.text(
        message="vLLM embedding model (HuggingFace handle):",
        default=existing.get("VLLM_EMBED_MODEL", "BAAI/bge-m3"),
    ).execute()
    vllm_embed_dim = inquirer.text(
        message="Embedding dimension:",
        default=existing.get("VLLM_EMBED_DIM", "1024"),
    ).execute()
    paf_tarball = _resolve_kit_tarball(_host_kit_arch())
    console.print(f"[green]✓[/green] PAF kit: {Path(paf_tarball).name}")

    # PAF admin creds — used by manage.py's own `paf trust-ca` and `paf
    # api-key` commands to authenticate against PAF as an administrator.
    # Manual install-wizard input, no auto-generation; leave blank to keep
    # whatever's already in .env on a re-run.
    paf_admin_user = inquirer.text(
        message="PAF admin username (the one entered in the install wizard, leave blank to keep existing):",
        default=existing.get("PAF_ADMIN_USER", ""),
    ).execute()
    paf_admin_pass = inquirer.secret(
        message="PAF admin password (leave blank to keep existing):",
        default="",
    ).execute()
    if not paf_admin_pass:
        paf_admin_pass = existing.get("PAF_ADMIN_PASS", "")

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
        "# Models (vLLM — OpenAI-compatible endpoints on the GPU host)\n"
        f"VLLM_HOST={vllm_host}\n"
        f"VLLM_GEN_PORT={vllm_gen_port}\n"
        f"VLLM_EMBED_PORT={vllm_embed_port}\n"
        f"VLLM_GEN_MODEL={vllm_gen_model}\n"
        f"VLLM_EMBED_MODEL={vllm_embed_model}\n"
        f"VLLM_EMBED_DIM={vllm_embed_dim}\n"
        "\n"
        "# PAF kit tarball (read by `manage.py paf prepare` when no path is given)\n"
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
    console.print("\nNext: [cyan]python manage.py paf prepare[/cyan]")


@setup.command("cloud")
def setup_cloud() -> None:
    """Interactive cloud-deployment configuration."""
    console.print(Panel.fit("[bold]Oracle PAF PoC — Cloud Setup (OCI)[/bold]"))
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

    region = inquirer.select(
        message="Workload region (VCN, computes, ADB):",
        choices=regions,
        default=existing.get("OCI_REGION", _oci_profile_region(oci_profile) or regions[0]),
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

    console.print("[dim]Listing compartments…[/dim]")
    compartments = _oci_json(
        ["iam", "compartment", "list", "--compartment-id", tenancy_ocid,
         "--compartment-id-in-subtree", "true", "--all"],
        oci_profile,
    ) or []
    active = sorted(
        ((c["name"], c["id"]) for c in compartments if c.get("lifecycle-state") == "ACTIVE"),
        key=lambda pair: pair[0],
    )
    if active:
        compartment_ocid = inquirer.select(
            message="Compartment:",
            choices=[{"name": name, "value": ocid} for name, ocid in active],
            default=existing.get("OCI_COMPARTMENT_OCID"),
        ).execute()
    else:
        compartment_ocid = inquirer.text(
            message="Compartment OCID:",
            default=existing.get("OCI_COMPARTMENT_OCID", ""),
        ).execute()

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

    paf_tarball = _resolve_kit_tarball("X86_64")
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
        "# Generated by manage.py setup cloud — do not edit by hand\n"
        "DEPLOYMENT_TARGET=cloud\n"
        "\n"
        "# OCI targeting\n"
        f"OCI_PROFILE={oci_profile}\n"
        f"OCI_TENANCY_OCID={tenancy_ocid}\n"
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
        "# PAF kit tarball (read by `manage.py paf prepare` when no path is given)\n"
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
    console.print("\nNext: [cyan]python manage.py tf[/cyan]")


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

    genai_model = inquirer.select(
        message="Generation model:",
        choices=chat_models,
        default=existing.get("GENAI_MODEL") if existing.get("GENAI_MODEL") in chat_models else None,
    ).execute()

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
    """Profile names declared in ~/.oci/config."""
    config = Path.home() / ".oci" / "config"
    if not config.exists():
        return []
    return re.findall(r"^\[([^\]]+)\]", config.read_text(), flags=re.MULTILINE)


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
    if os.environ.get("DEPLOYMENT_TARGET") != "cloud":
        console.print("[red].env targets local.[/red] Run `python manage.py setup cloud` first.")
        sys.exit(1)

    roots = {
        TF_VARS_TEMPLATE: (TF_VARS_FILE, [
            "OCI_PROFILE", "OCI_REGION", "OCI_GENAI_REGION", "OCI_COMPARTMENT_OCID",
            "OCI_LABEL", "OCI_SSH_PUBLIC_KEY", "OCI_ADMIN_CIDR", "OCI_COMPUTE_SHAPE",
            "DB_NAME", "DB_PASSWORD", "DB_WALLET_PASSWORD", "PAF_TARBALL", "GENAI_MODEL",
        ]),
        TF_IAM_VARS_TEMPLATE: (TF_IAM_VARS_FILE, [
            "OCI_PROFILE", "OCI_REGION", "OCI_TENANCY_OCID", "OCI_COMPARTMENT_OCID", "OCI_LABEL",
        ]),
    }

    for template_path, (out_path, keys) in roots.items():
        missing = [k for k in keys if not os.environ.get(k)]
        if missing:
            console.print(f"[red]Missing in .env:[/red] {', '.join(missing)}")
            sys.exit(1)
        template = Template(template_path.read_text(), undefined=StrictUndefined)
        out_path.write_text(template.render({k: os.environ[k] for k in keys}) + "\n")
        out_path.chmod(0o600)
        console.print(f"[green]✓[/green] Wrote {out_path}")

    console.print(
        "\nThe IAM root creates the dynamic groups and policy, and needs tenancy-admin rights:\n"
        "  [cyan]cd deploy/tf/iam && terraform init && terraform apply[/cyan]\n"
        "Then the workload stack:\n"
        "  [cyan]cd deploy/tf/app && terraform init && terraform plan -out=tfplan && terraform apply tfplan[/cyan]"
    )


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
    services = ["oracle-free-26ai", "opa", "opa-mcp", "hitl-mcp", "application-mcp", "banking-mcp", "registry-api", "application-backend", "customer-ui", "backoffice-ui", "proxy", "mcp-proxy"]
    # The MCP TLS cert is bind-mounted into mcp-proxy, so it must exist before
    # compose starts that container.
    console.print("[bold]Preparing MCP TLS gateway cert...[/bold]")
    _configure_mcp_tls()
    # Always export so compose substitution succeeds even when paf isn't started.
    os.environ["PAF_APP_VERSION"] = _paf_app_version() or "unset"
    os.environ.setdefault("HOST_OS", platform.system())
    # PAF reaches vLLM directly; when VLLM_HOST is a `.local` mDNS name the
    # PAF container can't resolve it, so we resolve it on the host and inject
    # the mapping via the compose `extra_hosts` (`${VLLM_HOSTS_ENTRY}`).
    hosts_entry = _compute_vllm_hosts_entry()
    if hosts_entry:
        os.environ["VLLM_HOSTS_ENTRY"] = hosts_entry
        console.print(f"[dim]Injecting extra_hosts: {hosts_entry}[/dim]")
    if paf_ready:
        services.append("paf")
    console.print("[bold]Starting podman containers (rebuilds wrapper images when source changed)...[/bold]")
    # `--build` makes `up` layer-aware: unchanged wrappers come up fast
    # from cache; edited wrappers (src/ai/*-mcp, src/api/registry) get a
    # fresh image. `local down --purge && local up` wipes volumes but
    # leaves images alone, so without `--build` a wrapper edit would
    # silently re-run the previous build.
    _run([
        "podman", "compose", "-f", str(PODMAN_COMPOSE),
        "up", "-d", "--build", *services,
    ])
    console.print("[bold]Waiting for Oracle DB to be healthy (up to 5 min)...[/bold]")
    _wait_for_db()
    console.print("[bold]Applying pre-Liquibase sysdba grants...[/bold]")
    _grant_sysdba_pre_liquibase()
    console.print("[bold]Ensuring DBMS_CLOUD is installed...[/bold]")
    _install_dbms_cloud()
    console.print("[bold]Provisioning database (Ansible → Liquibase)...[/bold]")
    _provision_local()
    console.print("[bold]Applying post-Liquibase sysdba grants...[/bold]")
    _grant_sysdba_post_liquibase()
    console.print("[bold]Bootstrapping Select AI profiles...[/bold]")
    _bootstrap_select_ai_profiles()
    console.print("[bold]Configuring TCPS (encrypted SQL*Net) + exporting client wallet...[/bold]")
    _configure_tcps()
    if paf_ready:
        console.print("[bold]Configuring PAF container (post-start handshake)...[/bold]")
        _paf_post_start()
    # `up --build` rebuilds the application-backend image when src/backend
    # changed, but podman leaves the already-running container on the old
    # image — so code changes were silently ignored. Force-recreate just the
    # application-backend (DB is healthy by now) so it always lands on the
    # freshly built image.
    console.print("[bold]Recreating application-backend onto the latest image...[/bold]")
    _run(RECREATE_BACKEND_CMD)
    console.print("\n[green]✓ Local stack up.[/green]")
    if paf_ready:
        console.print(
            "Next: [cyan]python manage.py paf bootstrap[/cyan] "
            "to walk through the PAF UI installer."
        )
        console.print(
            "Anytime: [cyan]python manage.py info[/cyan] for URLs and connection details."
        )
    else:
        console.print(
            "[yellow]PAF not started.[/yellow] "
            "Next: [cyan]python manage.py paf prepare <path-to-tar>[/cyan] "
            "and re-run [cyan]local up[/cyan]."
        )
        console.print(
            "Anytime: [cyan]python manage.py info[/cyan] for DB connection details."
        )


@local.command("tcps")
def local_tcps() -> None:
    """(Re)configure TCPS on the Oracle listener and export the client wallet.

    Runs automatically as part of `local up`; use this to regenerate the wallet
    on demand (e.g. after a `local down --purge` if you skipped a full up)."""
    _ensure_env()
    _configure_tcps()


@local.command("mcp-tls")
def local_mcp_tls() -> None:
    """(Re)generate the MCP TLS gateway certificate.

    Runs automatically as part of `local up`. The certificate is reused if
    present — delete ./mcp-tls/ first to force a fresh one, then re-register it
    with `paf trust-ca` and restart the gateway.
    """
    _ensure_env()
    _configure_mcp_tls()
    console.print(
        "[dim]If the certificate changed, re-register it with "
        "[cyan]python manage.py paf trust-ca[/cyan] and restart the gateway: "
        "[cyan]podman restart paf-mcp-proxy[/cyan][/dim]"
    )


@local.command("down")
@click.option(
    "--purge", is_flag=True,
    help="Remove the Oracle data volume and empty PAF's bind-mount state.",
)
def local_down(purge: bool) -> None:
    """Stop and remove the local stack."""
    args = ["podman", "compose", "-f", str(PODMAN_COMPOSE), "down"]
    if purge:
        args.append("-v")
    _run(args)
    if purge:
        # `compose down -v` is supposed to remove the named oradata volume
        # but podman-compose on macOS sometimes leaves it behind — a fresh
        # `local up` then re-applies all 72 Liquibase changesets against an
        # already-populated DATABASECHANGELOG and the seed data is stale.
        # Force-remove so the next `local up` starts from an empty Oracle.
        subprocess.run(
            ["podman", "volume", "rm", "--force", "paf-oradata"],
            check=False,
            capture_output=True,
        )
        _reset_paf_bind_mount_state()


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
    """Apply Liquibase + grants + Select AI bootstrap against the local DB (idempotent)."""
    _ensure_env()
    _grant_sysdba_pre_liquibase()
    _install_dbms_cloud()
    _provision_local()
    _grant_sysdba_post_liquibase()
    _bootstrap_select_ai_profiles()


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
        console.print(f"vLLM (gen):     http://{os.getenv('VLLM_HOST')}:{os.getenv('VLLM_GEN_PORT')}/v1   model={os.getenv('VLLM_GEN_MODEL')}")
        console.print(f"vLLM (embed):   http://{os.getenv('VLLM_HOST')}:{os.getenv('VLLM_EMBED_PORT')}/v1   model={os.getenv('VLLM_EMBED_MODEL')}")
        console.print(f"OPA:            http://opa:8181 (compose-internal)")
        console.print(f"OPA MCP:        http://opa-mcp:8500/mcp/ (compose-internal — wire as PAF MCP server)")
        console.print(f"HITL MCP:       http://hitl-mcp:8502/mcp/ (compose-internal — wire as PAF MCP server; create_hitl_task side effect)")
        console.print(f"Registry API:   http://registry-api:8600/openapi.json (compose-internal — wire as PAF HTTP datasource)")
        console.print(f"Application API:http://localhost:8090 (application-backend — /v1/customers, /v1/login, /v1/chat)")
        console.print(f"Chat UI:        http://localhost:5173/ (customer-ui via Caddy front door; /v1 routed to backend)")
        console.print(f"Backoffice UI:  http://localhost:5173/backoffice (backoffice-ui via Caddy front door)")
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
@click.argument("tarball", required=False, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def paf_prepare(tarball: Path | None) -> None:
    """Extract the PAF kit tarball into ./paf-kit/ and record its version in .env.

    With no argument, reads the path from PAF_TARBALL in .env (set by `setup local`).
    """
    if tarball is None:
        if ENV_FILE.exists():
            load_dotenv(ENV_FILE)
        env_path = os.getenv("PAF_TARBALL", "").strip()
        if not env_path:
            console.print(
                "[red]No tarball given and PAF_TARBALL not set in .env.[/red] "
                "Pass a path or run `python manage.py setup local`."
            )
            sys.exit(1)
        tarball = Path(env_path).expanduser()
        if not tarball.is_file():
            console.print(f"[red]PAF_TARBALL points at a missing file:[/red] {tarball}")
            sys.exit(1)
        console.print(f"[dim]Using PAF_TARBALL from .env: {tarball}[/dim]")
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
    _snapshot_paf_bind_mounts()
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


def _resolve_vllm_host() -> tuple[str, str | None]:
    """Return (host-to-paste, advisory). If .env's VLLM_HOST is a `.local`
    mDNS name, resolve it to an IPv4 and return that — containers can't do
    mDNS, so pasting the .local hostname into the PAF form leads to
    `ConnectError: Name or service not known`.
    """
    host = os.getenv("VLLM_HOST", "")
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


@paf.command("allow-internal-mcp")
def paf_allow_internal_mcp() -> None:
    """Relax PAF's outbound-URL SSRF guard so the internal MCP gateway can be
    registered: sets BLOCK_PRIVATE_OUTBOUND_URLS=false in PAF's app settings.

    Required because mcp-proxy (and every MCP) resolves to a private podman IP,
    which PAF blocks by default — even over https. ALLOW_INSECURE_HTTP_URLS
    is left false: MCPs are served over https via mcp-proxy. Run once after the
    PAF install wizard completes; re-run after a `local down --purge` reinstall
    (the setting resets to the secure default on a fresh install).
    """
    _ensure_env()
    db_password = os.getenv("DB_PASSWORD", "")
    sql = (
        "SET DEFINE OFF\n"
        "UPDATE AGENT_FACTORY.AAI_APPLICATION_SETTINGS SET value='false' "
        "WHERE field='BLOCK_PRIVATE_OUTBOUND_URLS';\n"
        "COMMIT;\n"
        "SET PAGESIZE 0 FEEDBACK OFF\n"
        "SELECT field||'='||value FROM AGENT_FACTORY.AAI_APPLICATION_SETTINGS "
        "WHERE field IN ('BLOCK_PRIVATE_OUTBOUND_URLS','ALLOW_INSECURE_HTTP_URLS');\n"
        "EXIT;\n"
    )
    proc = subprocess.run(
        ["podman", "exec", "-i", "paf-oracle-free-26ai", "bash", "-lc",
         f'sqlplus -s SYSTEM/"{db_password}"@localhost:1521/FREEPDB1'],
        input=sql, capture_output=True, text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if "BLOCK_PRIVATE_OUTBOUND_URLS=false" not in out:
        console.print(
            "[red]Could not confirm the setting change.[/red] Is PAF installed yet "
            "(the settings table exists only after the install wizard)?\n" + out.strip()
        )
        sys.exit(1)
    console.print("[green]✓[/green] BLOCK_PRIVATE_OUTBOUND_URLS=false — internal MCP URLs allowed.")
    console.print("[dim]Register MCP servers as https://mcp-proxy:8443/<svc>/mcp/ (see LOCAL.md §4a).[/dim]")


@paf.command("trust-ca")
def paf_trust_ca() -> None:
    """Register the MCP gateway CA in PAF's administrator certificate store.

    PAF's outbound HTTP clients read this store when they dial MCP servers, so
    the https://mcp-proxy:8443 URLs verify. The store lives on PAF's mounted
    volume and survives image rebuilds. Run once per install, after the wizard.
    """
    _ensure_env()
    crt = MCP_TLS_DIR / "mcp-proxy.crt"
    if not crt.exists():
        console.print(
            f"[red]{crt} not found.[/red] Run `python manage.py local mcp-tls` first."
        )
        sys.exit(1)
    session = _paf_session()
    with crt.open("rb") as handle:
        r = session.post(
            f"{PAF_BASE_URL}/agentFactory/v1/certs",
            headers={"Origin": PAF_BASE_URL},
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
    r = session.get(f"{PAF_BASE_URL}/agentFactory/v1/tools/mcp/sources", timeout=30)
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

    r = session.get(f"{PAF_BASE_URL}/agentFactory/v1/agents/{agent_id}", timeout=30)
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
            "Register them per LOCAL.md §4a, then re-run."
        )
        sys.exit(1)

    if not changes:
        console.print("[green]✓[/green] Every MCP node already points at the right server.")
        return

    r = session.put(
        f"{PAF_BASE_URL}/agentFactory/v1/agents/{agent_id}/data",
        headers={"Origin": PAF_BASE_URL},
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
        f"{PAF_BASE_URL}/agentFactory/v1/integrations/agents/{agent_id}/keys",
        headers={"Origin": PAF_BASE_URL},
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
        "[dim]PAF_AGENT_ID and PAF_API_KEY written to .env. Recreate the backend "
        f"to pick them up: [cyan]{' '.join(RECREATE_BACKEND_CMD)}[/cyan][/dim]"
    )


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


@paf.command("bootstrap")
def paf_bootstrap() -> None:
    """Print the PAF UI installer URL and the connection details to paste into it."""
    _ensure_env()
    if (os.getenv("DEPLOYMENT_TARGET") or "").strip().lower() == "cloud":
        _paf_bootstrap_cloud()
    else:
        _paf_bootstrap_local()


def _paf_bootstrap_local() -> None:
    console.print(Panel.fit("[bold]PAF UI Installer[/bold]"))
    console.print(
        "Open the installer in a browser and accept the self-signed certificate:\n"
        "  [cyan]https://localhost:8080/agentFactory/installation[/cyan]\n"
    )
    console.print("[bold]Step 1 — admin user[/bold]")
    console.print("  Create an admin user (username + password — record them yourself).\n")

    wallet_ready = TCPS_WALLET_ZIP.exists()
    console.print("[bold]Step 2 — database configuration[/bold] (TCPS / encrypted)")
    console.print(f"  Connection type:  [cyan]Wallet[/cyan]")
    if wallet_ready:
        console.print(f"  Wallet file:      drop [cyan]{TCPS_WALLET_ZIP}[/cyan]")
    else:
        console.print(f"  Wallet file:      [yellow]missing[/yellow] — run "
                      f"[cyan]python manage.py local tcps[/cyan] to generate it")
    console.print(f"  Network alias:    [cyan]{str(os.getenv('DB_SERVICE')).lower()}[/cyan]"
                  f"   (from the wallet's tnsnames — selects TCPS {DB_HOST_DNS}:{TCPS_PORT})")
    console.print(f"  Username:         [cyan]AGENT_FACTORY[/cyan]")
    console.print(f"  Password:         same as DB_PASSWORD in .env")
    console.print(f"  [dim]The wallet carries the TCPS host/port + trusted self-signed cert,[/dim]")
    console.print(f"  [dim]so host/port/protocol are not entered by hand. TCP/1521 also still works[/dim]")
    console.print(f"  [dim]if PAF rejects the self-signed wallet: Basic / TCP / {DB_HOST_DNS} / 1521 / no wallet.[/dim]")
    console.print(f"  [bold]After the connection succeeds, PAF asks two more questions:[/bold]")
    console.print(f"    Air-gapped environment?            [cyan]No[/cyan]   (DB has outbound NAT via podman)")
    console.print(f"    OCI certificates added to wallet?  [cyan]No[/cyan]   (this is a local self-signed TCPS")
    console.print(f"        wallet, not an OCI/ADB wallet — it has no OCI certs)")
    console.print(f"  [yellow]Expected:[/yellow] PAF then warns the [bold]Knowledge Assistant won't be installed[/bold]")
    console.print(f"  (it needs OCI certs in the wallet). [green]That is fine here[/green] — CHAT_FLOW /")
    console.print(f"  RESEARCH_WORKFLOW don't use the Knowledge Assistant, and we run vLLM locally,")
    console.print(f"  not OCI services. The DB connection still succeeds and install continues.\n")

    console.print("[bold]Step 3 — installation[/bold]")
    console.print("  Click Install. PAF creates its metadata tables under AGENT_FACTORY")
    console.print("  and uses the read-only user AAI_RO_AGENT_FACTORY (pre-created by `local up`).\n")

    vllm_host, advisory = _resolve_vllm_host()
    console.print("[bold]Step 4 — LLM configuration[/bold]")
    if advisory:
        console.print(f"  [yellow]Note:[/yellow] {advisory}")
    console.print(f"  [bold]Generative model[/bold]   (Model type radio: [cyan]Generative model[/cyan])")
    console.print(f"    LLM provider:        [cyan]vLLM[/cyan]")
    console.print(f"    Configuration name:  [cyan]gen-model[/cyan]   (generic — keep stable across model swaps; CHAT_FLOW references it)")
    console.print(f"    Model ID:            [cyan]{os.getenv('VLLM_GEN_MODEL')}[/cyan]")
    console.print(f"    Host:                [cyan]http://{vllm_host}[/cyan]   (scheme required)")
    console.print(f"    Port:                [cyan]{os.getenv('VLLM_GEN_PORT')}[/cyan]")
    console.print(f"  [bold]Embedding model[/bold]   (Model type radio: [cyan]Embedding model[/cyan])")
    console.print(f"    LLM provider:        [cyan]vLLM[/cyan]")
    console.print(f"    Configuration name:  [cyan]emb-model[/cyan]")
    console.print(f"    Model ID:            [cyan]{os.getenv('VLLM_EMBED_MODEL')}[/cyan]")
    console.print(f"    Host:                [cyan]http://{vllm_host}[/cyan]")
    console.print(f"    Port:                [cyan]{os.getenv('VLLM_EMBED_PORT')}[/cyan]\n")

    console.print("[bold]After install[/bold] — sign in as the admin user and:")
    console.print("  - Verify LLM Management shows both configurations.")
    console.print("  - Agent Builder → build a trivial Chat→Prompt→LLM→Chat flow to smoke-test.")
    console.print(
        "\n[yellow]Note:[/yellow] API automation for these UI steps is intentionally out of "
        "scope (Playwright-style driving is fragile across PAF versions)."
    )


def _paf_bootstrap_cloud() -> None:
    console.print(Panel.fit("[bold]PAF UI Installer — cloud (OCI)[/bold]"))

    lb_ip = _tf_output("lb_ip")
    wallet = _tf_output("adb_wallet_path") or "deploy/tf/app/generated/adb-wallet.zip"
    compartment = os.getenv("OCI_COMPARTMENT_OCID", "")
    endpoint = os.getenv("GENAI_ENDPOINT", "")
    db_service = str(os.getenv("DB_SERVICE", "")).lower()

    if lb_ip:
        console.print(f"Open the installer:\n  [cyan]http://{lb_ip}/agentFactory/installation[/cyan]\n")
    else:
        console.print(
            "[yellow]No Terraform output yet.[/yellow] Apply deploy/tf/app first, then re-run.\n"
            "  The installer is at [cyan]http://<lb_ip>/agentFactory/installation[/cyan]\n"
        )

    console.print("[bold]Step 1 — admin user[/bold]")
    console.print("  Create an admin user (username + password — record them yourself).\n")

    console.print("[bold]Step 2 — database configuration[/bold] (ADB wallet)")
    console.print("  Connection type:  [cyan]Wallet[/cyan]")
    console.print(f"  Wallet file:      drop [cyan]{wallet}[/cyan]")
    console.print(f"  Network alias:    [cyan]{db_service}[/cyan]   (from the wallet's tnsnames)")
    console.print("  Username:         [cyan]AGENT_FACTORY[/cyan]")
    console.print("  Password:         same as DB_PASSWORD in .env")
    console.print("  [bold]PAF then asks two more questions:[/bold]")
    console.print("    Air-gapped environment?            [cyan]No[/cyan]")
    console.print("    OCI certificates added to wallet?  [cyan]Yes[/cyan]   (an ADB wallet carries them,")
    console.print("        so the Knowledge Assistant installs here — unlike the local target)\n")

    console.print("[bold]Step 3 — installation[/bold]")
    console.print("  Click Install. PAF creates its metadata tables under AGENT_FACTORY.\n")

    console.print("[bold]Step 4 — LLM configuration[/bold]   (no key material — the compute")
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
        f"in the changelog.[/dim]\n"
    )

    console.print("[bold]After install[/bold] — sign in as the admin user and:")
    console.print("  - Verify LLM Management shows both configurations and that a test call succeeds.")
    console.print("    A failure here is almost always the dynamic group or policy: apply")
    console.print("    [cyan]deploy/tf/iam[/cyan] with a tenancy-admin profile.")
    console.print("  - Register the Select AI tools against AGENT_TOOLS.PKG_AGENT_TOOLS.")
    console.print(
        "\n[yellow]Note:[/yellow] API automation for these UI steps is intentionally out of "
        "scope (Playwright-style driving is fragile across PAF versions)."
    )


# ---------------------------------------------------------------- test

@cli.group()
def test() -> None:
    """Run end-to-end tests against the local PAF stack."""


@test.command("chat-workflow")
@click.option("-k", "expr", default=None,
              help="Filter tests by name (pytest -k <expr>)")
@click.option("-v", "--verbose", "verbose", is_flag=True,
              help="Verbose pytest output (-vv)")
def test_chat_workflow(expr: str | None, verbose: bool) -> None:
    """Run the CHAT_FLOW end-to-end test suite.

    Prerequisites:
      - Stack is up (`manage.py local up`).
      - PAF is installed (admin user known).
      - CHAT_FLOW is built in Agent Builder with Text Input value
        `paf-test-runner`, saved, and Published.
      - `.env` has PAF_ADMIN_USER + PAF_ADMIN_PASS (run `setup local` to add).
    """
    _ensure_env()
    if not os.getenv("PAF_ADMIN_USER") or not os.getenv("PAF_ADMIN_PASS"):
        console.print(
            "[red]PAF_ADMIN_USER / PAF_ADMIN_PASS not set in .env.[/red]\n"
            "Re-run [cyan]python manage.py setup local[/cyan] to add them."
        )
        sys.exit(1)
    args = ["pytest", "tests/test_chat_workflow.py"]
    if verbose:
        args.append("-vv")
    if expr:
        args.extend(["-k", expr])
    _run(args)


# Three scenarios — one per recommendation tier — that the smoke test drives
# end to end as a post-install sanity check. Each maps to a pytest id in
# tests/test_chat_workflow.py.
SMOKE_SCENARIOS = ("alice-clean", "frank-warn-band", "david-dti-cap")


@cli.command("smoke")
def smoke() -> None:
    """End-to-end sanity check: drive APPROVE, REVIEW and DECLINE through the
    live stack and assert each lands in the expected tier.

    Runs three CHAT_FLOW turns (Alice → APPROVE, Frank → REVIEW,
    David → DECLINE) via the published flow, asserting the customer-facing
    reply and the hitl_task recommendation row for each. ~5–10 min wall clock
    (a full agent turn is ~1–4 min). The three requests it creates stay in
    the backoffice queue for review.

    Prerequisites are the same as `test chat-workflow`: stack up, PAF
    installed, CHAT_FLOW built + published, PAF_ADMIN_* in .env.
    """
    _ensure_env()
    if not os.getenv("PAF_ADMIN_USER") or not os.getenv("PAF_ADMIN_PASS"):
        console.print(
            "[red]PAF_ADMIN_USER / PAF_ADMIN_PASS not set in .env.[/red]\n"
            "Re-run [cyan]python manage.py setup local[/cyan] to add them."
        )
        sys.exit(1)
    console.print(Panel.fit(
        "[bold]Smoke test — APPROVE / REVIEW / DECLINE[/bold]\n"
        "Alice → APPROVE   Frank → REVIEW   David → DECLINE"
    ))
    _run(["pytest", "tests/test_chat_workflow.py", "-v",
          "-k", " or ".join(SMOKE_SCENARIOS)])
    console.print(
        "[green]Smoke passed.[/green] The three requests are now in the "
        "backoffice queue at http://localhost:5173/backoffice"
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

    _stage(PROJECT_ROOT / "opa", backend_files / "opa")
    _stage(PROJECT_ROOT / "src" / "api" / "registry", backend_files / "registry")
    _stage(PROJECT_ROOT / "database" / "liquibase", ops_files / "database" / "liquibase")

    console.print(f"[green]✓[/green] Staged every tier payload under {ANSIBLE_ROOT}")
    console.print("\nNext: [cyan]python manage.py tf[/cyan]")


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
