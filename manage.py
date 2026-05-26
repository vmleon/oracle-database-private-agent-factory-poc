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

# Caddy → Ollama HTTPS proxy. Cert + key live on the host (mounted into the
# Caddy container); the CA root is baked into the Oracle container's OS trust
# store. Hostname must match the compose service name and the SAN below.
CADDY_TLS_DIR = PROJECT_ROOT / "deploy" / "podman" / "caddy" / "tls"
CADDY_TLS_HOSTNAME = "caddy-ollama-tls"
# Oracle SSL wallet path inside the database container. DBMS_CLOUD looks
# this up via the SSL_WALLET database property (set by `_setup_oracle_ssl_wallet`).
# The wallet password is only used by orapki at create-time — the wallet is
# `-auto_login`, so DBMS_CLOUD opens it passwordlessly at runtime.
ORACLE_WALLET_DIR = "/opt/oracle/dcs/commonstore/wallets/ssl"
ORACLE_WALLET_PWD = "PafWalletPwd_internal_only"
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
    (the packages are installed by `_install_dbms_cloud` earlier), and
    appends a network ACL letting AGENT_FACTORY make outbound HTTPS to
    the Caddy TLS proxy that fronts Ollama (used by Select AI profiles).
    The ACL grants both `http` and `https` privileges — Oracle's HTTPS
    callout requires both to be present for the underlying TCP setup.
    """
    sql_lines = [
        "ALTER SESSION SET CONTAINER=FREEPDB1;",
        "GRANT SELECT ON SYS.V_$PARAMETER TO AGENT_FACTORY;",
        "GRANT EXECUTE ON DBMS_CLOUD TO AGENT_FACTORY;",
        "GRANT EXECUTE ON DBMS_CLOUD_AI TO AGENT_FACTORY;",
        "BEGIN",
        "  DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(",
        f"    host => '{CADDY_TLS_HOSTNAME}',",
        "    lower_port => 443,",
        "    upper_port => 443,",
        "    ace => xs$ace_type(",
        "      privilege_list => xs$name_list('http', 'http_proxy'),",
        "      principal_name => 'AGENT_FACTORY',",
        "      principal_type => xs_acl.ptype_db));",
        "END;",
        "/",
        "EXIT;",
    ]
    sql = "\n".join(sql_lines) + "\n"
    _run_sysdba_sql(sql, "Post-Liquibase sysdba grant", container)
    console.print("[green]✓[/green] SYS-only grants applied to AGENT_FACTORY.")
    console.print(
        f"[green]✓[/green] Network ACL: AGENT_FACTORY → {CADDY_TLS_HOSTNAME}:443 (https)."
    )


def _ensure_tls_certs() -> None:
    """Generate (once) the self-signed CA + leaf cert used by the Caddy
    HTTPS proxy in front of the LAN LLM endpoint. Idempotent: skipped if both files
    already exist.

    Why: Oracle 26ai's DBMS_CLOUD_AI rejects HTTP endpoints (ORA-20047),
    so we put Caddy in the loop to terminate TLS. Caddy serves
    `server.crt` (signed by our local CA `ca.crt`); the Oracle container
    has `ca.crt` baked into its OS trust store by
    `_install_caddy_ca_in_oracle`, so the TLS handshake succeeds. Oracle
    26ai trusts the OS cert store directly (no wallet needed for normal
    CA-rooted chains) — see Martin Carstenbach's "Using the OS cert store
    in 26ai" post.
    """
    ca_crt = CADDY_TLS_DIR / "ca.crt"
    ca_key = CADDY_TLS_DIR / "ca.key"
    server_crt = CADDY_TLS_DIR / "server.crt"
    server_key = CADDY_TLS_DIR / "server.key"
    if all(p.exists() for p in (ca_crt, ca_key, server_crt, server_key)):
        console.print(f"[green]✓[/green] Caddy TLS certs already present.")
        return
    if not shutil.which("openssl"):
        console.print(
            "[red]openssl not found on PATH.[/red] Install via "
            "`brew install openssl` (macOS) or `dnf install openssl` (OL8)."
        )
        sys.exit(1)
    CADDY_TLS_DIR.mkdir(parents=True, exist_ok=True)
    console.print(f"[bold]Generating Caddy TLS certs in {CADDY_TLS_DIR.relative_to(PROJECT_ROOT)}...[/bold]")

    # CA — 10-year validity, self-signed root.
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(ca_key), "-out", str(ca_crt),
         "-days", "3650", "-subj", "/CN=PAF-PoC Local CA"],
        check=True, capture_output=True,
    )

    # Server cert with SAN covering the compose service name + a couple
    # of fallbacks for debugging.
    csr = CADDY_TLS_DIR / "server.csr"
    ext = CADDY_TLS_DIR / "server.ext"
    ext.write_text(
        f"subjectAltName = DNS:{CADDY_TLS_HOSTNAME},DNS:localhost,IP:127.0.0.1\n"
    )
    subprocess.run(
        ["openssl", "req", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(server_key), "-out", str(csr),
         "-subj", f"/CN={CADDY_TLS_HOSTNAME}"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "x509", "-req", "-in", str(csr),
         "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial",
         "-out", str(server_crt), "-days", "365", "-extfile", str(ext)],
        check=True, capture_output=True,
    )
    # Clean up artefacts we don't need at runtime.
    for p in (csr, ext, CADDY_TLS_DIR / "ca.srl"):
        if p.exists():
            p.unlink()
    console.print(f"[green]✓[/green] CA + server certs generated (SAN: {CADDY_TLS_HOSTNAME}).")


def _setup_oracle_ssl_wallet(container: str = "paf-oracle-free-26ai") -> None:
    """Build an Oracle SSL wallet, register it via the SSL_WALLET database
    property, and add the Caddy CA cert to it.

    Oracle 26ai trusts the OS cert store for plain `UTL_HTTP`, but
    `DBMS_CLOUD` is special — it looks up an Oracle wallet whose path
    is registered as a database property. Without this, the first HTTPS
    callout from a DBMS_CLOUD profile raises
    `ORA-20000: Database property SSL_WALLET not found`.

    Steps (all idempotent):
      1. Copy the Caddy CA cert into the container.
      2. `orapki wallet create -auto_login` at `ORACLE_WALLET_DIR`
         if not already present.
      3. `orapki wallet add -trusted_cert` — re-adding the same cert
         returns a non-fatal error which we discard.
      4. Append `WALLET_LOCATION=...` to `sqlnet.ora` (only if missing).
      5. `ALTER DATABASE PROPERTY SET SSL_WALLET = ...` in CDB$ROOT
         (no-op when already set to the same value).
    """
    ca_crt = CADDY_TLS_DIR / "ca.crt"
    if not ca_crt.exists():
        console.print(f"[red]{ca_crt.relative_to(PROJECT_ROOT)} missing.[/red] "
                      "Run `_ensure_tls_certs()` first.")
        sys.exit(1)

    # 1. Copy CA into the container (overwriting any prior copy is fine).
    cp = subprocess.run(
        ["podman", "cp", str(ca_crt),
         f"{container}:/tmp/paf-caddy-ca.crt"],
        capture_output=True, text=True,
    )
    if cp.returncode != 0:
        console.print(f"[red]podman cp failed:[/red]\n{cp.stderr}")
        sys.exit(1)

    # 2-4. Wallet create + add trusted cert + sqlnet.ora append.
    # Runs as the default oracle user so file ownership matches the DB.
    bash_cmd = (
        "set -e\n"
        f"mkdir -p {ORACLE_WALLET_DIR}\n"
        f"cd {ORACLE_WALLET_DIR}\n"
        # Create only if missing — cwallet.sso is the auto-login file.
        f'if [ ! -f cwallet.sso ]; then\n'
        f'  $ORACLE_HOME/bin/orapki wallet create -wallet . '
        f'-pwd {ORACLE_WALLET_PWD} -auto_login\n'
        'fi\n'
        # Re-adding the same trusted cert returns a non-zero exit but is harmless.
        f'$ORACLE_HOME/bin/orapki wallet add -wallet . -trusted_cert '
        f'-cert /tmp/paf-caddy-ca.crt -pwd {ORACLE_WALLET_PWD} >/dev/null 2>&1 || true\n'
        # sqlnet.ora WALLET_LOCATION — idempotent.
        'SQLNET=$ORACLE_HOME/network/admin/sqlnet.ora\n'
        'if ! grep -q "WALLET_LOCATION" "$SQLNET" 2>/dev/null; then\n'
        f'  printf "\\nWALLET_LOCATION=(SOURCE=(METHOD=FILE)(METHOD_DATA=(DIRECTORY={ORACLE_WALLET_DIR})))\\n" >> "$SQLNET"\n'
        'fi\n'
    )
    wallet_setup = subprocess.run(
        ["podman", "exec", container, "bash", "-c", bash_cmd],
        capture_output=True, text=True,
    )
    if wallet_setup.returncode != 0:
        console.print(
            f"[red]Oracle wallet setup failed:[/red]\n"
            f"{wallet_setup.stdout}\n{wallet_setup.stderr}"
        )
        sys.exit(1)

    # 5. Register the wallet path with the database. Must run in CDB$ROOT
    # (no ALTER SESSION SET CONTAINER), and Oracle propagates to PDBs.
    sql = (
        f"ALTER DATABASE PROPERTY SET SSL_WALLET = '{ORACLE_WALLET_DIR}';\n"
        "EXIT;\n"
    )
    _run_sysdba_sql(sql, "SSL_WALLET database property", container)
    console.print(
        f"[green]✓[/green] Oracle SSL wallet at {ORACLE_WALLET_DIR} "
        "+ Caddy CA trusted + SSL_WALLET property set."
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

    Uses the `openai` provider with a `provider_endpoint` pointed at the
    Caddy HTTPS proxy (`https://caddy-ollama-tls/v1`) rather than at
    the vLLM endpoint directly. Caddy bridges Oracle's TLS requirement;
    its upstream is whatever LLM `VLLM_HOST:VLLM_GEN_PORT` resolves to.

    A `credential_name` is mandatory on every DBMS_CLOUD_AI profile;
    vLLM doesn't enforce auth by default, so we create a dummy `VLLM_CRED`
    with placeholder username/password.

    Idempotent: credential and profiles are dropped (ignore-if-missing)
    and recreated, so .env changes propagate cleanly.

    LOCAL CONSTRAINT (`DEPLOYMENT_TARGET=local`): Oracle Database Free
    26ai (23.26.x) rejects `provider: ollama` / `provider: openai-compatible`
    (ORA-20046) and rejects HTTP `provider_endpoint` values (ORA-20047).
    Forcing it through Caddy HTTPS clears those, but `provider: openai`
    then fails pre-flight with ORA-20401 — the on-prem build appears
    to allow-list the OpenAI hostname and reject custom endpoints at
    validation time, before the request leaves the DB. See the
    operational note in `docs/DEPLOYMENT.md`. The function therefore
    drops any leftover credential / profiles on local and skips
    creation. On ADB / cloud the same code will create profiles
    successfully — `DEPLOYMENT_TARGET=cloud` runs the full body.
    """
    deployment_target = (os.getenv("DEPLOYMENT_TARGET") or "").strip().lower()
    if deployment_target == "local":
        _drop_select_ai_artefacts(container)
        console.print(
            "[yellow]Select AI profile bootstrap skipped on local.[/yellow] "
            "Oracle Free 26ai's DBMS_CLOUD_AI rejects custom provider_endpoint "
            "values pre-flight (ORA-20401). The CHAT_WORKFLOW flow uses a generic "
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

    provider_endpoint = f"https://{CADDY_TLS_HOSTNAME}/v1"
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
        default=existing.get("VLLM_GEN_MODEL", "Qwen/Qwen2.5-32B-Instruct-AWQ"),
    ).execute()
    vllm_embed_model = inquirer.text(
        message="vLLM embedding model (HuggingFace handle):",
        default=existing.get("VLLM_EMBED_MODEL", "BAAI/bge-m3"),
    ).execute()
    vllm_embed_dim = inquirer.text(
        message="Embedding dimension:",
        default=existing.get("VLLM_EMBED_DIM", "1024"),
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
        "# Models (vLLM — OpenAI-compatible endpoints on the GPU host)\n"
        f"VLLM_HOST={vllm_host}\n"
        f"VLLM_GEN_PORT={vllm_gen_port}\n"
        f"VLLM_EMBED_PORT={vllm_embed_port}\n"
        f"VLLM_GEN_MODEL={vllm_gen_model}\n"
        f"VLLM_EMBED_MODEL={vllm_embed_model}\n"
        f"VLLM_EMBED_DIM={vllm_embed_dim}\n"
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
    _ensure_tls_certs()
    services = ["oracle-free-26ai", "caddy-ollama-tls", "opa", "opa-mcp", "ocr-mcp", "hitl-mcp", "banking-mcp", "registry-api"]
    # Always export so compose substitution succeeds even when paf isn't started.
    os.environ["PAF_APP_VERSION"] = _paf_app_version() or "unset"
    os.environ.setdefault("HOST_OS", platform.system())
    # `deploy/podman/compose.local.yml` substitutes `${OLLAMA_HOST}` /
    # `${OLLAMA_PORT}` for the Caddy upstream. Mirror the VLLM_* values
    # into those names so the Caddy service resolves the configured LLM
    # endpoint regardless of provider naming.
    os.environ["OLLAMA_HOST"] = os.environ.get("VLLM_HOST", "")
    os.environ["OLLAMA_PORT"] = os.environ.get("VLLM_GEN_PORT", "8000")
    hosts_entry = _compute_vllm_hosts_entry()
    if hosts_entry:
        os.environ["OLLAMA_HOSTS_ENTRY"] = hosts_entry
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
    console.print("[bold]Setting up Oracle SSL wallet with Caddy CA...[/bold]")
    _setup_oracle_ssl_wallet()
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
    if paf_ready:
        console.print("[bold]Configuring PAF container (post-start handshake)...[/bold]")
        _paf_post_start()
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
    _ensure_tls_certs()
    _setup_oracle_ssl_wallet()
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
        console.print(f"OCR:            http://{os.getenv('OCR_HOST')}:{os.getenv('OCR_PORT')}")
        console.print(f"OPA:            http://opa:8181 (compose-internal)")
        console.print(f"OPA MCP:        http://opa-mcp:8500/mcp/ (compose-internal — wire as PAF MCP server)")
        console.print(f"OCR MCP (stub): http://ocr-mcp:8501/mcp/ (compose-internal — wire as PAF MCP server)")
        console.print(f"HITL MCP:       http://hitl-mcp:8502/mcp/ (compose-internal — wire as PAF MCP server; create_hitl_task side effect)")
        console.print(f"Registry API:   http://registry-api:8600/openapi.json (compose-internal — wire as PAF HTTP datasource)")
        console.print(f"Caddy TLS:      https://caddy-ollama-tls/v1 (compose-internal — Oracle SSL wallet trusted)")
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

    vllm_host, advisory = _resolve_vllm_host()
    console.print("[bold]Step 4 — LLM configuration[/bold]")
    if advisory:
        console.print(f"  [yellow]Note:[/yellow] {advisory}")
    console.print(f"  [bold]Generative model[/bold]   (Model type radio: [cyan]Generative model[/cyan])")
    console.print(f"    LLM provider:        [cyan]vLLM[/cyan]")
    console.print(f"    Configuration name:  [cyan]vllm-gen-qwen2.5-32B[/cyan]   (any label)")
    console.print(f"    Model ID:            [cyan]{os.getenv('VLLM_GEN_MODEL')}[/cyan]")
    console.print(f"    Host:                [cyan]http://{vllm_host}[/cyan]   (scheme required)")
    console.print(f"    Port:                [cyan]{os.getenv('VLLM_GEN_PORT')}[/cyan]")
    console.print(f"  [bold]Embedding model[/bold]   (Model type radio: [cyan]Embedding model[/cyan])")
    console.print(f"    LLM provider:        [cyan]vLLM[/cyan]")
    console.print(f"    Configuration name:  [cyan]vllm-embed-bge-m3[/cyan]")
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
