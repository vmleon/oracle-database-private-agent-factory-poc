#!/usr/bin/env python3
"""CLI for managing the Oracle PAF Decisioning Engine PoC."""

import os
import secrets
import shutil
import subprocess
import sys
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


def _wait_for_db(container: str = "paf-oracle-free-26ai", timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["podman", "exec", container, "/opt/oracle/checkDBStatus.sh"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]✓[/green] Oracle DB is healthy.")
            return
        time.sleep(5)
    console.print("[red]Timed out waiting for Oracle DB.[/red] See `manage.py local logs oracle-free-26ai`.")
    sys.exit(1)


def _provision_local() -> None:
    load_dotenv(ENV_FILE)
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
        default=existing.get("OLLAMA_LLM_MODEL", "llama3.2"),
    ).execute()
    ollama_embed = inquirer.text(
        message="Ollama embedding model:",
        default=existing.get("OLLAMA_EMBED_MODEL", "multilingual-e5-base"),
    ).execute()
    ollama_embed_dim = inquirer.text(
        message="Embedding dimension:",
        default=existing.get("OLLAMA_EMBED_DIM", "768"),
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
    console.print("[bold]Starting podman containers...[/bold]")
    _run(["podman", "compose", "-f", str(PODMAN_COMPOSE), "up", "-d"])
    console.print("[bold]Waiting for Oracle DB to be healthy (up to 5 min)...[/bold]")
    _wait_for_db()
    console.print("[bold]Provisioning database (Ansible → Liquibase)...[/bold]")
    _provision_local()
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


# ---------------------------------------------------------------- paf

@cli.group()
def paf() -> None:
    """Private Agent Factory operations."""


@paf.command("bootstrap")
def paf_bootstrap() -> None:
    """Print the manual PAF bootstrap checklist."""
    console.print(Panel.fit("[bold]PAF Bootstrap Checklist[/bold]"))
    steps = [
        "Open the PAF UI (URL from `manage.py info`) and sign in.",
        "LLM Management → add Ollama generative + embedding configurations using the host/port in .env.",
        "Data sources → add a Database data source over REPORTING views, and a File data source for policy_corpus.",
        "Select AI → create a profile with NL2SQL object list scoped to REPORTING.*, and a RAG vector index over policy_corpus.",
        "MCP Servers → register opa-mcp and ocr-mcp (URLs from .env, auth as configured).",
        "Agent Builder → import the HELLO_AGENT flow (v0) or DECISIONING_AGENT flow (v1+).",
        "Publish the agent and paste the run URL when prompted.",
    ]
    for i, s in enumerate(steps, 1):
        console.print(f"  [cyan]{i}.[/cyan] {s}")
    console.print(
        "\n[yellow]Note:[/yellow] API automation for these steps is planned for a later PR. "
        "Playwright-style UI driving is deliberately avoided as too fragile across PAF versions."
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
