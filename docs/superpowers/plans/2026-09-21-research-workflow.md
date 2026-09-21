# `RESEARCH_WORKFLOW` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a reviewer holding a `REVIEW` task presses **Run research** and gets a decision-support summary — composed from evidence the task screen does not show — recorded as a row in an append-only blockchain table.

**Architecture:** a fourteen-node PAF flow whose Agent node holds **no tools**. Five `Deterministic MCP` nodes fan out from one `{"task_id": N}` payload, and the agent reads their results out of named prompt ports and writes prose. A third MCP server, `research-mcp`, logs in as `BACKOFFICE_AGENT_RO` (`SELECT` only). The Spring backend screens the summary for outcome verdicts before anything is persisted or shown.

**Tech Stack:** FastMCP (Python 3.11, backend tier), Oracle 26ai + Liquibase, Spring Boot, React + vitest, PAF Agent Builder, Terraform/Ansible.

**Spec:** [`docs/superpowers/specs/2026-09-21-research-workflow-design.md`](../specs/2026-09-21-research-workflow-design.md)

## Global Constraints

- **The PAF kit is vendor code.** `paf/dist/` and `paf-kit/` are never touched.
- **Docs describe the final state.** No "removed", "previously", "now", "no longer", no status markers, anywhere in repo docs or code comments.
- **No personal details** in any file, comment, commit message or doc.
- **Never edit an applied Liquibase changeset.** Add a new changeset — including when adding grants to `020-client-grants.yaml`, where a _new changeset id in the same file_ is correct and keeps the grant matrix readable in one place.
- **A `runOnChange: true` changeset is edited in place** — and the newest changeset defining an object is the one to edit. `027` is new, so it is edited in place from here on.
- **No hardcoded IDENTITY ids.** Seeds and tests resolve by `full_name`.
- **Privilege follows the audience.** `research-mcp` logs in as `BACKOFFICE_AGENT_RO` and gets no `EXECUTE` and no write grant, ever. `SVC_BACKEND` does the writing.
- **The generation model is `openai.gpt-oss-120b`**, registered as `gen-model`, temperature `0.01`.
- **The flow bundle password is `WelcomeAmigo123!`**.
- **A payload change reaches a running tier through `cloud redeploy`, not `cloud up`.**
- **Ports:** `banking-mcp` 8503, `application-mcp` 8504, `research-mcp` **8505**.

---

## Who does what

| Task                                                 | Claude | You |
| ---------------------------------------------------- | ------ | --- |
| 1 Schema — views, blockchain table, grants           | ✓      |     |
| 2 `match.py` — comparable-case bands                 | ✓      |     |
| 3 `research-mcp` — the five tools                    | ✓      |     |
| 4 `ResearchSummary.screen` — the no-lean rule        | ✓      |     |
| 5 Backend — service, endpoints, persistence          | ✓      |     |
| 6 Reviewer panel                                     | ✓      |     |
| 7 Deployment — Ansible, `manage.py`, `CLOUD.md`      | ✓      |     |
| 8 `paf/flows/RESEARCH_WORKFLOW.md` blueprint         | ✓      |     |
| 9 End-to-end test                                    | ✓      |     |
| 10 Docs and backlog                                  | ✓      |     |
| 11 Deploy, build the canvas, publish, export, verify |        | ✓   |

**Task 11 is last and cannot move.** The `Deterministic MCP tool` node's tool dropdown lists only what PAF discovers from a _registered, running_ server, so `research-mcp` must be deployed and registered before the canvas can be built.

---

## File structure

| File                                                            | Responsibility                                              |
| --------------------------------------------------------------- | ----------------------------------------------------------- |
| `database/liquibase/027-research-workflow.yaml`                 | two widened views + `research_summary` blockchain table     |
| `database/liquibase/020-client-grants.yaml`                     | one appended changeset: `SVC_BACKEND` on `research_summary` |
| `src/ai/research-mcp/match.py`                                  | pure band arithmetic — host-testable                        |
| `src/ai/research-mcp/server.py`                                 | five read tools, `BACKOFFICE_AGENT_RO`                      |
| `src/ai/research-mcp/Dockerfile`, `requirements.txt`            | copies of `banking-mcp`'s                                   |
| `src/backend/.../research/ResearchSummary.java`                 | the no-lean screen — pure, no Spring                        |
| `src/backend/.../research/ResearchPafClient.java`               | posts to `RESEARCH_WORKFLOW`'s agent id                     |
| `src/backend/.../research/ResearchService.java`                 | run, screen, persist, read back                             |
| `src/backend/.../research/ResearchController.java`              | `/v1/research/*`                                            |
| `src/backend/.../audit/AuditController.java`                    | one added `/v1/audit/research` mapping                      |
| `src/backend/.../audit/ResearchAuditService.java`               | writes `research_audit`                                     |
| `src/backoffice-ui/src/components/backoffice/ResearchPanel.tsx` | button, pending state, summary                              |
| `paf/flows/RESEARCH_WORKFLOW.md`                                | canvas build blueprint                                      |
| `tests/unit/test_research_match.py`                             | band arithmetic                                             |
| `tests/test_research_workflow.py`                               | end to end on the bastion                                   |

---

## Task 1: Schema

**Files:**

- Create: `database/liquibase/027-research-workflow.yaml`
- Modify: `database/liquibase/db.changelog-master.yaml` (register `027`)
- Modify: `database/liquibase/020-client-grants.yaml` (append one changeset)

**Interfaces:**

- Produces: `BANK_VIEWS.research_v_hitl_task` with columns `task_id, application_id, customer_id, state, agent_recommendation, agent_reasoning, agent_evidence, agent_explore_hints, agent_run_id, human_outcome, created_at, closed_at, amount_requested, term_months, purpose`; `BANK_VIEWS.research_v_decision_history` with `customer_id` added; `BANK_CORE.research_summary(research_id, application_id, hitl_task_id, research_run_id, reviewer, summary, created_at)`.

- [ ] **Step 1: Create the changeset**

Create `database/liquibase/027-research-workflow.yaml`:

```yaml
databaseChangeLog:
  # The research identity reads the case under review through this view. It
  # carries the recommendation packet because the summary is written against
  # it, and the application's own values because comparable cases are matched
  # on them.
  - changeSet:
      id: 027-research-view-hitl-task
      author: paf-poc
      runOnChange: true
      changes:
        - sql:
            sql: |-
              CREATE OR REPLACE VIEW BANK_VIEWS.research_v_hitl_task AS
              SELECT
                t.task_id,
                t.application_id,
                la.customer_id,
                t.assigned_to,
                t.state,
                t.agent_recommendation,
                t.agent_reasoning,
                t.agent_evidence,
                t.agent_explore_hints,
                t.agent_run_id,
                t.human_outcome,
                t.human_user,
                t.created_at,
                t.closed_at,
                la.amount_requested,
                la.term_months,
                la.purpose,
                la.product_type
              FROM BANK_CORE.hitl_task t
              JOIN BANK_CORE.loan_application la
                ON la.application_id = t.application_id

  # customer_id is what makes "this customer's past decisions" answerable;
  # the decision row carries only the application it closed.
  - changeSet:
      id: 027-research-view-decision-history
      author: paf-poc
      runOnChange: true
      changes:
        - sql:
            sql: |-
              CREATE OR REPLACE VIEW BANK_VIEWS.research_v_decision_history AS
              SELECT
                d.decision_id,
                d.application_id,
                la.customer_id,
                d.human_outcome,
                d.human_user,
                d.decided_at,
                d.agent_recommendation,
                d.agent_run_id,
                d.computed_dti,
                d.computed_pti
              FROM BANK_CORE.decision d
              JOIN BANK_CORE.loan_application la
                ON la.application_id = d.application_id

  # One row per research run, appended when the reviewer runs it rather than
  # copied onto the decision at close, so the record carries the moment the
  # reviewer read it. application_id is a plain indexed column: a blockchain
  # table cannot carry a foreign key, which is why `decision` links the same way.
  - changeSet:
      id: 027-create-research-summary-blockchain-table
      author: paf-poc
      changes:
        - sql:
            sql: |-
              CREATE BLOCKCHAIN TABLE BANK_CORE.research_summary (
                research_id     NUMBER GENERATED ALWAYS AS IDENTITY,
                application_id  NUMBER NOT NULL,
                hitl_task_id    NUMBER NOT NULL,
                research_run_id VARCHAR2(60) NOT NULL,
                reviewer        VARCHAR2(120) NOT NULL,
                summary         CLOB NOT NULL,
                created_at      TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT uq_research_id UNIQUE (research_id)
              ) NO DROP UNTIL 2555 DAYS IDLE
                NO DELETE LOCKED
                HASHING USING "SHA2_512" VERSION "v1"
        - sql:
            sql: |-
              CREATE INDEX BANK_CORE.ix_research_summary_application
                ON BANK_CORE.research_summary(application_id)
        - sql:
            sql: |-
              CREATE INDEX BANK_CORE.ix_research_summary_task
                ON BANK_CORE.research_summary(hitl_task_id)
```

- [ ] **Step 2: Register it in the master changelog**

Add to `database/liquibase/db.changelog-master.yaml`, following the existing entry format and immediately after the `026` include:

```yaml
- include:
    file: 027-research-workflow.yaml
    relativeToChangelogFile: true
    context: adb
```

Read the `026` entry first and copy its exact key ordering and context value.

- [ ] **Step 3: Append the grant changeset**

Append to the **end** of `database/liquibase/020-client-grants.yaml` — a new id, same file, so the grant matrix stays in one place:

```yaml
# ------------------------------------------ SVC_BACKEND (research) --
# The Application Service writes the research summary, as it writes the
# decision row: the MCP wrapper posts and the backend inserts, so
# BACKOFFICE_AGENT_RO needs no write grant anywhere.
- changeSet:
    id: 020-grant-svc-backend-research-summary
    author: paf-poc
    changes:
      - sql:
          sql: |-
            GRANT SELECT, INSERT ON BANK_CORE.research_summary TO SVC_BACKEND
```

- [ ] **Step 4: Apply and verify against the deployed ADB**

Steps 4–6 need a running stack. If the ADB is not deployed right now, write the changesets, commit at Step 7, and run these three verifications as part of Task 11 Step 1 instead — they are the same commands.

Run:

```bash
python manage.py cloud redeploy ops
python manage.py cloud sql "SELECT object_name, status FROM ALL_OBJECTS WHERE object_name IN ('RESEARCH_V_HITL_TASK','RESEARCH_V_DECISION_HISTORY','RESEARCH_SUMMARY')"
```

Expected: three rows, all `VALID`. A view that comes back `INVALID` means the join column names are wrong — read the base table and fix the changeset in place (`runOnChange` re-runs it).

- [ ] **Step 5: Verify the blockchain clauses took**

Run:

```bash
python manage.py cloud sql "SELECT table_name, row_retention, hash_algorithm FROM USER_BLOCKCHAIN_TABLES"
```

Expected: `RESEARCH_SUMMARY` listed beside `DECISION`, hash algorithm `SHA2_512`.

- [ ] **Step 6: Verify the grant**

```bash
python manage.py cloud sql "SELECT grantee, privilege FROM ALL_TAB_PRIVS WHERE table_name = 'RESEARCH_SUMMARY'"
```

Expected: `SVC_BACKEND` with `SELECT` and `INSERT`, and nothing else.

- [ ] **Step 7: Commit**

```bash
git add database/liquibase/027-research-workflow.yaml \
        database/liquibase/db.changelog-master.yaml \
        database/liquibase/020-client-grants.yaml
git commit -m "feat(db): research views, the research_summary ledger and its grant"
```

---

## Task 2: `match.py` — comparable-case bands

**Files:**

- Create: `src/ai/research-mcp/match.py`
- Test: `tests/unit/test_research_match.py`

**Interfaces:**

- Produces: `missing_match_keys(case) -> list[str]`, `bands_for(case) -> dict | None`, `outcome_split(cases) -> dict[str, int]`, and the constants `AMOUNT_TOLERANCE`, `DTI_TOLERANCE`, `SCORE_TOLERANCE`, `MAX_COMPARABLES`. `bands_for` returns keys `amount_low`, `amount_high`, `dti_low`, `dti_high`, `score_low`, `score_high` — these are the bind-variable names Task 3's SQL uses.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_research_match.py`:

```python
"""Unit tests for research-mcp's pure comparable-case matching.

These run on the host: match.py imports neither fastmcp nor oracledb.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ai" / "research-mcp"))

from match import (  # noqa: E402
    MAX_COMPARABLES,
    bands_for,
    missing_match_keys,
    outcome_split,
)

COMPLETE = {"amount": 20000, "dti": 0.32, "credit_score": 700}


def test_a_complete_case_has_nothing_missing():
    assert missing_match_keys(COMPLETE) == []


@pytest.mark.parametrize("key", ["amount", "dti", "credit_score"])
def test_an_absent_key_is_reported(key):
    case = dict(COMPLETE)
    case[key] = None
    assert missing_match_keys(case) == [key]


@pytest.mark.parametrize("amount", [0, -5000])
def test_a_non_positive_amount_cannot_be_matched_on(amount):
    # A band of +/-25% around zero matches every case ever closed.
    assert missing_match_keys({**COMPLETE, "amount": amount}) == ["amount"]


def test_no_case_at_all_reports_every_key():
    assert missing_match_keys(None) == ["amount", "dti", "credit_score"]


def test_bands_are_centred_on_the_case_under_review():
    assert bands_for(COMPLETE) == {
        "amount_low": 15000.0,
        "amount_high": 25000.0,
        "dti_low": 0.27,
        "dti_high": 0.37,
        "score_low": 660,
        "score_high": 740,
    }


def test_an_incomplete_case_yields_no_bands():
    # Fail closed: a partial window would match on whatever happened to be
    # present, and report the result as "comparable".
    assert bands_for({**COMPLETE, "dti": None}) is None
    assert bands_for(None) is None


def test_outcome_split_counts_how_comparable_cases_were_decided():
    cases = [{"outcome": "APPROVE"}, {"outcome": "DECLINE"}, {"outcome": "APPROVE"}]
    assert outcome_split(cases) == {"APPROVE": 2, "DECLINE": 1}


def test_outcome_split_of_nothing_is_zero_of_each():
    # The summary says "no comparable cases" from this, so both keys are present.
    assert outcome_split([]) == {"APPROVE": 0, "DECLINE": 0}


def test_the_comparable_cap_is_small_enough_to_read():
    assert MAX_COMPARABLES == 6
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/unit/test_research_match.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'match'`.

- [ ] **Step 3: Write the implementation**

Create `src/ai/research-mcp/match.py`:

```python
"""Pure comparable-case matching for the backoffice research tools.

Free of fastmcp and oracledb so the arithmetic can be unit-tested on the host,
exactly as gate.py is for banking-mcp.

`case_history` records an outcome and prose, not reason codes, so "comparable"
can only mean a numeric window: a case of similar size, affordability and
credit standing. The window is what the SQL binds; the outcomes are what the
reviewer reads.
"""

from __future__ import annotations

from typing import Any

# How far a closed case may sit from the case under review and still be
# comparable. Wide enough that a few dozen seeded cases return something,
# narrow enough that the word means something.
AMOUNT_TOLERANCE = 0.25
DTI_TOLERANCE = 0.05
SCORE_TOLERANCE = 40

# The reviewer reads these beside everything else on the screen; a long list
# stops being evidence and starts being a table.
MAX_COMPARABLES = 6

# What a case must supply before any window can be centred on it.
MATCH_KEYS = ("amount", "dti", "credit_score")


def missing_match_keys(case: dict[str, Any] | None) -> list[str]:
    """The comparison keys this case cannot supply.

    An amount of zero or less is as unusable as an absent one: a window of
    +/-25% around zero matches every case ever closed.
    """
    row = case or {}
    missing: list[str] = []
    for key in MATCH_KEYS:
        value = row.get(key)
        if value is None:
            missing.append(key)
        elif key == "amount" and float(value) <= 0:
            missing.append(key)
    return missing


def bands_for(case: dict[str, Any] | None) -> dict[str, Any] | None:
    """The numeric window a comparable case falls in.

    None when the case under review cannot supply every key — the caller then
    reports no comparables, rather than matching on whichever half was present
    and calling the result comparable.
    """
    if missing_match_keys(case):
        return None
    amount = float(case["amount"])
    dti = float(case["dti"])
    score = int(case["credit_score"])
    return {
        "amount_low": round(amount * (1 - AMOUNT_TOLERANCE), 2),
        "amount_high": round(amount * (1 + AMOUNT_TOLERANCE), 2),
        "dti_low": round(dti - DTI_TOLERANCE, 2),
        "dti_high": round(dti + DTI_TOLERANCE, 2),
        "score_low": score - SCORE_TOLERANCE,
        "score_high": score + SCORE_TOLERANCE,
    }


def outcome_split(cases: list[dict[str, Any]] | None) -> dict[str, int]:
    """How the comparable cases were decided. Both keys are always present, so
    an empty match reads as "none either way" rather than as missing data."""
    split = {"APPROVE": 0, "DECLINE": 0}
    for case in cases or []:
        outcome = case.get("outcome")
        if outcome in split:
            split[outcome] += 1
    return split
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/unit/test_research_match.py -q`
Expected: 10 passed.

- [ ] **Step 5: Run the whole host suite**

Run: `./venv/bin/python -m pytest tests/unit -q`
Expected: all pass, no new failures.

- [ ] **Step 6: Commit**

```bash
git add src/ai/research-mcp/match.py tests/unit/test_research_match.py
git commit -m "feat(research): band arithmetic for comparable closed cases"
```

---

## Task 3: `research-mcp` — the five read tools

**Files:**

- Create: `src/ai/research-mcp/server.py`
- Create: `src/ai/research-mcp/requirements.txt` (copy of `src/ai/banking-mcp/requirements.txt`)
- Create: `src/ai/research-mcp/Dockerfile` (copy of `src/ai/banking-mcp/Dockerfile`)

**Interfaces:**

- Consumes: `match.bands_for`, `match.missing_match_keys`, `match.outcome_split`, `match.MAX_COMPARABLES` from Task 2; the views from Task 1.
- Produces: five MCP tools, each taking `task_id: int` and each returning a dict whose first three keys are `task_id`, `application_id`, `customer_name` — the echo that makes a miscopied id visible. `recommendation_for_task` returns `{task_id, application_id, customer_name, tier, reasoning, reason_codes, evidence, explore_hints, amount, term_months, purpose}` or `{"error": "task_not_found"}`.

- [ ] **Step 1: Copy the packaging files**

```bash
mkdir -p src/ai/research-mcp
cp src/ai/banking-mcp/requirements.txt src/ai/research-mcp/requirements.txt
cp src/ai/banking-mcp/Dockerfile src/ai/research-mcp/Dockerfile
```

Read `src/ai/research-mcp/Dockerfile` and change any `banking-mcp` string and any `8503` to `research-mcp` / `8505`.

- [ ] **Step 2: Write the server**

Create `src/ai/research-mcp/server.py`:

```python
"""research-mcp — the backoffice reviewer's read-only research surface.

Five tools, each taking only a HITL task id. Four answer questions the task
detail screen does not already answer — how comparable cases were decided,
what this customer's own history says, what the transactions show, and which
policy thresholds moved since the case was assessed. The fifth returns the
case under review itself, which the summary is written against and which the
flow's gate tests.

Connects as BACKOFFICE_AGENT_RO: SELECT on the BANK_VIEWS.research_v_* set and
cust_360, no EXECUTE anywhere and no write grant of any kind (Liquibase 020).
A research agent that cannot write is structurally unable to decide anything.

Every tool echoes the case it resolved — task id, application id, customer
name — so a task id miscopied anywhere upstream arrives labelled as the wrong
case rather than reading as a plausible answer about the right one.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx
import oracledb
from fastmcp import FastMCP

from match import MAX_COMPARABLES, bands_for, missing_match_keys, outcome_split


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


_AUDIT_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8090").rstrip("/") + "/v1/audit/research"

mcp = FastMCP("research-mcp")

DB_DSN = os.environ["DB_DSN"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_WALLET_PASSWORD = os.environ["DB_WALLET_PASSWORD"]
TNS_ADMIN = os.environ["TNS_ADMIN"]


def _connect():
    """Open a database connection. Autonomous Database is behind mTLS, so the
    wallet directory supplies both the alias in DB_DSN and the certificates."""
    return oracledb.connect(
        user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN,
        config_dir=TNS_ADMIN, wallet_location=TNS_ADMIN,
        wallet_password=DB_WALLET_PASSWORD,
    )


def _audit(tool_name, status, started, ended, tool_input, tool_output, *, task_id):
    """Best-effort per-tool audit to the Application Service, which owns the
    write. Never raises — an audit failure must not break the live call."""
    try:
        httpx.post(_AUDIT_URL, json={
            "hitlTaskId": task_id,
            "toolName": tool_name,
            "status": status,
            "startedAt": started.isoformat(),
            "endedAt": ended.isoformat(),
            "toolInput": json.dumps(tool_input, default=str),
            "toolOutput": json.dumps(tool_output, default=str),
        }, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 — audit is fire-and-forget
        print(f"[audit] skipped ({tool_name}): {exc}", flush=True)


def _rows(cur):
    """Every row as a dict keyed by lowercase column name."""
    columns = [d[0].lower() for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _clob(value):
    return value.read() if hasattr(value, "read") else value


def _f(v):
    return None if v is None else float(v)


def _i(v):
    return None if v is None else int(v)


_TASK_SQL = """
    SELECT t.task_id, t.application_id, t.customer_id, t.state,
           t.agent_recommendation, t.agent_reasoning, t.agent_evidence,
           t.agent_explore_hints, t.agent_run_id, t.created_at,
           t.amount_requested, t.term_months, t.purpose,
           c.full_name, c.credit_score
      FROM BANK_VIEWS.research_v_hitl_task t
      JOIN BANK_VIEWS.cust_360 c ON c.customer_id = t.customer_id
     WHERE t.task_id = :task_id
"""

_SIMILAR_SQL = f"""
    SELECT case_id, amount, term_months, dti, pti, credit_score,
           outcome, outcome_reason
      FROM BANK_VIEWS.research_v_case_history
     WHERE amount       BETWEEN :amount_low AND :amount_high
       AND dti          BETWEEN :dti_low    AND :dti_high
       AND credit_score BETWEEN :score_low  AND :score_high
     ORDER BY ABS(credit_score - :score_centre), case_id
     FETCH FIRST {MAX_COMPARABLES} ROWS ONLY
"""

_DECISION_HISTORY_SQL = """
    SELECT decision_id, application_id, human_outcome, decided_at,
           agent_recommendation, computed_dti, computed_pti
      FROM BANK_VIEWS.research_v_decision_history
     WHERE customer_id = :customer_id
     ORDER BY decided_at DESC
     FETCH FIRST 20 ROWS ONLY
"""

_TRANSACTIONS_SQL = """
    SELECT txn_date, amount, currency, txn_type, description, balance_after
      FROM BANK_VIEWS.research_v_full_transactions
     WHERE customer_id = :customer_id
     ORDER BY txn_date DESC
     FETCH FIRST 60 ROWS ONLY
"""

_POLICY_CHANGES_SQL = """
    SELECT config_key, old_value, new_value, changed_at, change_reason
      FROM BANK_VIEWS.research_v_policy_parameter_history
     WHERE changed_at >= :since
     ORDER BY changed_at DESC
"""

_NOT_FOUND = {"error": "task_not_found"}


def _task_row(cur, task_id: int) -> dict | None:
    cur.execute(_TASK_SQL, task_id=int(task_id))
    rows = _rows(cur)
    return rows[0] if rows else None


def _echo(task: dict) -> dict:
    """The three fields every tool leads with, so an answer always says which
    case it is about."""
    return {
        "task_id": _i(task["task_id"]),
        "application_id": _i(task["application_id"]),
        "customer_name": task["full_name"],
    }


@mcp.tool()
def recommendation_for_task(task_id: int) -> dict:
    """The case the reviewer is deciding: the agent's recommendation packet and
    the application it was computed for.

    This is the case under review rather than research. The research summary is
    written against it, and the flow's gate tests its result — an unresolvable
    task fails the gate before any model runs.
    """
    started = _now_utc()
    print(f"[recommendation_for_task] called task_id={task_id!r}", flush=True)
    with _connect() as conn:
        with conn.cursor() as cur:
            task = _task_row(cur, task_id)
    if task is None:
        _audit("recommendation_for_task", "FAILED", started, _now_utc(),
               {"task_id": task_id}, _NOT_FOUND, task_id=task_id)
        print("[recommendation_for_task] -> task_not_found", flush=True)
        return _NOT_FOUND
    evidence = json.loads(_clob(task["agent_evidence"]) or "{}")
    out = {
        **_echo(task),
        "tier": task["agent_recommendation"],
        "reasoning": _clob(task["agent_reasoning"]),
        "reason_codes": evidence.get("reason_codes") or [],
        "evidence": evidence,
        "explore_hints": json.loads(_clob(task["agent_explore_hints"]) or "null"),
        "amount": _f(task["amount_requested"]),
        "term_months": _i(task["term_months"]),
        "purpose": task["purpose"],
        "state": task["state"],
    }
    _audit("recommendation_for_task", "SUCCESS", started, _now_utc(),
           {"task_id": task_id}, out, task_id=task_id)
    print(f"[recommendation_for_task] -> tier={out['tier']}", flush=True)
    return out


@mcp.tool()
def similar_cases_for_task(task_id: int) -> dict:
    """Closed cases of comparable size, affordability and credit standing, and
    how each was decided.

    Comparable means a numeric window, not a vector search: `case_history`
    records an outcome and prose, so the bands are the only honest basis. A
    case whose own amount, DTI or score is missing yields no comparables rather
    than a window centred on half the values.
    """
    started = _now_utc()
    print(f"[similar_cases_for_task] called task_id={task_id!r}", flush=True)
    with _connect() as conn:
        with conn.cursor() as cur:
            task = _task_row(cur, task_id)
            if task is None:
                _audit("similar_cases_for_task", "FAILED", started, _now_utc(),
                       {"task_id": task_id}, _NOT_FOUND, task_id=task_id)
                return _NOT_FOUND
            evidence = json.loads(_clob(task["agent_evidence"]) or "{}")
            derived = evidence.get("derived") or {}
            subject = {
                "amount": _f(task["amount_requested"]),
                "dti": _f(derived.get("dti")),
                "credit_score": _i(task["credit_score"]),
            }
            bands = bands_for(subject)
            if bands is None:
                out = {
                    **_echo(task),
                    "comparable": [],
                    "outcome_split": outcome_split([]),
                    "not_matched_on": missing_match_keys(subject),
                }
                _audit("similar_cases_for_task", "SKIPPED", started, _now_utc(),
                       {"task_id": task_id}, out, task_id=task_id)
                print(f"[similar_cases_for_task] -> no bands: {out['not_matched_on']}", flush=True)
                return out
            cur.execute(_SIMILAR_SQL, score_centre=subject["credit_score"], **bands)
            cases = [
                {
                    "amount": _f(r["amount"]),
                    "term_months": _i(r["term_months"]),
                    "dti": _f(r["dti"]),
                    "pti": _f(r["pti"]),
                    "credit_score": _i(r["credit_score"]),
                    "outcome": r["outcome"],
                    "reason": _clob(r["outcome_reason"]),
                }
                for r in _rows(cur)
            ]
    out = {
        **_echo(task),
        "matched_on": {"amount": subject["amount"], "dti": subject["dti"],
                       "credit_score": subject["credit_score"]},
        "bands": bands,
        "comparable": cases,
        "outcome_split": outcome_split(cases),
    }
    _audit("similar_cases_for_task", "SUCCESS", started, _now_utc(),
           {"task_id": task_id}, out, task_id=task_id)
    print(f"[similar_cases_for_task] -> {len(cases)} comparable {out['outcome_split']}", flush=True)
    return out


@mcp.tool()
def decision_history_for_task(task_id: int) -> dict:
    """Every decision this customer has already received, newest first."""
    started = _now_utc()
    print(f"[decision_history_for_task] called task_id={task_id!r}", flush=True)
    with _connect() as conn:
        with conn.cursor() as cur:
            task = _task_row(cur, task_id)
            if task is None:
                _audit("decision_history_for_task", "FAILED", started, _now_utc(),
                       {"task_id": task_id}, _NOT_FOUND, task_id=task_id)
                return _NOT_FOUND
            cur.execute(_DECISION_HISTORY_SQL, customer_id=int(task["customer_id"]))
            decisions = [
                {
                    "application_id": _i(r["application_id"]),
                    "outcome": r["human_outcome"],
                    "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                    "agent_recommendation": r["agent_recommendation"],
                    "dti": _f(r["computed_dti"]),
                    "pti": _f(r["computed_pti"]),
                }
                for r in _rows(cur)
                # The case under review has no decision yet; a row for its own
                # application would be a prior application, not this one.
                if _i(r["application_id"]) != _i(task["application_id"])
            ]
    out = {**_echo(task), "decisions": decisions}
    _audit("decision_history_for_task", "SUCCESS", started, _now_utc(),
           {"task_id": task_id}, out, task_id=task_id)
    print(f"[decision_history_for_task] -> {len(decisions)} prior decision(s)", flush=True)
    return out


@mcp.tool()
def transactions_for_task(task_id: int) -> dict:
    """This customer's transaction detail, newest first.

    The chat path sees a summary; the reviewer sees the ledger. This is the
    clearest example of why the two agents hold different database identities.
    """
    started = _now_utc()
    print(f"[transactions_for_task] called task_id={task_id!r}", flush=True)
    with _connect() as conn:
        with conn.cursor() as cur:
            task = _task_row(cur, task_id)
            if task is None:
                _audit("transactions_for_task", "FAILED", started, _now_utc(),
                       {"task_id": task_id}, _NOT_FOUND, task_id=task_id)
                return _NOT_FOUND
            cur.execute(_TRANSACTIONS_SQL, customer_id=int(task["customer_id"]))
            transactions = [
                {
                    "date": r["txn_date"].isoformat() if r["txn_date"] else None,
                    "amount": _f(r["amount"]),
                    "currency": r["currency"],
                    "type": r["txn_type"],
                    "description": r["description"],
                    "balance_after": _f(r["balance_after"]),
                }
                for r in _rows(cur)
            ]
    out = {**_echo(task), "transactions": transactions}
    _audit("transactions_for_task", "SUCCESS", started, _now_utc(),
           {"task_id": task_id}, out, task_id=task_id)
    print(f"[transactions_for_task] -> {len(transactions)} transaction(s)", flush=True)
    return out


@mcp.tool()
def policy_changes_for_task(task_id: int) -> dict:
    """Policy thresholds that moved since this case was assessed.

    Scoped to the task's own creation time, so the question it answers is "was
    this case judged against the rules in force today" — which is the only
    version of the question a reviewer can act on.
    """
    started = _now_utc()
    print(f"[policy_changes_for_task] called task_id={task_id!r}", flush=True)
    with _connect() as conn:
        with conn.cursor() as cur:
            task = _task_row(cur, task_id)
            if task is None:
                _audit("policy_changes_for_task", "FAILED", started, _now_utc(),
                       {"task_id": task_id}, _NOT_FOUND, task_id=task_id)
                return _NOT_FOUND
            cur.execute(_POLICY_CHANGES_SQL, since=task["created_at"])
            changes = [
                {
                    "parameter": r["config_key"],
                    "from": _clob(r["old_value"]),
                    "to": _clob(r["new_value"]),
                    "changed_at": r["changed_at"].isoformat() if r["changed_at"] else None,
                    "reason": _clob(r["change_reason"]),
                }
                for r in _rows(cur)
            ]
    out = {
        **_echo(task),
        "assessed_at": task["created_at"].isoformat() if task["created_at"] else None,
        "changes": changes,
    }
    _audit("policy_changes_for_task", "SUCCESS", started, _now_utc(),
           {"task_id": task_id}, out, task_id=task_id)
    print(f"[policy_changes_for_task] -> {len(changes)} change(s) since assessment", flush=True)
    return out


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8505"))
    mcp.run(transport="streamable-http", host=host, port=port)
```

- [ ] **Step 3: Verify it imports and the tools register**

`fastmcp` and `oracledb` are not installed on the host, so check syntax only:

Run: `./venv/bin/python -m py_compile src/ai/research-mcp/server.py && echo OK`
Expected: `OK`.

- [ ] **Step 4: Confirm every SQL statement binds and never interpolates**

Run: `grep -n "f\"\"\"" src/ai/research-mcp/server.py`
Expected: exactly one hit — `_SIMILAR_SQL`, whose only interpolation is `MAX_COMPARABLES`, an integer constant from `match.py`. Every value that comes from data is a `:name` bind. If any other f-string appears in a SQL constant, rewrite it as a bind.

- [ ] **Step 5: Commit**

```bash
git add src/ai/research-mcp/
git commit -m "feat(research): read-only MCP surface over the backoffice view set"
```

---

## Task 4: `ResearchSummary.screen` — the no-lean rule

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/research/ResearchSummary.java`
- Test: `src/backend/src/test/java/com/bank/appbackend/research/ResearchSummaryTest.java`

**Interfaces:**

- Produces: `ResearchSummary.screen(String summary) -> String`, `ResearchSummary.verdicts(String summary) -> List<String>`, `ResearchSummary.BLOCKED` (a `String` constant). Task 5 calls `screen` and persists only when the result is unchanged.

- [ ] **Step 1: Write the failing test**

Create `src/backend/src/test/java/com/bank/appbackend/research/ResearchSummaryTest.java`:

```java
package com.bank.appbackend.research;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class ResearchSummaryTest {

    private static final String ORGANISED = """
            The agent recommended REVIEW on credit history.

            SUPPORTS APPROVING
            - 4 comparable cases were approved in the same score band
            - 24 months of stable salary credits

            ARGUES AGAINST
            - 2 comparable cases were declined on affordability
            - 3 large round outflows in the last 30 days

            NOT ESTABLISHED
            - no prior decision for this customer
            - the score floor moved 3 weeks ago
            """;

    @Test
    void anOrganisedSummaryPassesThrough() {
        assertThat(ResearchSummary.screen(ORGANISED)).isEqualTo(ORGANISED);
        assertThat(ResearchSummary.verdicts(ORGANISED)).isEmpty();
    }

    @Test
    void tierNamesAndHeadingsAreNotVerdicts() {
        // The reviewer is bank staff: naming the tier and heading a section
        // "SUPPORTS APPROVING" is the job. Only a conclusion is barred.
        assertThat(ResearchSummary.verdicts("The agent recommended DECLINE.")).isEmpty();
        assertThat(ResearchSummary.verdicts("SUPPORTS APPROVING\n- stable income")).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "On balance, the evidence points to approval.",
            "I recommend approving this application.",
            "My recommendation is to decline.",
            "This should be approved.",
            "It ought to be declined given the outflows.",
            "The evidence leans toward approving.",
            "The case leans towards declining.",
            "The evidence supports approving this case.",
            "You should approve this application.",
    })
    void aVerdictIsRejected(String summary) {
        assertThat(ResearchSummary.verdicts(summary)).isNotEmpty();
        assertThat(ResearchSummary.screen(summary)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @Test
    void aVerdictBuriedInAnOtherwiseGoodSummaryIsStillRejected() {
        String withLean = ORGANISED + "\nON BALANCE\n- I recommend approving.\n";
        assertThat(ResearchSummary.screen(withLean)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @Test
    void anEmptySummaryIsBlocked() {
        // Nothing to show is not the same as nothing to say; the panel must
        // never render an empty research section as though it had run.
        assertThat(ResearchSummary.screen("")).isEqualTo(ResearchSummary.BLOCKED);
        assertThat(ResearchSummary.screen(null)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @Test
    void theBlockedTextNamesNoOutcome() {
        assertThat(ResearchSummary.BLOCKED).doesNotContain("APPROVE", "DECLINE");
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests '*ResearchSummaryTest*'`
Expected: compilation failure — `cannot find symbol: class ResearchSummary`.

- [ ] **Step 3: Write the implementation**

Create `src/backend/src/main/java/com/bank/appbackend/research/ResearchSummary.java`:

```java
package com.bank.appbackend.research;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * The no-lean rule, enforced between the research agent and the reviewer.
 *
 * <p>The rule itself — organise the evidence, name no outcome — is written into
 * the agent's instructions, where it is a request. This class is the rule:
 * every summary passes through {@link #screen} before it is persisted or shown,
 * so one that concludes reaches neither.
 *
 * <p>A summary that endorsed the tier would be a second recommendation beside
 * the deterministic one, composed by a model and grounded in nothing, and it
 * would turn human review into agreement with a machine — the failure mode the
 * human-in-the-loop design exists to prevent.
 *
 * <p>The reviewer is bank staff, so unlike {@link com.bank.appbackend.chat.Disclosure}
 * this bars no vocabulary: tier names, figures, ratios and reason codes all
 * belong in a reviewer's summary. Only a verdict is barred.
 *
 * <p>Pure and free of Spring, so the rules are unit-testable on the host.
 */
public final class ResearchSummary {

    /** Shown when a summary concludes. Names no outcome itself. */
    public static final String BLOCKED =
            "Research could not be completed for this case. The evidence is on this screen; "
            + "the decision is yours to make.";

    private static final List<Rule> VERDICTS = List.of(
            new Rule(Pattern.compile("(?i)\\bI\\s+(recommend|suggest|advise)\\b"), "a recommendation"),
            new Rule(Pattern.compile("(?i)\\bmy\\s+recommendation\\b"), "a recommendation"),
            new Rule(Pattern.compile(
                    "(?i)\\b(should|ought\\s+to)\\s+be\\s+(approved|declined|rejected)\\b"),
                    "a verdict"),
            new Rule(Pattern.compile(
                    "(?i)\\byou\\s+should\\s+(approve|decline|reject)\\b"), "a verdict"),
            new Rule(Pattern.compile("(?i)\\bleans?\\s+towards?\\b"), "a lean"),
            new Rule(Pattern.compile("(?i)\\bon\\s+balance\\b"), "a lean"),
            new Rule(Pattern.compile(
                    "(?i)\\bevidence\\s+(supports|favou?rs|points\\s+to)\\s+"
                            + "(approving|declining|approval|decline|rejection)\\b"),
                    "a lean"),
            new Rule(Pattern.compile(
                    "(?i)\\bpoints\\s+to\\s+(approval|approving|decline|declining)\\b"), "a lean")
    );

    private ResearchSummary() {
    }

    /**
     * The verdict rules this summary breaks, named so a log line records the rule
     * and never the text. Empty means the summary organises without concluding.
     */
    public static List<String> verdicts(String summary) {
        String text = summary == null ? "" : summary;
        List<String> broken = new ArrayList<>();
        for (Rule rule : VERDICTS) {
            if (rule.pattern.matcher(text).find() && !broken.contains(rule.what)) {
                broken.add(rule.what);
            }
        }
        return broken;
    }

    /**
     * The summary as the reviewer may read it: unchanged when it holds to the
     * rule, replaced outright when it does not. Replacing rather than trimming
     * the offending line is deliberate — a summary built toward a conclusion
     * still leans once the conclusion is cut.
     */
    public static String screen(String summary) {
        if (summary == null || summary.isBlank()) {
            return BLOCKED;
        }
        return verdicts(summary).isEmpty() ? summary : BLOCKED;
    }

    private record Rule(Pattern pattern, String what) {
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests '*ResearchSummaryTest*'`
Expected: BUILD SUCCESSFUL.

If `"On balance, the evidence points to approval."` fails, both the `on balance` and the `points to approval` rule should match — the assertion is only that the list is non-empty, so a failure here means a regex typo, not an over-match.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd src/backend && ./gradlew test`
Expected: BUILD SUCCESSFUL, no pre-existing test broken.

- [ ] **Step 6: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/research/ResearchSummary.java \
        src/backend/src/test/java/com/bank/appbackend/research/ResearchSummaryTest.java
git commit -m "feat(research): bar a summary that states an outcome"
```

---

## Task 5: Backend — run, screen, persist, read back

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/research/ResearchPafClient.java`
- Create: `src/backend/src/main/java/com/bank/appbackend/research/ResearchService.java`
- Create: `src/backend/src/main/java/com/bank/appbackend/research/ResearchController.java`
- Create: `src/backend/src/main/java/com/bank/appbackend/audit/ResearchAuditService.java`
- Modify: `src/backend/src/main/java/com/bank/appbackend/audit/AuditController.java`
- Modify: `src/backend/src/main/java/com/bank/appbackend/api/Dtos.java`
- Modify: `src/backend/src/main/resources/application.yaml` (add `paf.research.*`)
- Test: `src/backend/src/test/java/com/bank/appbackend/research/ResearchServiceTest.java`

**Interfaces:**

- Consumes: `ResearchSummary.screen` from Task 4; `BANK_CORE.research_summary` from Task 1; `research-mcp`'s `/v1/audit/research` payload shape from Task 3 (`hitlTaskId`, `toolName`, `status`, `startedAt`, `endedAt`, `toolInput`, `toolOutput`).
- Produces: `ResearchService.run(Long taskId, String reviewer) -> ResearchView`, `ResearchService.latest(Long taskId) -> ResearchView` (null when none). `ResearchView` is `record ResearchView(Long taskId, String summary, String reviewer, Instant createdAt, String researchRunId)`.

- [ ] **Step 1: Add the DTOs**

In `src/backend/src/main/java/com/bank/appbackend/api/Dtos.java`, beside `ToolCallAudit`:

```java
    public record ResearchAudit(Long hitlTaskId, String toolName,
                                String status, Instant startedAt, Instant endedAt,
                                String toolInput, String toolOutput) {
    }

    public record ResearchRequest(String reviewer) {
    }

    public record ResearchView(Long taskId, String summary, String reviewer,
                               Instant createdAt, String researchRunId) {
    }
```

- [ ] **Step 2: Write the failing service test**

Create `src/backend/src/test/java/com/bank/appbackend/research/ResearchServiceTest.java`:

```java
package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchView;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResearchServiceTest {

    private final ResearchPafClient paf = mock(ResearchPafClient.class);
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final ResearchService service = new ResearchService(paf, jdbc);

    private static final String ORGANISED =
            "SUPPORTS APPROVING\n- 4 comparable cases approved\n\nARGUES AGAINST\n- 3 round outflows";

    @Test
    void runEnvelopesTheTaskId() {
        when(paf.run(anyString())).thenReturn(ORGANISED);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        service.run(42L, "Backoffice Reviewer");

        verify(paf).run(eq("[[TASK 42]]"));
    }

    @Test
    void anOrganisedSummaryIsPersistedAndReturned() {
        when(paf.run(anyString())).thenReturn(ORGANISED);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ORGANISED);
        assertThat(view.researchRunId()).isNotBlank();
        verify(jdbc).update(anyString(), eq(7L), eq(42L), eq(view.researchRunId()),
                eq("Backoffice Reviewer"), eq(ORGANISED));
    }

    @Test
    void aSummaryThatConcludesIsNeverPersisted() {
        when(paf.run(anyString())).thenReturn("On balance, I recommend approving this.");
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ResearchSummary.BLOCKED);
        // The ledger is append-only: a rejected summary must never reach it.
        verify(jdbc, never()).update(anyString(), any(), any(), any(), any(), any());
    }

    @Test
    void anUnknownTaskIsNotResearched() {
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(null);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ResearchSummary.BLOCKED);
        verify(paf, never()).run(anyString());
        verify(jdbc, never()).update(anyString(), any(), any(), any(), any(), any());
    }
}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests '*ResearchServiceTest*'`
Expected: compilation failure — `cannot find symbol: class ResearchPafClient`.

- [ ] **Step 4: Write `ResearchPafClient`**

Create `src/backend/src/main/java/com/bank/appbackend/research/ResearchPafClient.java`:

```java
package com.bank.appbackend.research;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

import static org.springframework.http.HttpStatus.BAD_GATEWAY;

/**
 * Runs RESEARCH_WORKFLOW. Separate from {@link com.bank.appbackend.chat.PafClient}
 * because it is bound to a different agent id and a different integration key —
 * which is what makes the routing separation real: a key authorised for the chat
 * agent cannot run the research agent, so the customer path cannot reach it.
 *
 * <p>It shares the {@code pafRestClient} bean, so PAF's certificate is verified
 * on this hop exactly as it is on the chat hop.
 *
 * <p>The response contract differs too: research returns prose, with no markers
 * to strip and no decision to detect.
 */
@Component
public class ResearchPafClient {

    private static final Logger log = LoggerFactory.getLogger(ResearchPafClient.class);
    private static final String RUN_PATH_PREFIX = "/agentFactory/v1/integrations/agents/";
    private static final String RUN_PATH_SUFFIX = "/run";

    private final RestClient http;
    private final String apiKey;
    private final String agentId;
    private final ObjectMapper mapper = new ObjectMapper();

    public ResearchPafClient(RestClient pafRestClient,
                             @Value("${paf.research.api-key:}") String apiKey,
                             @Value("${paf.research.agent-id:}") String agentId) {
        this.http = pafRestClient;
        this.apiKey = apiKey;
        this.agentId = agentId;
    }

    /** The agent's summary text. Throws 502 when PAF cannot be reached or answers with errors. */
    public String run(String envelopedMessage) {
        if (apiKey.isBlank() || agentId.isBlank()) {
            throw new ResponseStatusException(BAD_GATEWAY,
                    "RESEARCH_WORKFLOW is not configured; run `manage.py paf api-key`");
        }
        String body;
        try {
            body = http.post()
                    .uri(RUN_PATH_PREFIX + agentId + RUN_PATH_SUFFIX)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("message", envelopedMessage))
                    .retrieve()
                    .body(String.class);
        } catch (RestClientException e) {
            log.warn("PAF research run failed (agentId={})", agentId, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF research run failed", e);
        }
        JsonNode root;
        try {
            root = mapper.readTree(body);
        } catch (Exception e) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF response not JSON", e);
        }
        JsonNode errs = root.path("errorMessages");
        if (errs.isArray() && !errs.isEmpty()) {
            log.warn("PAF returned errorMessages (agentId={}): {}", agentId, errs);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF returned errors: " + errs);
        }
        try {
            return com.bank.appbackend.chat.Envelope.extractRawReply(root);
        } catch (IllegalStateException e) {
            log.warn("PAF research reply shape not recognized (agentId={}): {}", agentId, body, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF reply shape not recognized", e);
        }
    }
}
```

Before using `Envelope.extractRawReply`, open `src/backend/src/main/java/com/bank/appbackend/chat/Envelope.java` and confirm the method is `public static` and returns `String` given a `JsonNode`. If it is package-private, widen it to `public` — it is the one piece of reply-shape knowledge both flows share, and duplicating it would mean two places to fix when PAF changes its envelope.

- [ ] **Step 5: Write `ResearchService`**

Create `src/backend/src/main/java/com/bank/appbackend/research/ResearchService.java`:

```java
package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchView;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Runs the research agent for one review task and records what it produced.
 *
 * <p>The summary reaches the reviewer and the ledger only through
 * {@link ResearchSummary#screen}, so a summary that states an outcome is shown
 * to nobody and stored nowhere. The ledger is append-only: there is no second
 * chance to remove a row, which is why the screen runs before the insert.
 */
@Service
public class ResearchService {

    private static final Logger log = LoggerFactory.getLogger(ResearchService.class);

    private final ResearchPafClient paf;
    private final JdbcTemplate jdbc;

    public ResearchService(ResearchPafClient paf, JdbcTemplate jdbc) {
        this.paf = paf;
        this.jdbc = jdbc;
    }

    /** Run research for a task and append the result. Never throws for a bad task id. */
    public ResearchView run(Long taskId, String reviewer) {
        String who = (reviewer == null || reviewer.isBlank()) ? "Backoffice Reviewer" : reviewer.trim();
        Long applicationId = applicationFor(taskId);
        if (applicationId == null) {
            log.warn("research requested for unknown task {}", taskId);
            return new ResearchView(taskId, ResearchSummary.BLOCKED, who, Instant.now(), null);
        }
        String runId = UUID.randomUUID().toString();
        // The task id is the flow's only input, and PAF accepts no input beyond
        // the chat message, so it travels in-band exactly as the session token
        // does on the customer path.
        String raw = paf.run("[[TASK " + taskId + "]]");
        String shown = ResearchSummary.screen(raw);
        if (!shown.equals(raw)) {
            // Name the rule, never the text that broke it.
            log.warn("research run {} for task {} stated an outcome: {}",
                    runId, taskId, ResearchSummary.verdicts(raw));
            return new ResearchView(taskId, shown, who, Instant.now(), null);
        }
        jdbc.update("""
                INSERT INTO BANK_CORE.research_summary
                    (application_id, hitl_task_id, research_run_id, reviewer, summary)
                VALUES (?, ?, ?, ?, ?)
                """, applicationId, taskId, runId, who, shown);
        log.info("research run {} recorded for task {}", runId, taskId);
        return new ResearchView(taskId, shown, who, Instant.now(), runId);
    }

    /** The most recent recorded summary for a task, or null when none was ever run. */
    public ResearchView latest(Long taskId) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT summary, reviewer, created_at, research_run_id
                  FROM BANK_CORE.research_summary
                 WHERE hitl_task_id = ?
                 ORDER BY research_id DESC
                 FETCH FIRST 1 ROW ONLY
                """, taskId);
        if (rows.isEmpty()) {
            return null;
        }
        Map<String, Object> row = rows.get(0);
        Timestamp created = (Timestamp) row.get("CREATED_AT");
        return new ResearchView(taskId, String.valueOf(row.get("SUMMARY")),
                String.valueOf(row.get("REVIEWER")),
                created == null ? null : created.toInstant(),
                String.valueOf(row.get("RESEARCH_RUN_ID")));
    }

    private Long applicationFor(Long taskId) {
        try {
            return jdbc.queryForObject(
                    "SELECT application_id FROM BANK_CORE.hitl_task WHERE task_id = ?",
                    Long.class, taskId);
        } catch (RuntimeException e) {
            return null;
        }
    }
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests '*ResearchServiceTest*'`
Expected: BUILD SUCCESSFUL, 4 tests.

`JdbcTemplate.queryForObject(String, Class<T>, Object...)` is a varargs method, and Mockito matches varargs one element at a time. If the stub returns null where 7L was expected, change `any()` to `any(Object[].class)` in the `queryForObject` stubbing — the behaviour under test is unchanged either way.

- [ ] **Step 7: Write the controller**

Create `src/backend/src/main/java/com/bank/appbackend/research/ResearchController.java`:

```java
package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchRequest;
import com.bank.appbackend.api.Dtos.ResearchView;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** The reviewer's research surface. Backoffice only — the customer path holds no key for it. */
@RestController
@RequestMapping("/v1/research")
public class ResearchController {

    private final ResearchService service;

    public ResearchController(ResearchService service) {
        this.service = service;
    }

    @PostMapping("/tasks/{taskId}/run")
    public ResearchView run(@PathVariable Long taskId, @RequestBody ResearchRequest request) {
        return service.run(taskId, request.reviewer());
    }

    /** The stored summary, so reopening a case does not re-run the agent. 204 when none. */
    @GetMapping("/tasks/{taskId}")
    public ResponseEntity<ResearchView> latest(@PathVariable Long taskId) {
        ResearchView view = service.latest(taskId);
        return view == null ? ResponseEntity.noContent().build() : ResponseEntity.ok(view);
    }
}
```

- [ ] **Step 8: Write the research audit collector**

Create `src/backend/src/main/java/com/bank/appbackend/audit/ResearchAuditService.java`:

```java
package com.bank.appbackend.audit;

import com.bank.appbackend.api.Dtos.ResearchAudit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;

/**
 * Collects the per-tool research trail posted by research-mcp and writes it to
 * BANK_CORE.research_audit, which is kept separate from decision_audit so a
 * reviewer's research never pollutes the decisioning trail.
 *
 * <p>The wrapper holds no write grant, so this is the only path to the table.
 * Best-effort: a failure here never breaks a live research run.
 */
@Service
public class ResearchAuditService {

    private static final Logger log = LoggerFactory.getLogger(ResearchAuditService.class);

    private final JdbcTemplate jdbc;

    public ResearchAuditService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void record(ResearchAudit req) {
        try {
            if (req.hitlTaskId() == null) {
                log.warn("research audit skipped: no task id (tool={})", req.toolName());
                return;
            }
            Long durationMs = (req.startedAt() != null && req.endedAt() != null)
                    ? Duration.between(req.startedAt(), req.endedAt()).toMillis()
                    : null;
            Integer stepNo = jdbc.queryForObject(
                    "SELECT NVL(MAX(step_no), 0) + 1 FROM BANK_CORE.research_audit WHERE hitl_task_id = ?",
                    Integer.class, req.hitlTaskId());
            jdbc.update("""
                    INSERT INTO BANK_CORE.research_audit
                        (research_run_id, hitl_task_id, reviewer, step_no, tool_name,
                         tool_input, tool_output, started_at, ended_at, duration_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    "task-" + req.hitlTaskId(), req.hitlTaskId(), "Backoffice Reviewer",
                    stepNo, req.toolName(), req.toolInput(), req.toolOutput(),
                    toTimestamp(req.startedAt()), toTimestamp(req.endedAt()), durationMs,
                    req.status() == null ? "SUCCESS" : req.status());
        } catch (RuntimeException e) {
            log.warn("research audit write failed (tool={})", req.toolName(), e);
        }
    }

    private static Timestamp toTimestamp(Instant i) {
        return i == null ? null : Timestamp.from(i);
    }
}
```

- [ ] **Step 9: Add the audit mapping**

In `src/backend/src/main/java/com/bank/appbackend/audit/AuditController.java`, add the second service to the constructor and this mapping:

```java
    @PostMapping("/research")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void research(@RequestBody ResearchAudit req) {
        researchService.record(req);
    }
```

Import `com.bank.appbackend.api.Dtos.ResearchAudit` and `ResearchAuditService`; update the class javadoc to say it collects both trails.

- [ ] **Step 10: Add the configuration properties**

In `src/backend/src/main/resources/application.yaml`, under the existing `paf:` block, add:

```yaml
research:
  agent-id: ${PAF_RESEARCH_AGENT_ID:}
  api-key: ${PAF_RESEARCH_API_KEY:}
```

Read the existing `paf:` block first and match its indentation and placeholder style exactly.

- [ ] **Step 11: Run the whole backend suite**

Run: `cd src/backend && ./gradlew test`
Expected: BUILD SUCCESSFUL. Confirm the count grew by the new tests and nothing regressed.

- [ ] **Step 12: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/research/ \
        src/backend/src/main/java/com/bank/appbackend/audit/ \
        src/backend/src/main/java/com/bank/appbackend/api/Dtos.java \
        src/backend/src/main/resources/application.yaml \
        src/backend/src/test/java/com/bank/appbackend/research/
git commit -m "feat(research): run the agent, screen the summary, append the ledger row"
```

---

## Task 6: Reviewer panel

**Files:**

- Create: `src/backoffice-ui/src/components/backoffice/ResearchPanel.tsx`
- Create: `src/backoffice-ui/src/components/backoffice/researchPanel.test.ts`
- Modify: `src/backoffice-ui/src/api.ts`
- Modify: `src/backoffice-ui/src/components/backoffice/TaskDetail.tsx`
- Modify: `src/backoffice-ui/package.json` (only if no `test` script resolves — see Step 1)

**Interfaces:**

- Consumes: `POST /v1/research/tasks/{taskId}/run` and `GET /v1/research/tasks/{taskId}` from Task 5, returning `ResearchView`.
- Produces: `<ResearchPanel taskId={number} reviewer={string} />`, and the pure helper `researchState(view, busy) -> "idle" | "running" | "ready"` that the test drives.

- [ ] **Step 1: Confirm the test runner picks up a test file here**

`src/backoffice-ui` currently reports "No test files found". Run:

```bash
cd src/backoffice-ui && cat package.json | grep -A3 '"scripts"' && grep -rn "include" vite.config.* vitest.config.* 2>/dev/null
```

The vitest include pattern is `src/**/*.test.ts`. Name the new test file `researchPanel.test.ts` (not `.tsx`) so it matches, and keep the tested logic in plain TypeScript.

- [ ] **Step 2: Write the failing test**

Create `src/backoffice-ui/src/components/backoffice/researchPanel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { researchState, type ResearchView } from "./ResearchPanel";

const view: ResearchView = {
  taskId: 42,
  summary: "SUPPORTS APPROVING\n- 4 comparable cases approved",
  reviewer: "Backoffice Reviewer",
  createdAt: "2026-09-21T10:00:00Z",
  researchRunId: "r-1",
};

describe("researchState", () => {
  it("is idle before anything has been run", () => {
    expect(researchState(null, false)).toBe("idle");
  });

  it("is running while the agent is working", () => {
    expect(researchState(null, true)).toBe("running");
  });

  it("is ready once a summary exists", () => {
    // A stored summary renders on load; the reviewer never re-runs to read it.
    expect(researchState(view, false)).toBe("ready");
  });

  it("stays running when a re-run is in flight over an existing summary", () => {
    expect(researchState(view, true)).toBe("running");
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd src/backoffice-ui && npm test`
Expected: FAIL — cannot resolve `./ResearchPanel`.

- [ ] **Step 4: Add the API calls**

In `src/backoffice-ui/src/api.ts`, following the shape of the existing `getHitlTask` / `decideHitlTask`:

```ts
export interface ResearchView {
  taskId: number;
  summary: string;
  reviewer: string;
  createdAt: string | null;
  researchRunId: string | null;
}

/** The stored summary for a task, or null when research has never been run. */
export async function getResearch(
  taskId: number,
): Promise<ResearchView | null> {
  const r = await fetch(`/v1/research/tasks/${taskId}`);
  if (r.status === 204) return null;
  return json<ResearchView>(r);
}

export function runResearch(
  taskId: number,
  reviewer: string,
): Promise<ResearchView> {
  return fetch(`/v1/research/tasks/${taskId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer }),
  }).then((r) => json<ResearchView>(r));
}
```

Read the file first and reuse its existing `json<T>` helper and error handling rather than introducing a second style.

- [ ] **Step 5: Write the panel**

Create `src/backoffice-ui/src/components/backoffice/ResearchPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getResearch, runResearch, type ResearchView } from "@/api";
import { Button } from "@/components/ui/button";

export type { ResearchView };

/** What the panel shows. A stored summary renders on load; a run in flight wins. */
export function researchState(
  view: ResearchView | null,
  busy: boolean,
): "idle" | "running" | "ready" {
  if (busy) return "running";
  return view ? "ready" : "idle";
}

export function ResearchPanel({
  taskId,
  reviewer,
}: {
  taskId: number;
  reviewer: string;
}) {
  const [view, setView] = useState<ResearchView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getResearch(taskId)
      .then(setView)
      .catch(() => setError("Could not load earlier research."));
  }, [taskId]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setView(await runResearch(taskId, reviewer));
    } catch {
      setError("Research could not be run. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const state = researchState(view, busy);

  return (
    <section className="rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Case research</h3>
        <Button onClick={run} disabled={busy}>
          {state === "running"
            ? "Researching…"
            : state === "ready"
              ? "Run again"
              : "Run research"}
        </Button>
      </div>

      {state === "idle" && (
        <p className="mt-2 text-sm text-muted-foreground">
          Gathers comparable closed cases, this customer's decision history,
          their full transactions and any policy changes since this case was
          assessed. The decision stays yours.
        </p>
      )}

      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}

      {state === "ready" && view && (
        <>
          <pre className="mt-3 whitespace-pre-wrap text-sm">{view.summary}</pre>
          <p className="mt-2 text-xs text-muted-foreground">
            Run by {view.reviewer}
            {view.createdAt
              ? ` · ${new Date(view.createdAt).toLocaleString()}`
              : ""}
          </p>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd src/backoffice-ui && npm test`
Expected: 4 passed.

- [ ] **Step 7: Mount the panel**

In `src/backoffice-ui/src/components/backoffice/TaskDetail.tsx`, import `ResearchPanel` and render it immediately after `<EvidencePanel raw={task.agentEvidence} />` (line ~96):

```tsx
<ResearchPanel taskId={taskId} reviewer={REVIEWER} />
```

`REVIEWER` is already defined at the top of that file.

- [ ] **Step 8: Verify the build**

Run: `cd src/backoffice-ui && npm run build`
Expected: no TypeScript errors.

- [ ] **Step 9: Commit**

```bash
git add src/backoffice-ui/src/
git commit -m "feat(backoffice): case research panel on the task detail screen"
```

---

## Task 7: Deployment

**Files:**

- Modify: `deploy/ansible/backend/roles/appstack/defaults/main.yaml:13-14` (add a third server)
- Modify: `deploy/ansible/backend/roles/appstack/tasks/main.yaml:184` (firewall loop)
- Modify: `manage.py` (`_discover_chat_flow_id`, `link-flow`, `api-key`, `push-key`, `info`, `paf bootstrap`)
- Modify: `deploy/tf/app/` internal load balancer backend set for 8505
- Modify: `CLOUD.md` (new §10)
- Modify: `.env.example` if one exists, and `manage.py setup`'s writer

**Interfaces:**

- Consumes: `research-mcp` from Task 3, `paf.research.*` from Task 5.
- Produces: `.env` keys `PAF_RESEARCH_AGENT_ID`, `PAF_RESEARCH_API_KEY`; `research-mcp` serving on 8505 on the backend tier.

- [ ] **Step 1: Add the server to the Ansible role**

In `deploy/ansible/backend/roles/appstack/defaults/main.yaml`, after line 14:

```yaml
- {
    name: research-mcp,
    port: 8505,
    db_user: BACKOFFICE_AGENT_RO,
    db_password_var: db_backoffice_ro_password,
  }
```

Confirm `db_backoffice_ro_password` is the variable name Terraform already renders — grep the role and `deploy/tf/app/` for the existing backoffice password variable and use that exact name. If it is not yet plumbed to this tier, add it beside the two customer passwords, following their pattern in the same files.

- [ ] **Step 2: Open the port**

In `deploy/ansible/backend/roles/appstack/tasks/main.yaml:184`, change:

```yaml
loop: [8090, 8600, 8503, 8504]
```

to:

```yaml
loop: [8090, 8600, 8503, 8504, 8505]
```

- [ ] **Step 3: Add the load balancer backend set**

Grep `deploy/tf/app/` for `8504` and replicate every resource that mentions it for `8505` — backend set, backend, listener — using the same naming convention with `research` in place of `application`.

- [ ] **Step 4: Generalise the flow lookup in `manage.py`**

Replace `_discover_chat_flow_id` (`manage.py:289`) with a name-taking version, keeping a thin wrapper so existing call sites are untouched:

```python
def _discover_flow_id(session: requests.Session, flow_name: str) -> str:
    """Resolve a flow's agent id by name."""
    r = session.get(f"{_paf_base_url()}/agentFactory/v1/agents", timeout=30)
    if r.status_code != 200:
        console.print(f"[red]Could not list agents: HTTP {r.status_code}.[/red]\n{r.text[:300]}")
        sys.exit(1)
    body = r.json()
    data = body.get("data") if isinstance(body, dict) else body
    agents = data.get("items", []) if isinstance(data, dict) else data
    for agent in agents or []:
        if agent.get("name") == flow_name:
            agent_id = agent.get("agentId") or agent.get("agent_id")
            if agent_id:
                return str(agent_id)
    console.print(
        f"[red]{flow_name} not found in PAF's agent list.[/red] "
        f"Import and publish it per paf/flows/{flow_name}.md."
    )
    sys.exit(1)


def _discover_chat_flow_id(session: requests.Session) -> str:
    return _discover_flow_id(session, "CHAT_FLOW")
```

- [ ] **Step 5: Teach the PAF commands about the second flow**

Read each of `paf link-flow` (~line 1744), `paf api-key` (~1862), `paf push-key` (~2032) and `info` (~920), and add the research flow beside the chat flow in each:

- `link-flow` — iterate both flow names, rebinding MCP nodes in each; `research-mcp` is the server `RESEARCH_WORKFLOW`'s nodes bind to.
- `api-key` — mint a key for `RESEARCH_WORKFLOW` as well, writing `PAF_RESEARCH_AGENT_ID` and `PAF_RESEARCH_API_KEY` into `.env` beside the existing pair.
- `push-key` — deliver both keys and the certificate to the backend tier in one pass.
- `info` — a readiness line for `RESEARCH_WORKFLOW` matching the existing `CHAT_FLOW` one (imported / key minted / backend has it).
- `paf bootstrap` — add `research-mcp` to the MCP server registration step and a `RESEARCH_WORKFLOW` import/publish step.

Follow each command's existing structure rather than adding a parallel code path; where a literal `"CHAT_FLOW"` appears, make it a loop over both names.

- [ ] **Step 6: Write `CLOUD.md §10`**

Add a section mirroring §9 — import `RESEARCH_WORKFLOW.paf` with password `WelcomeAmigo123!`, run `paf link-flow`, publish, run `paf api-key`, then `paf push-key`. Any step that is not part of a deployment from scratch goes in a `>` blockquote opening with the condition that excuses the reader.

- [ ] **Step 7: Build and stage**

Run: `python manage.py build`
Expected: `✓ Staged every tier payload`.

Run: `ls deploy/ansible/backend/roles/appstack/files/mcp/`
Expected: `banking-mcp`, `application-mcp`, `research-mcp`.

- [ ] **Step 8: Commit**

```bash
git add deploy/ manage.py CLOUD.md
git commit -m "feat(deploy): serve research-mcp and manage the second flow"
```

---

## Task 8: The canvas blueprint

**Files:**

- Create: `paf/flows/RESEARCH_WORKFLOW.md`

**Interfaces:**

- Consumes: the tool names and return shapes from Task 3; the flow graph from the spec's §2.
- Produces: the document Task 11 is built from.

- [ ] **Step 1: Read the model document end to end**

Read `paf/flows/CHAT_FLOW.md` in full. The new blueprint carries the same sections in the same order: intro, purpose, flow inputs, node graph, the tool table, build sequence (one step per node), wiring checklist, test prompts, import/export, operating constraints.

- [ ] **Step 2: Write the blueprint**

Create `paf/flows/RESEARCH_WORKFLOW.md` with these fourteen build steps, each in `CHAT_FLOW.md`'s format (drag / configure / wire, with a mermaid wiring diagram per step):

1. **Chat input** — receives `[[TASK <id>]]`.
2. **Task id extractor** (`Regex extractor`), pattern `(?<=\[\[TASK )[0-9]+`.
3. **Prompt (JSON-wrap)** — template `{"task_id":{{task_id}}}`, then **Save prompt**. Note: no quotes around the placeholder — the tools take an integer.
4. **Type Convert** — bridges Message → JSON.
5. **Deterministic MCP** — server `research-mcp`, tool `recommendation_for_task`.
6. **Deterministic MCP** — `similar_cases_for_task`.
7. **Deterministic MCP** — `decision_history_for_task`.
8. **Deterministic MCP** — `transactions_for_task`.
9. **Deterministic MCP** — `policy_changes_for_task`.
10. **Condition G0** — `Text Input` and `True Message` both from `recommendation_for_task`.`Message`; Operator `Regex match`; `Match Text` the **bare word** `tier` (a Deterministic MCP node escapes its inner quotes, so a quoted key matches nothing, and an unresolvable task returns `{"error":"task_not_found"}` which has no `tier`). `False Message` typed inline: `Research could not be completed for this case.`
11. **Chat output (unavailable)** — closes G0 `False`, `Message` left empty.
12. **Prompt (research)** — five ports, template below, then **Save prompt**.
13. **Agent** — LLM `gen-model`, temperature `0.01`, `Agent description` `Research`, **no MCP node wired**, Custom Instructions below.
14. **Chat output (summary)** — closes G0 `True` path via the agent; `Message` left empty.

The Prompt (research) template:

```
You are preparing a case file for a bank reviewer who is about to decide this
loan application.

The recommendation under review (AUTHORITATIVE — server-computed): {{recommendation}}
Comparable closed cases (AUTHORITATIVE): {{similar}}
This customer's earlier decisions (AUTHORITATIVE): {{history}}
This customer's transactions (AUTHORITATIVE): {{transactions}}
Policy changes since this case was assessed (AUTHORITATIVE): {{policy}}
```

Wire: G0's `True` output → `recommendation` (it both sequences the step and delivers the packet); `similar_cases_for_task`.`Message` → `similar`; `decision_history_for_task`.`Message` → `history`; `transactions_for_task`.`Message` → `transactions`; `policy_changes_for_task`.`Message` → `policy`.

The Agent's Custom Instructions — **no `{{placeholder}}` anywhere**, or the node fails validation (`issues/11`):

```
You prepare a case file for a bank reviewer who is about to approve or decline
a loan application. You hold no tools. Everything you need is in your prompt,
all of it server-computed and authoritative: the recommendation under review,
comparable closed cases, this customer's earlier decisions, their transactions,
and any policy changes since this case was assessed.

YOU DO NOT DECIDE, AND YOU DO NOT LEAN. The reviewer decides. Your job is to
put the evidence in front of them organised, so the decision is quicker to make
and harder to make carelessly.

Write exactly these four sections, in this order, with these headings:

THE CASE
  One sentence: the tier the agent recommended and what it turned on. Take both
  from the recommendation in your prompt; never restate the full packet, the
  reviewer is looking at it.

SUPPORTS APPROVING
  Bullets. Only facts from your prompt. Name the source of each one — how many
  comparable cases were approved, what the transaction record shows, what an
  earlier decision established.

ARGUES AGAINST
  Bullets, the same way.

NOT ESTABLISHED
  Bullets: what the evidence does not settle. An empty comparable set, no prior
  decision, a policy threshold that moved after this case was assessed. This
  section is why the reviewer still has to think.

RULES:
- Never say what the outcome should be. No recommendation, no lean, no "on
  balance", no "the evidence supports approving". A summary that concludes is
  rejected before the reviewer sees it and the run is wasted.
- Every bullet is a fact from your prompt. If a section has nothing, write
  "nothing on the record" under it rather than inventing a bullet.
- Figures, ratios, reason codes and tier names are all fine here — the reader
  is bank staff, not the customer.
- Plain text. No JSON, no braces, no markdown tables.
```

- [ ] **Step 3: Write the wiring checklist**

Produce the source-port → target-port table covering all fourteen nodes, in the format of `CHAT_FLOW.md`'s. Every edge created in Steps 1–14 appears exactly once.

- [ ] **Step 4: Write the test prompts section**

Include the SQL for finding a `REVIEW` task to test against:

```sql
SELECT t.task_id, c.full_name, t.agent_recommendation
  FROM BANK_CORE.hitl_task t
  JOIN BANK_CORE.loan_application la ON la.application_id = t.application_id
  JOIN BANK_CORE.customer c ON c.customer_id = la.customer_id
 WHERE t.state <> 'CLOSED'
 ORDER BY t.task_id DESC;
```

Playground input is `[[TASK <id>]]`. Trace expectation: five deterministic nodes run once each, the agent makes **zero** tool calls. A bare message with no `[[TASK ...]]` yields no id, `recommendation_for_task` returns `task_not_found`, G0 fails, and the unavailable output fires with no row written.

- [ ] **Step 5: Write the import/export and operating-constraints sections**

Import/export mirrors `CHAT_FLOW.md`'s, with `RESEARCH_WORKFLOW.paf` and the same password. State that portable Agent Spec export fails here too, for the same reason (`issues/13`) — the `Regex extractor` is a runtime tool.

Operating constraints must record: the agent holds no tools so `issues/01` does not apply; `BACKOFFICE_AGENT_RO` has no `EXECUTE` and no write grant, so no path through this flow can change anything; the summary passes `ResearchSummary.screen` in the backend, which is where the no-lean rule is enforced rather than requested.

- [ ] **Step 6: Commit**

```bash
git add paf/flows/RESEARCH_WORKFLOW.md
git commit -m "docs(flow): blueprint for the backoffice research workflow"
```

---

## Task 9: End-to-end test

**Files:**

- Create: `tests/test_research_workflow.py`
- Modify: `tests/conftest.py` (add a `research` fixture)
- Modify: whatever `manage.py cloud test` ships to the bastion, so the new file goes with it

**Interfaces:**

- Consumes: the backend endpoints from Task 5; the `db` fixture from `tests/conftest.py`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Add the fixture**

In `tests/conftest.py`, beside the existing `chat` fixture:

```python
@pytest.fixture
def research(env):
    """POST /v1/research/tasks/<id>/run against the deployed backend."""
    def _run(task_id: int, reviewer: str = "Backoffice Reviewer") -> dict:
        r = requests.post(
            f"{env['BACKEND_URL']}/v1/research/tasks/{task_id}/run",
            json={"reviewer": reviewer},
            timeout=300,
            verify=env.get("LB_CA_BUNDLE", True),
        )
        r.raise_for_status()
        return r.json()
    return _run
```

Read the `chat` fixture first and match how it reads the backend URL and TLS bundle out of `env` — reuse those keys rather than inventing names.

- [ ] **Step 2: Write the test**

Create `tests/test_research_workflow.py`:

```python
"""End-to-end tests for RESEARCH_WORKFLOW.

Needs the deployed backend, PAF and the private-endpoint ADB, so it runs on the
bastion through `python manage.py cloud test`, never from the host.

Each test resolves its task by querying for an open one — IDENTITY values are
non-contiguous and are never hardcoded.
"""
from __future__ import annotations

import pytest

# The four headings the agent is instructed to produce.
SECTIONS = ("THE CASE", "SUPPORTS APPROVING", "ARGUES AGAINST", "NOT ESTABLISHED")

# What a summary may never contain. The backend screen enforces this; the test
# asserts the property end to end rather than trusting the prompt.
VERDICTS = ("i recommend", "my recommendation", "on balance",
            "should be approved", "should be declined", "leans toward",
            "leans towards")


@pytest.fixture
def open_review_task(db):
    """The newest task still awaiting a human decision."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT task_id, application_id
              FROM BANK_CORE.hitl_task
             WHERE state <> 'CLOSED'
             ORDER BY task_id DESC
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
    import requests
    task_id = open_review_task["task_id"]
    written = research(task_id)
    r = requests.get(
        f"{env['BACKEND_URL']}/v1/research/tasks/{task_id}",
        timeout=30,
        verify=env.get("LB_CA_BUNDLE", True),
    )
    r.raise_for_status()
    assert r.json()["researchRunId"] == written["researchRunId"]
```

- [ ] **Step 3: Ship the file to the bastion**

Grep `manage.py` for `test_chat_workflow.py` and for how `cloud test` selects files to upload. If it copies the whole `tests/` tree, nothing to do; if it names files, add `test_research_workflow.py` beside the existing entry.

- [ ] **Step 4: Confirm the host suite is unaffected**

Run: `./venv/bin/python -m pytest tests/unit -q`
Expected: all pass. `tests/test_research_workflow.py` must not be collected here — confirm `pytest.ini` scopes `tests/unit` as it already does for `test_chat_workflow.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_workflow.py tests/conftest.py manage.py
git commit -m "test(research): end-to-end cover for the research run and its ledger"
```

---

## Task 10: Docs and backlog

**Files:**

- Modify: `docs/DESIGN.md` (§5 endpoints, §6.3 flow shape, §8 step 12, §9 audit, §11 decisions)
- Modify: `README.md` (what's next list)
- Modify: `BACKLOG.md` (remove §3 and §8, renumber, fix cross-references)
- Modify: `CLAUDE.md` ("Where to look" table)
- Delete: nothing in `issues/`

**Interfaces:** none.

- [ ] **Step 1: Update `docs/DESIGN.md`**

- §5: `/research/*` is implemented — describe `POST /v1/research/tasks/{taskId}/run` and `GET /v1/research/tasks/{taskId}`.
- §6.3: replace the Select AI Bridge description of `RESEARCH_WORKFLOW` with the built shape — five deterministic `research-mcp` nodes, an Agent node with no tools, `BACKOFFICE_AGENT_RO`.
- §8 step 12: the reviewer may run research from the task detail screen, and the summary is appended to `BANK_CORE.research_summary`.
- §9: `research_audit` has a writer, and `research_summary` joins the audit inventory.
- §11: record the decision — a read-only MCP wrapper rather than the Select AI Bridge, because it carries the same read scope without waiting on the policy corpus or Select AI adoption.

Present tense, final state, no account of how it used to be described.

- [ ] **Step 2: Update `README.md`**

Remove the `RESEARCH_WORKFLOW` item from the "what's next" list, renumber the remaining items, and correct every `BACKLOG.md §N` link to match the renumbered backlog from Step 3. Add `RESEARCH_WORKFLOW` to the architecture description beside `CHAT_FLOW`.

- [ ] **Step 3: Update `BACKLOG.md`**

Delete §3 (`RESEARCH_WORKFLOW`) and §8 (similar-case lookup) — both are done. Renumber the remaining sections so the sequence is contiguous, then fix every internal `§N` reference and every `BACKLOG.md §N` reference in `README.md`, `docs/DESIGN.md`, `docs/DEPLOYMENT.md` and `database/liquibase/020-client-grants.yaml`.

Verify with:

```bash
grep -rn "BACKLOG.md §" --exclude-dir=.git --exclude-dir=venv --exclude-dir=node_modules --exclude-dir=paf-kit .
grep -n "^## [0-9]" BACKLOG.md
```

Every reference must resolve to the section it names.

- [ ] **Step 4: Update `CLAUDE.md`**

Add `paf/flows/RESEARCH_WORKFLOW.md` to the "Where to look" table, and note the third database identity's flow beside the `CHAT_FLOW` description.

- [ ] **Step 5: Commit**

```bash
git add docs/ README.md BACKLOG.md CLAUDE.md
git commit -m "docs: record the research workflow and close its backlog items"
```

---

## Task 11: Deploy, build, publish, verify (human)

This task is yours — the canvas cannot be built until `research-mcp` is running and registered, because the `Deterministic MCP tool` node lists only tools PAF has discovered from a live server.

- [ ] **Step 1: Ship the code**

```bash
python manage.py build
python manage.py cloud redeploy ops        # Liquibase 027 and the new grant
python manage.py cloud redeploy backend    # research-mcp, the Spring changes
python manage.py info
```

Expected: `info` shows the backend tier ready. If the load balancer backend set for 8505 was added in Task 7 Step 3, a rebuild rather than a redeploy may be needed — Terraform variables are rendered into cloud-init at instance creation.

- [ ] **Step 2: Register the server in PAF**

`paf bootstrap` prints the sheet; register `research-mcp` as an MCP server alongside the other two, using the internal load balancer address and port 8505. Confirm PAF discovers all five tools.

- [ ] **Step 3: Build the flow**

Follow `paf/flows/RESEARCH_WORKFLOW.md` step by step on the canvas. Fourteen nodes.

- [ ] **Step 4: Link and publish**

```bash
python manage.py paf link-flow
```

Then publish `RESEARCH_WORKFLOW` in Agent Builder.

- [ ] **Step 5: Mint and deliver the key**

```bash
python manage.py paf api-key
python manage.py paf push-key
python manage.py info
```

Expected: `info` reports `RESEARCH_WORKFLOW` imported, key minted, and the backend holding it.

- [ ] **Step 6: Run the end-to-end suite**

```bash
python manage.py cloud test
```

Expected: the existing chat scenarios still pass, and all six research tests pass.

If `test_every_deterministic_node_leaves_an_audit_row` fails with fewer than five tools, check the backend's `/v1/audit/research` logs — the wrapper's audit is fire-and-forget and swallows its own failures, so a missing row means the POST never landed, not that the node never ran.

- [ ] **Step 7: Export the bundle**

Export the flow from Agent Builder with the bundle password `WelcomeAmigo123!`, save it as `paf/flows/RESEARCH_WORKFLOW.paf`, and commit it together with any blueprint correction the build turned up.

```bash
git add paf/flows/RESEARCH_WORKFLOW.paf paf/flows/RESEARCH_WORKFLOW.md
git commit -m "flow: export the research workflow bundle"
```

A bundle that disagrees with its blueprint is worse than no bundle — if the canvas differed from the document anywhere, fix the document in the same commit.
