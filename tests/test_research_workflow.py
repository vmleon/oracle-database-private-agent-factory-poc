"""End-to-end tests for RESEARCH_WORKFLOW.

Needs the deployed backend, PAF and the private-endpoint ADB, so it runs on the
bastion through `python manage.py cloud test`, never from the host.

Each test resolves its task by querying for an open one — IDENTITY values are
non-contiguous and are never hardcoded.
"""
from __future__ import annotations

import os

import pytest
import requests

# `manage.py paf api-key` only mints PAF_RESEARCH_AGENT_ID once RESEARCH_WORKFLOW
# is imported and published, so its absence is the same "not configured yet"
# signal manage.py itself uses (FLOWS in manage.py) — the whole file skips
# rather than failing `cloud test` before that manual step is done.
pytestmark = pytest.mark.skipif(
    not os.getenv("PAF_RESEARCH_AGENT_ID"),
    reason="RESEARCH_WORKFLOW is not configured; build and publish it per "
           "CLOUD.md §10, then run `manage.py paf api-key`.",
)

# The four headings the agent is instructed to produce.
SECTIONS = ("THE CASE", "SUPPORTS APPROVING", "ARGUES AGAINST", "NOT ESTABLISHED")

# What a summary may never contain. The backend screen enforces this; the test
# asserts the property end to end rather than trusting the prompt.
VERDICTS = ("i recommend", "my recommendation", "on balance",
            "should be approved", "should be declined", "leans toward",
            "leans towards")


@pytest.fixture
def open_review_task(db):
    """The oldest task still awaiting a human decision.

    Oldest rather than newest because a research run appends to an append-only
    ledger and the reviewer's panel renders a stored summary on load: a suite
    that targets the newest case leaves it pre-filled, and the demo loses the
    run it exists to show. The oldest open case is the seeded backfill nobody
    presents from.
    """
    with db.cursor() as cur:
        cur.execute("""
            SELECT task_id, application_id
              FROM BANK_CORE.hitl_task
             WHERE state <> 'CLOSED'
             ORDER BY task_id
             FETCH FIRST 1 ROW ONLY
        """)
        row = cur.fetchone()
    if row is None:
        pytest.skip("no open HITL task to research; run the chat suite first")
    return {"task_id": int(row[0]), "application_id": int(row[1])}


def test_research_produces_an_organised_summary(research, open_review_task):
    result = research(open_review_task["task_id"])
    summary = result["summary"]
    for heading in SECTIONS:
        assert heading in summary, f"missing section {heading}"


def test_the_summary_states_no_outcome(research, open_review_task):
    summary = research(open_review_task["task_id"])["summary"].lower()
    for verdict in VERDICTS:
        assert verdict not in summary, f"summary concluded: {verdict!r}"


def test_a_run_appends_exactly_one_ledger_row(research, db, open_review_task):
    task_id = open_review_task["task_id"]
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM BANK_CORE.research_summary WHERE hitl_task_id = :t",
                    t=task_id)
        before = cur.fetchone()[0]

    result = research(task_id)

    with db.cursor() as cur:
        cur.execute("""
            SELECT research_run_id, reviewer, application_id
              FROM BANK_CORE.research_summary
             WHERE hitl_task_id = :t
             ORDER BY research_id DESC
             FETCH FIRST 1 ROW ONLY
        """, t=task_id)
        run_id, reviewer, application_id = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM BANK_CORE.research_summary WHERE hitl_task_id = :t",
                    t=task_id)
        after = cur.fetchone()[0]

    assert after == before + 1
    assert run_id == result["researchRunId"]
    assert reviewer == "Backoffice Reviewer"
    assert int(application_id) == open_review_task["application_id"]


def test_every_deterministic_node_leaves_an_audit_row(research, db, open_review_task):
    task_id = open_review_task["task_id"]
    research(task_id)
    with db.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT tool_name
              FROM BANK_CORE.research_audit
             WHERE hitl_task_id = :t
        """, t=task_id)
        tools = {row[0] for row in cur.fetchall()}
    assert tools == {
        "recommendation_for_task",
        "similar_cases_for_task",
        "decision_history_for_task",
        "transactions_for_task",
        "policy_changes_for_task",
    }


def test_an_unknown_task_writes_nothing(research, db):
    # 999999 cannot exist: the ledger must stay empty and the panel must be told.
    result = research(999999)
    assert "decision is yours" in result["summary"]
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM BANK_CORE.research_summary WHERE hitl_task_id = 999999")
        assert cur.fetchone()[0] == 0


def test_the_stored_summary_is_read_back_without_rerunning(research, env, open_review_task):
    task_id = open_review_task["task_id"]
    written = research(task_id)
    r = requests.get(
        f"{env['BACKEND_BASE']}/v1/research/tasks/{task_id}",
        timeout=30,
        verify=env["PAF_CA"],
    )
    r.raise_for_status()
    assert r.json()["researchRunId"] == written["researchRunId"]
