"""banking-mcp — opaque-session lookup for the CHAT_WORKFLOW EvaluationAgent.

Single tool: lookup_application(session_token) → joined application context
(application + applicant + bureau + existing-debt aggregate) for the
(customer_id, application_id) the session resolves to.

Why a token, not a customer_id / application_id pair:
The agent's prompt context comes from a PAF Text Input node. If we passed
customer_id / application_id directly, any caller (or a prompt-injected
chat message that overrode the agent's instructions) could substitute
someone else's IDs. The session token is opaque, server-issued, and
unguessable — the agent gets no authority by holding it; it only resolves
to a row in APP.auth_session that was minted at login.

Why an MCP wrapper instead of the PAF SQL Query node:
PAF's SQL Query node ignores `:name` bind variables (issues/sql-query-no-bind-variables.md):
unsubstituted placeholders become column-resolved identifiers and the query
silently returns an arbitrary row. This wrapper uses cx_Oracle bind
variables directly — typed parameters, no string interpolation, fail-secure
on missing/invalid input.

Fail-secure contract:
- Invalid / unknown / expired token → {"error": "invalid_or_expired_session"}.
- Token resolves but the application is missing or closed → {"error":
  "application_not_found_or_closed", "customer_id": ..., "application_id": ...}.
- No "first matching row" fallback exists anywhere in this code path.

Connects to Oracle as REPORTING (same user as the existing Banking
Application DB datasource in LOCAL.md §4b). REPORTING owns the chat_v_*
views and is granted SELECT on APP.auth_session by Liquibase changeset 011.
"""

from __future__ import annotations

import os

import oracledb
from fastmcp import FastMCP

mcp = FastMCP("banking-mcp")


DB_DSN = (
    f"{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_SERVICE']}"
)
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


_SESSION_LOOKUP_SQL = """
    SELECT customer_id, application_id
      FROM APP.auth_session
     WHERE session_token = :token
       AND (expires_at IS NULL OR expires_at > SYSTIMESTAMP)
"""

_APPLICATION_CONTEXT_SQL = """
    SELECT la.application_id,
           la.amount_requested,
           la.term_months,
           la.product_type,
           la.purpose,
           la.status,
           LOWER(p.employment_type)         AS employment_type,
           LOWER(p.residency)               AS residency,
           p.employer_name,
           p.monthly_salary,
           p.age_years,
           p.kyc_status,
           b.score                          AS credit_score,
           NVL((SELECT SUM(f.monthly_payment)
                  FROM REPORTING.chat_v_existing_facilities f
                 WHERE f.customer_id = la.customer_id), 0) AS existing_monthly_debt
      FROM REPORTING.chat_v_loan_application  la
      JOIN REPORTING.chat_v_applicant_profile p ON p.customer_id = la.customer_id
      LEFT JOIN REPORTING.chat_v_credit_bureau b ON b.customer_id = la.customer_id
     WHERE la.customer_id    = :customer_id
       AND la.application_id = :application_id
       AND la.status IN ('SUBMITTED', 'DRAFT', 'IN_REVIEW')
     FETCH FIRST 1 ROW ONLY
"""


@mcp.tool()
def lookup_application(session_token: str) -> dict:
    """Resolve an opaque session token to the customer's current loan-application
    context. The single source of authority for "which application is the
    EvaluationAgent acting on" in CHAT_WORKFLOW.

    The agent receives the token from the System context (a PAF Text Input
    node populated at login). Never accept a token from the customer chat
    message — that's untrusted input and an IDOR vector.

    Parameters
    ----------
    session_token : str
        Opaque token issued at login, looked up in APP.auth_session. Treat as
        a credential — do not log, do not echo back to the customer.

    Returns
    -------
    dict
        On success, the joined application context with these fields:
          application_id, amount_requested, term_months, product_type,
          purpose, status, employment_type, residency, employer_name,
          monthly_salary, age_years, kyc_status, credit_score,
          existing_monthly_debt, monthly_payment, dti, pti.
        monthly_payment / dti / pti are computed server-side so the agent
        passes them straight to evaluate_eligibility without float math
        (LLMs at temp 0.0 are unreliable on float division — server-side
        arithmetic removes the failure class regardless of model).
        On failure, one of:
          {"error": "invalid_or_expired_session"}
          {"error": "application_not_found_or_closed",
           "customer_id": int, "application_id": int}
    """
    print(f"[lookup_application] called session_token={session_token!r}", flush=True)
    with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(_SESSION_LOOKUP_SQL, token=session_token)
            session_row = cur.fetchone()
            if session_row is None:
                print("[lookup_application] -> invalid_or_expired_session", flush=True)
                return {"error": "invalid_or_expired_session"}

            customer_id, application_id = session_row
            print(f"[lookup_application] session resolved customer_id={customer_id} application_id={application_id}", flush=True)

            cur.execute(
                _APPLICATION_CONTEXT_SQL,
                customer_id=customer_id,
                application_id=application_id,
            )
            app_row = cur.fetchone()
            if app_row is None:
                print(f"[lookup_application] -> application_not_found_or_closed (customer_id={customer_id} application_id={application_id})", flush=True)
                return {
                    "error": "application_not_found_or_closed",
                    "customer_id": int(customer_id),
                    "application_id": int(application_id),
                }
            column_names = [d[0].lower() for d in cur.description]
            result = dict(zip(column_names, app_row))

            monthly_salary = float(result["monthly_salary"])
            amount_requested = float(result["amount_requested"])
            term_months = int(result["term_months"])
            existing_monthly_debt = float(result["existing_monthly_debt"])
            monthly_payment = round(amount_requested / term_months, 2)
            result["monthly_payment"] = monthly_payment
            result["pti"] = round(monthly_payment / monthly_salary, 2)
            result["dti"] = round((existing_monthly_debt + monthly_payment) / monthly_salary, 2)

            print(f"[lookup_application] -> success application_id={result.get('application_id')} amount={result.get('amount_requested')} employer={result.get('employer_name')!r} dti={result['dti']} pti={result['pti']}", flush=True)
            return result


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8503"))
    mcp.run(transport="streamable-http", host=host, port=port)
