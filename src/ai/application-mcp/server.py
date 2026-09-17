"""application-mcp — CHAT_FLOW's write surface.

Two tools, one per worker:
  - upsert_application(session_token, amount?, term_months?, purpose?) — the
    Intake worker's tool. Creates the customer's DRAFT loan application on
    first call and patches supplied fields after.
  - create_hitl_task(session_token, explore_hints?) — the Recommendation
    worker's tool, and the flow's only side effect. Records the
    server-computed recommendation packet in BANK_CORE.hitl_task and enqueues
    HITL_REQUEST in the same transaction.

customer_id is resolved from the opaque token inside the PL/SQL functions
(bind variables) — never from the chat message, so neither tool can be steered
to another customer's application (same boundary as banking-mcp.get_context).

Why MCP rather than a PAF SQL Query node: that node is read-only by design
(docs/PAF.md §10); anything with side effects goes through MCP/REST.

Connects as CUSTOMER_AGENT_RW, the client user for CHAT_FLOW's write path,
which holds EXECUTE on BANK_TOOLS.PKG_AGENT_TOOLS and no table privilege; the
package runs with definer's rights (BANK_TOOLS has INSERT/UPDATE on
BANK_CORE.loan_application via changeset 012, INSERT/SELECT on hitl_task and
ENQUEUE on HITL_REQUEST via 007 + 009). Each Agent Builder MCP Server node
that points here lists exactly one tool under "Allowed MCP tools", so a worker
sees only its own.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone

import httpx
import oracledb
from fastmcp import Client, FastMCP

mcp = FastMCP("application-mcp")

DB_DSN = os.environ["DB_DSN"]
DB_USER = os.environ["DB_USER"]
TNS_ADMIN = os.environ["TNS_ADMIN"]
DB_WALLET_PASSWORD = os.getenv("DB_WALLET_PASSWORD", "")
DB_PASSWORD = os.environ["DB_PASSWORD"]

def _connect():
    """Open a database connection. Autonomous Database is behind mTLS, so the
    wallet directory supplies both the alias in DB_DSN and the certificates."""
    return oracledb.connect(
        user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN,
        config_dir=TNS_ADMIN, wallet_location=TNS_ADMIN,
        wallet_password=DB_WALLET_PASSWORD,
    )


_AUDIT_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8090").rstrip("/") + "/v1/audit/tool-call"
_BANKING_MCP_URL = os.getenv("BANKING_MCP_URL", "http://127.0.0.1:8503/mcp")


def _now():
    return datetime.now(timezone.utc)


def _audit(tool_name, status, started, ended, tool_input, tool_output, *, session_token):
    """Best-effort per-tool audit to the Application Service. The application is resolved
    server-side from session_token — never sent as a raw id. Never raises — an audit
    failure must not break the live tool call."""
    try:
        httpx.post(_AUDIT_URL, json={
            "sessionToken": session_token,
            "toolName": tool_name,
            "status": status,
            "startedAt": started.isoformat(),
            "endedAt": ended.isoformat(),
            "toolInput": json.dumps(tool_input, default=str),
            "toolOutput": json.dumps(tool_output, default=str),
        }, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 — audit is fire-and-forget
        print(f"[audit] skipped ({tool_name}): {exc}", flush=True)


@mcp.tool()
def upsert_application(
    session_token: str,
    amount: float | None = None,
    term_months: int | None = None,
    purpose: str | None = None,
) -> dict:
    """Create or patch the customer's DRAFT loan application.

    The Concierge agent calls this as it collects the loan request. Pass only
    the fields you just learned; omitted/None fields are left unchanged. Safe
    to call repeatedly — it never creates a second application for a customer
    who already has an open one.

    Parameters
    ----------
    session_token : str
        Opaque login token. The customer is resolved from it server-side.
        Never pass an id taken from the chat message.
    amount : float, optional
        Requested loan amount.
    term_months : int, optional
        Repayment term in months.
    purpose : str, optional
        Free-text loan purpose.

    Returns
    -------
    dict
        { "application_id": int } on success.
        { "error": "invalid_or_expired_session" } for a bad/expired token.
        { "error": "amount_out_of_range", "min_amount": ..., "max_amount": ... }
        or { "error": "term_out_of_range", "min_term_months": ...,
        "max_term_months": ... } when the request falls outside what this
        product is sold at. Nothing is written in that case — tell the customer
        the range that came back and ask for a figure inside it.
        { "error": "application_under_review" } when a recommendation is already
        with a reviewer and this call would change the amount or the term.
        Nothing is written — tell the customer their application is already with
        the team, so the figures it was assessed on cannot change now. Changing
        only the purpose is still allowed.
    """
    started = _now()
    result = _upsert_application_impl(session_token, amount, term_months, purpose)
    status = "FAILED" if isinstance(result, dict) and "error" in result else "SUCCESS"
    _audit("upsert_application", status, started, _now(),
           {"amount": amount, "term_months": term_months, "purpose": purpose},
           result, session_token=session_token)
    return result


# PKG_AGENT_TOOLS refuses an amount or term the product is not sold at, and packs
# the bounds into the error so the agent can name them instead of guessing.
_OUT_OF_RANGE = re.compile(r"(amount|term)_out_of_range:(-?[\d.]+):(-?[\d.]+)")
_RANGE_KEYS = {
    "amount": ("min_amount", "max_amount", float),
    "term": ("min_term_months", "max_term_months", int),
}


def _out_of_range(err) -> dict | None:
    """The refusal as a structured result, or None when this was another error."""
    found = _OUT_OF_RANGE.search(getattr(err, "message", "") or "")
    if not found:
        return None
    kind, low, high = found.group(1), found.group(2), found.group(3)
    low_key, high_key, cast = _RANGE_KEYS[kind]
    return {"error": f"{kind}_out_of_range", low_key: cast(low), high_key: cast(high)}


def _upsert_application_impl(
    session_token: str,
    amount: float | None = None,
    term_months: int | None = None,
    purpose: str | None = None,
) -> dict:
    print(f"[upsert_application] token={session_token!r} amount={amount} term={term_months} purpose={purpose!r}", flush=True)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                application_id = cur.callfunc(
                    "BANK_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application",
                    int,
                    [session_token, amount, term_months, purpose],
                )
            conn.commit()
    except oracledb.DatabaseError as e:
        # NO_DATA_FOUND from the token lookup surfaces as ORA-01403.
        (err,) = e.args
        if getattr(err, "code", None) == 1403:
            print("[upsert_application] -> invalid_or_expired_session", flush=True)
            return {"error": "invalid_or_expired_session"}
        refused = _out_of_range(err)
        if refused:
            print(f"[upsert_application] -> {refused}", flush=True)
            return refused
        if "application_under_review" in (getattr(err, "message", "") or ""):
            print("[upsert_application] -> application_under_review", flush=True)
            return {"error": "application_under_review"}
        raise
    print(f"[upsert_application] -> application_id={application_id}", flush=True)
    return {"application_id": application_id}


async def _recommendation_packet(session_token: str) -> dict:
    """The server-computed decision packet from banking-mcp: tier, reasoning and
    the evidence the review portal renders. Returns an empty packet if it cannot
    be reached — the caller then records nothing."""
    try:
        async with Client(_BANKING_MCP_URL) as client:
            result = await client.call_tool(
                "recommend_tier_for_session", {"session_token": session_token}
            )
        return json.loads(result.content[0].text)
    except Exception as exc:  # noqa: BLE001 — fail closed, never write a guess
        print(f"[create_hitl_task] recommendation lookup failed: {exc}", flush=True)
        return {}


@mcp.tool()
async def create_hitl_task(
    session_token: str,
    explore_hints: str | None = None,
) -> dict:
    """Write the CHAT_FLOW recommendation packet to BANK_CORE.hitl_task and
    enqueue HITL_REQUEST in the same transaction. Returns the new task_id
    and the server-generated `agent_run_id`.

    This is CHAT_FLOW's ONLY side-effect tool: every successful run ends
    with exactly one call. The human reviewer (not the agent) closes the
    task; that close is what writes the Blockchain `decision` row.

    Everything recorded is computed server-side from the opaque session token:
    the application, the recommendation tier, its reasoning and the evidence
    packet. No agent names an application, chooses a tier or re-words a policy
    message, so what the reviewer reads is what the policy actually returned.

    The tier is returned to you with `factors` — the customer-safe words for
    what the outcome turned on. Write the customer's reply from THOSE, never
    from a tier or a factor you inferred yourself, and never quote a number,
    threshold or reason code.

    Argument extraction guidance for the LLM:
      - session_token  — the opaque `sess_...` token from the manager's
                         message. Copy it exactly; never invent one.
      - explore_hints  — REVIEW-only: JSON string array of follow-up
                         questions/checks the reviewer should examine.
                         Pass null otherwise.

    Note: `agent_run_id` is generated server-side as a UUID-4 and returned
    in the response. The agent must NOT supply it — LLMs reliably
    hallucinate non-hex strings (`a4b5c6d7-e8f9-g0h1-…`) when asked to
    produce a UUID.
    """
    started = _now()
    print(f"[create_hitl_task] called session_token={session_token!r}", flush=True)
    agent_run_id = str(uuid.uuid4())
    tool_input = {"explore_hints": explore_hints}

    packet = await _recommendation_packet(session_token)
    tier = packet.get("tier")
    if tier in (None, "UNAVAILABLE"):
        print(f"[create_hitl_task] -> no decision available (tier={tier})", flush=True)
        out = {"error": "no_decision_available"}
        _audit("create_hitl_task", "SKIPPED", started, _now(), tool_input, out,
               session_token=session_token)
        return out
    recommendation = tier
    reasoning = packet.get("reasoning") or ""
    factors = packet.get("factors") or []
    reason_codes = (packet.get("evidence") or {}).get("reason_codes") or []
    evidence = json.dumps(packet.get("evidence"))

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                task_id = cur.callfunc(
                    "BANK_TOOLS.PKG_AGENT_TOOLS.create_hitl_task",
                    int,
                    [
                        session_token,
                        recommendation,
                        reasoning,
                        explore_hints,
                        evidence,
                        agent_run_id,
                    ],
                )
            conn.commit()
    except oracledb.DatabaseError as exc:
        # NO_DATA_FOUND inside the package: unknown/expired token, or the
        # customer has no open application. Fail closed, and record the attempt.
        print(f"[create_hitl_task] -> rejected: {exc}", flush=True)
        out = {"error": "invalid_or_expired_session"}
        _audit("create_hitl_task", "FAILED", started, _now(), tool_input, out,
               session_token=session_token)
        return out
    out = {
        "task_id": task_id,
        "tier": recommendation,
        "factors": factors,
        "reason_codes": reason_codes,
        "agent_run_id": agent_run_id,
        "state": "OPEN",
        "queue": "BANK_CORE.HITL_REQUEST",
        "message": (
            f"HITL task {task_id} recorded with tier {recommendation}; "
            f"enqueued on HITL_REQUEST. Write the customer's reply for tier "
            f"{recommendation}, naming only these factors: "
            f"{factors or 'none — name no factor at all'}. Never mention a "
            f"number, threshold, score, ratio, tier name or reason code."
        ),
    }
    _audit("create_hitl_task", "SUCCESS", started, _now(), tool_input, out,
           session_token=session_token)
    print(f"[create_hitl_task] -> success task_id={task_id} agent_run_id={agent_run_id}", flush=True)
    return out


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8504"))
    mcp.run(transport="streamable-http", host=host, port=port)
