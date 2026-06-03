"""application-mcp — the write surface for conversational intake.

Single tool: upsert_application(session_token, amount?, term_months?, purpose?)
creates the customer's DRAFT loan application on first call and patches
supplied fields after. customer_id is resolved from the opaque token inside
the PL/SQL function (bind variables) — never from the chat message, so this
cannot be steered to another customer's application (IDOR-safe, same boundary
as banking-mcp.lookup_application / get_context).

Connects as AGENT_FACTORY, which has EXECUTE on AGENT_TOOLS.PKG_AGENT_TOOLS;
the package runs with definer's rights (AGENT_TOOLS has INSERT/UPDATE on
APP.loan_application via changeset 012). Mirrors hitl-mcp.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx
import oracledb
from fastmcp import FastMCP

mcp = FastMCP("application-mcp")

DB_DSN = f"{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_SERVICE']}"
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


_AUDIT_URL = os.getenv("BACKEND_URL", "http://application-backend:8090").rstrip("/") + "/v1/audit/tool-call"


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
        { "application_id": int } on success, or
        { "error": "invalid_or_expired_session" } for a bad/expired token.
    """
    started = _now()
    result = _upsert_application_impl(session_token, amount, term_months, purpose)
    status = "FAILED" if isinstance(result, dict) and "error" in result else "SUCCESS"
    _audit("upsert_application", status, started, _now(),
           {"amount": amount, "term_months": term_months, "purpose": purpose},
           result, session_token=session_token)
    return result


def _upsert_application_impl(
    session_token: str,
    amount: float | None = None,
    term_months: int | None = None,
    purpose: str | None = None,
) -> dict:
    print(f"[upsert_application] token={session_token!r} amount={amount} term={term_months} purpose={purpose!r}", flush=True)
    try:
        with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
            with conn.cursor() as cur:
                application_id = cur.callfunc(
                    "AGENT_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application",
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
        raise
    print(f"[upsert_application] -> application_id={application_id}", flush=True)
    return {"application_id": application_id}


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8504"))
    mcp.run(transport="streamable-http", host=host, port=port)
