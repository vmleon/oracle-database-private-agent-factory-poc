"""Pytest fixtures for the CHAT_WORKFLOW end-to-end test harness.

Strategy: avoid the per-scenario canvas rebuild by using a single fixed
session token (`paf-test-runner`) baked into the canvas's Text Input, and
scaffolding APP.auth_session per test to point that token at the desired
(customer_id, application_id). banking-mcp.lookup_application resolves the
token via the DB row we just wrote — exactly what a production App Service
would do at login. PAF issue 02 (no per-invocation inputs) is sidestepped.

Required canvas setup (one-time, manual):
  1. Set Text Input(session_token) value = "paf-test-runner"
  2. Save the flow
  3. Click Publish in the canvas top bar

Required env vars (.env, loaded automatically):
  - PAF_ADMIN_USER, PAF_ADMIN_PASS — programmatic login via /v1/loginValidation
  - DB_HOST, DB_PORT, DB_SERVICE, DB_PASSWORD — Oracle connection as APP
  - CHAT_WORKFLOW_AGENT_ID (optional) — pin the agent_id; auto-discovers
    by name from /v1/agents when unset.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

import oracledb
import pytest
import requests
from dotenv import load_dotenv
from urllib3.exceptions import InsecureRequestWarning

# PAF terminates TLS with a self-signed cert; accepted for the local POC.
warnings.simplefilter("ignore", InsecureRequestWarning)

PROJECT_ROOT = Path(__file__).parent.parent
PAF_BASE = "https://localhost:8080"
RUNNER_TOKEN = "paf-test-runner"


@pytest.fixture(scope="session")
def env() -> dict[str, str]:
    """Load .env once and validate the keys the harness needs."""
    load_dotenv(PROJECT_ROOT / ".env")
    required = ("PAF_ADMIN_USER", "PAF_ADMIN_PASS", "DB_HOST", "DB_PORT",
                "DB_SERVICE", "DB_PASSWORD")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.exit(
            f"Missing required env vars: {', '.join(missing)}.\n"
            f"Run `python manage.py setup local` and fill in the prompts."
        )
    return {k: os.environ[k] for k in required}


@pytest.fixture(scope="session")
def paf(env) -> requests.Session:
    """Authenticated PAF requests.Session. Cookie set once; reused per test."""
    s = requests.Session()
    s.verify = False
    r = s.get(
        f"{PAF_BASE}/agentFactory/v1/loginValidation",
        auth=(env["PAF_ADMIN_USER"], env["PAF_ADMIN_PASS"]),
        timeout=30,
    )
    if r.status_code != 200:
        pytest.exit(
            f"PAF login failed: HTTP {r.status_code}. "
            f"Check PAF_ADMIN_USER / PAF_ADMIN_PASS in .env.\n"
            f"Response: {r.text[:300]}"
        )
    return s


@pytest.fixture(scope="session")
def agent_id(paf) -> str:
    """Find CHAT_WORKFLOW's agent_id. Honour env override; else discover."""
    pinned = os.getenv("CHAT_WORKFLOW_AGENT_ID")
    if pinned:
        return pinned
    r = paf.get(f"{PAF_BASE}/agentFactory/v1/agents", timeout=30)
    r.raise_for_status()
    body = r.json()
    data = body.get("data") if isinstance(body, dict) else body
    # PAF wraps the list as {"data": {"count": N, "items": [...]}}.
    agents = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(agents, list):
        pytest.exit(f"Unexpected /v1/agents response shape: {body}")
    for a in agents:
        if a.get("name") == "CHAT_WORKFLOW":
            aid = a.get("agentId") or a.get("agent_id")
            if aid:
                return aid
    pytest.exit(
        "CHAT_WORKFLOW not found in PAF's agent list. "
        "Build it per paf/flows/CHAT_WORKFLOW.md, or set CHAT_WORKFLOW_AGENT_ID."
    )


@pytest.fixture(scope="session")
def db(env):
    """Oracle connection as APP — owns auth_session and hitl_task."""
    conn = oracledb.connect(
        user="APP",
        password=env["DB_PASSWORD"],
        dsn=f"{env['DB_HOST']}:{env['DB_PORT']}/{env['DB_SERVICE']}",
    )
    yield conn
    conn.close()


def _clear_runner_token(db) -> None:
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM APP.auth_session WHERE session_token = :t",
            t=RUNNER_TOKEN,
        )
    db.commit()


@pytest.fixture
def runner_token(db):
    """Per-test: clear the runner token row, yield a setter for the desired
    (customer_id, application_id), then clear again on teardown."""
    _clear_runner_token(db)

    def _set(customer_id: int, application_id: int) -> None:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO APP.auth_session "
                "(session_token, customer_id, application_id, scenario_label) "
                "VALUES (:t, :c, :a, 'pytest-runner')",
                t=RUNNER_TOKEN, c=customer_id, a=application_id,
            )
        db.commit()

    yield _set
    _clear_runner_token(db)


@pytest.fixture
def chat(paf, agent_id):
    """POST a chat message through the published CHAT_WORKFLOW endpoint.
    Returns the unwrapped response body (PAF wraps as {data, errorMessages, ...})."""
    def _run(message: str) -> dict:
        r = paf.post(
            f"{PAF_BASE}/agentFactory/v1/agentBuilder/run/{agent_id}",
            json={"message": message},
            timeout=300,  # vLLM 72B can take 60-90s for a full agent turn
        )
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict):
            errs = body.get("errorMessages") or []
            if errs:
                pytest.fail(f"PAF runner returned errors: {errs}")
            return body.get("data", body)
        return body
    return _run


@pytest.fixture
def new_hitl_rows(db):
    """Capture the latest task_id at fixture-creation; return a callable that
    yields rows created since. Use to assert exactly-N rows per test."""
    with db.cursor() as cur:
        cur.execute("SELECT NVL(MAX(task_id), 0) FROM APP.hitl_task")
        before = cur.fetchone()[0]

    def _since() -> list[tuple[int, int, str, str]]:
        with db.cursor() as cur:
            cur.execute(
                "SELECT task_id, application_id, agent_recommendation, "
                "       agent_reasoning "
                "FROM APP.hitl_task WHERE task_id > :id ORDER BY task_id",
                id=before,
            )
            rows = []
            for tid, app, tier, reasoning in cur.fetchall():
                if hasattr(reasoning, "read"):
                    reasoning = reasoning.read()
                rows.append((tid, app, tier, reasoning))
            return rows

    return _since
