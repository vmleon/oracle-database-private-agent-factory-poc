"""application-mcp — the write surface for conversational intake.

Single tool: upsert_application(session_token, amount?, term_months?, purpose?)
creates the customer's DRAFT loan application on first call and patches
supplied fields after. customer_id is resolved from the opaque token inside
the PL/SQL function (bind variables) — never from the chat message, so this
cannot be steered to another customer's application (IDOR-safe, same boundary
as banking-mcp.lookup_application / get_context).

Connects as CUSTOMER_AGENT_RW, the client user for CHAT_FLOW's write path,
which holds EXECUTE on BANK_TOOLS.PKG_AGENT_TOOLS and no table privilege;
the package runs with definer's rights (BANK_TOOLS has INSERT/UPDATE on
BANK_CORE.loan_application via changeset 012). Mirrors hitl-mcp.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import httpx
import oracledb
from fastmcp import FastMCP

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
        raise
    print(f"[upsert_application] -> application_id={application_id}", flush=True)
    return {"application_id": application_id}


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8504"))
    mcp.run(transport="streamable-http", host=host, port=port)
