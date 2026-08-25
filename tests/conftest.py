r"""Pytest fixtures for the CHAT_FLOW end-to-end test harness.

Strategy: each test mints a unique opaque session token (`sess_<hex>`) into
APP.auth_session pointing at the desired (customer_id, application_id), then
sends it in-band to the flow inside a `[[SESSION <token>]]` envelope. The
flow's RegexExtractor splits the token from the customer message at flow
start; each agent's first call is banking-mcp.get_context, which resolves the
token — exactly what a production App Service would do at login. Unique
per-test tokens mean no shared-row contention.

Required canvas setup (one-time, manual): the published CHAT_FLOW must
split the envelope — a RegexExtractor on `(?<=\[\[SESSION )[^\]]+` feeds the
manager prompt's `token` port, and one on `(?<=\]\])[\s\S]+` feeds its
`input` port. See paf/flows/CHAT_FLOW.md.

Required env vars (.env, loaded automatically):
  - PAF_API_KEY, PAF_AGENT_ID — integration key for the published CHAT_FLOW,
    minted by `python manage.py paf api-key`
  - DB_HOST, DB_PORT, DB_SERVICE, DB_PASSWORD — Oracle connection as APP

The key is bound to one published workflow, so no agent lookup is needed.
"""
from __future__ import annotations

import json
import os
import re
import secrets
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

_SENTINEL_RE = re.compile(r"\[\[SESSION[^\]]*\]\]")


def _sanitize(message: str) -> str:
    """Strip any [[SESSION ...]] sentinel a customer might inject. MANDATORY
    before enveloping — the security boundary depends on it."""
    return _SENTINEL_RE.sub("", message)


def _envelope(token: str, message: str, *, sanitize: bool = True) -> str:
    body = _sanitize(message) if sanitize else message
    return f"[[SESSION {token}]]\n{body}"


@pytest.fixture(scope="session")
def env() -> dict[str, str]:
    """Load .env once and validate the keys the harness needs."""
    load_dotenv(PROJECT_ROOT / ".env")
    required = ("PAF_API_KEY", "PAF_AGENT_ID", "DB_HOST", "DB_PORT",
                "DB_SERVICE", "DB_PASSWORD")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.exit(
            f"Missing required env vars: {', '.join(missing)}.\n"
            f"Run `python manage.py setup local`, then `python manage.py paf api-key` "
            f"once CHAT_FLOW is published."
        )
    return {k: os.environ[k] for k in required}


@pytest.fixture(scope="session")
def paf(env) -> requests.Session:
    """PAF session carrying the integration key. Reused across tests."""
    s = requests.Session()
    s.verify = False
    s.headers["Authorization"] = f"Bearer {env['PAF_API_KEY']}"
    return s


@pytest.fixture(scope="session")
def agent_id(env) -> str:
    """The published CHAT_FLOW the integration key is bound to."""
    return env["PAF_AGENT_ID"]


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


@pytest.fixture
def resolve(db):
    """Resolve a customer's (customer_id, application_id) by full_name.

    Surrogate keys are IDENTITY values and are non-contiguous, so tests address
    rows by the stable full_name from the synthetic seed rather than by hardcoded
    IDs. Each scenario customer owns exactly one application."""
    def _resolve(full_name: str) -> tuple[int, int]:
        with db.cursor() as cur:
            cur.execute(
                "SELECT c.customer_id, la.application_id "
                "FROM APP.customer c "
                "JOIN APP.loan_application la ON la.customer_id = c.customer_id "
                "WHERE c.full_name = :n",
                n=full_name,
            )
            row = cur.fetchone()
        if row is None:
            pytest.fail(f"no customer+application found for full_name={full_name!r}")
        return int(row[0]), int(row[1])

    return _resolve


@pytest.fixture
def mint_session(db):
    """Per-test: mint unique opaque session tokens in APP.auth_session and clean
    them up on teardown. Returns mint(customer_id, application_id) -> token.

    Each call issues a fresh `sess_<hex>` token with a 15-minute expiry, so tests
    never contend on a shared row."""
    minted: list[str] = []

    def _mint(customer_id: int, application_id: int) -> str:
        token = "sess_" + secrets.token_hex(16)
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO APP.auth_session "
                "(session_token, customer_id, application_id, scenario_label, "
                " expires_at) "
                "VALUES (:t, :c, :a, 'pytest-mint', "
                "        SYSTIMESTAMP + INTERVAL '15' MINUTE)",
                t=token, c=customer_id, a=application_id,
            )
        db.commit()
        minted.append(token)
        return token

    yield _mint

    if minted:
        with db.cursor() as cur:
            for t in minted:
                cur.execute(
                    "DELETE FROM APP.auth_session WHERE session_token = :t", t=t
                )
        db.commit()


@pytest.fixture
def chat(paf, agent_id):
    """POST a chat turn through the published CHAT_FLOW integration endpoint,
    wrapping token + message in the [[SESSION ...]] envelope the flow's
    RegexExtractor splits. Returns the unwrapped response body."""
    def _run(token: str, message: str, *, sanitize: bool = True) -> dict:
        r = paf.post(
            f"{PAF_BASE}/agentFactory/v1/integrations/agents/{agent_id}/run",
            json={"message": _envelope(token, message, sanitize=sanitize)},
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
def evidence_and_trace(db):
    """Return a callable: application_id -> (evidence dict, tool-name list).

    The review portal reads the evidence by key name and renders the trace from
    APP.decision_audit, so both are part of the contract a run must satisfy."""
    def _for(application_id: int) -> tuple[dict, list[str]]:
        with db.cursor() as cur:
            cur.execute(
                "SELECT agent_evidence FROM APP.hitl_task "
                "WHERE application_id = :a ORDER BY task_id DESC FETCH FIRST 1 ROWS ONLY",
                a=application_id,
            )
            row = cur.fetchone()
            ev = row[0] if row else None
            if hasattr(ev, "read"):
                ev = ev.read()
            if isinstance(ev, str):
                ev = json.loads(ev)
            cur.execute(
                "SELECT tool_name FROM APP.decision_audit "
                "WHERE application_id = :a ORDER BY step_no",
                a=application_id,
            )
            return (ev or {}), [t for (t,) in cur.fetchall()]
    return _for


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
