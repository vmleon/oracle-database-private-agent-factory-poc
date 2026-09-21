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


def _json(value, default):
    """Decode a JSON-column value that oracledb may hand back as an already
    materialized dict/list, or as a LOB/str that still needs json.loads."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    text = _clob(value)
    return json.loads(text) if text else default


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
            evidence = _json(task["agent_evidence"], {})
            reasoning = _clob(task["agent_reasoning"])
            explore_hints = _json(task["agent_explore_hints"], None)
    out = {
        **_echo(task),
        "tier": task["agent_recommendation"],
        "reasoning": reasoning,
        "reason_codes": evidence.get("reason_codes") or [],
        "evidence": evidence,
        "explore_hints": explore_hints,
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
            evidence = _json(task["agent_evidence"], {})
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
