"""Fixtures for the conversational bench.

The bench signs in through the Spring backend and reads the database to check
what the conversation left behind, so it runs from the ops bastion — the only
host that reaches both the load balancer and the private-endpoint Autonomous
Database. `python manage.py cloud bench` ships it there and writes the
environment below for the run.

Required env vars:
  - BACKEND_BASE  the load balancer, where /v1 is served
  - PAF_CA        the listener's certificate, which BACKEND_BASE is verified against
  - DB_SERVICE, DB_BACKEND_PASSWORD, DB_WALLET_PASSWORD, TNS_ADMIN

The database identity is SVC_BACKEND — a read of the rows the product wrote,
with the grants the product already holds. No fixture widens a grant to make an
assertion easier.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import oracledb
import pytest
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
ENV_FILE = Path(os.getenv("POC_ENV_FILE") or (PROJECT_ROOT / ".env"))

sys.path.insert(0, str(HERE))

# `announces_a_decision` decides what "reads as a decision" means for the
# product's own gate; the bench asks the same question of the same function so
# the two cannot drift. In the repository gate.py sits with its server; on the
# bastion `cloud bench` drops it beside tests/.
for candidate in (PROJECT_ROOT / "src" / "ai" / "banking-mcp", PROJECT_ROOT):
    if (candidate / "gate.py").exists():
        sys.path.insert(0, str(candidate))
        break

from driver import Conversation, customer_ids  # noqa: E402


def pytest_configure(config):
    """Registered here rather than in pytest.ini because the bench runs from a
    directory the repository's ini file never reaches."""
    config.addinivalue_line(
        "markers",
        "judge: scores an exchange with the deployment's generation model. Off "
        "by default in `cloud bench` — non-deterministic, and a model call per "
        "exchange.",
    )


@pytest.fixture(scope="session")
def env() -> dict[str, str]:
    load_dotenv(ENV_FILE)
    required = ("BACKEND_BASE", "PAF_CA", "DB_SERVICE", "DB_BACKEND_PASSWORD", "TNS_ADMIN")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.exit(
            f"Missing required env vars: {', '.join(missing)}.\n"
            f"Run the bench with `python manage.py cloud bench`."
        )
    return {k: os.environ[k] for k in required}


@pytest.fixture(scope="session")
def db(env):
    """Read-only companion to the conversation: the rows it left behind."""
    conn = oracledb.connect(
        user="SVC_BACKEND",
        password=env["DB_BACKEND_PASSWORD"],
        dsn=env["DB_SERVICE"],
        config_dir=env["TNS_ADMIN"],
        wallet_location=env["TNS_ADMIN"],
        wallet_password=os.getenv("DB_WALLET_PASSWORD", ""),
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def ids(env) -> dict[str, int]:
    """Persona full_name -> customer_id, resolved at runtime. IDENTITY values
    are non-contiguous, so no id is ever written down."""
    return customer_ids(env["BACKEND_BASE"], env["PAF_CA"])


@pytest.fixture
def talk(env, ids):
    """Sign a persona in and hand back the conversation. Every session opened
    by a case is revoked when it ends, so a later case cannot inherit one."""
    opened: list[Conversation] = []

    def _talk(full_name: str) -> Conversation:
        if full_name not in ids:
            pytest.fail(f"no seeded customer named {full_name!r}")
        c = Conversation(ids[full_name], ca=env["PAF_CA"], base=env["BACKEND_BASE"])
        opened.append(c)
        return c

    yield _talk

    for c in opened:
        c.logout()


@pytest.fixture
def app_row(db):
    """The customer's application as the reviewer would see it, or None."""
    def _row(customer_id: int) -> dict | None:
        with db.cursor() as cur:
            cur.execute(
                "SELECT application_id, amount_requested, term_months, purpose, status "
                "FROM BANK_CORE.loan_application WHERE customer_id = :c "
                "ORDER BY application_id DESC FETCH FIRST 1 ROWS ONLY",
                c=customer_id,
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "application_id": int(row[0]),
            "amount_requested": float(row[1]) if row[1] is not None else None,
            "term_months": int(row[2]) if row[2] is not None else None,
            "purpose": row[3],
            "status": row[4],
        }

    return _row


@pytest.fixture
def tasks_for(db):
    """Every HITL task on an application, oldest first."""
    def _tasks(application_id: int | None) -> list[dict]:
        if application_id is None:
            return []
        with db.cursor() as cur:
            cur.execute(
                "SELECT task_id, state, agent_recommendation "
                "FROM BANK_CORE.hitl_task WHERE application_id = :a ORDER BY task_id",
                a=application_id,
            )
            return [{"task_id": int(t), "state": s, "tier": r} for t, s, r in cur.fetchall()]

    return _tasks


@pytest.fixture
def new_tasks(db):
    """Tasks filed since the case started, as (task_id, application_id, tier).
    Captures the high-water mark when the fixture is built, so a case can assert
    that nothing was filed against an application other than its own."""
    with db.cursor() as cur:
        cur.execute("SELECT NVL(MAX(task_id), 0) FROM BANK_CORE.hitl_task")
        before = cur.fetchone()[0]

    def _since() -> list[tuple[int, int, str]]:
        with db.cursor() as cur:
            cur.execute(
                "SELECT task_id, application_id, agent_recommendation "
                "FROM BANK_CORE.hitl_task WHERE task_id > :id ORDER BY task_id",
                id=before,
            )
            return [(int(t), int(a), r) for t, a, r in cur.fetchall()]

    return _since


@pytest.fixture
def stored_messages(db):
    """The thread as persisted, which is not always what was sent."""
    def _rows(customer_id: int) -> list[tuple[str, str]]:
        with db.cursor() as cur:
            cur.execute(
                "SELECT sender, body FROM BANK_CORE.chat_message "
                "WHERE customer_id = :c ORDER BY message_id",
                c=customer_id,
            )
            out = []
            for sender, body in cur.fetchall():
                if hasattr(body, "read"):
                    body = body.read()
                out.append((sender, body or ""))
            return out

    return _rows
