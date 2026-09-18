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
to a row in BANK_CORE.auth_session that was minted at login.

Why an MCP wrapper instead of the PAF SQL Query node:
PAF's SQL Query node ignores `:name` bind variables (issues/02-sql-query-no-bind-variables.md):
unsubstituted placeholders become column-resolved identifiers and the query
silently returns an arbitrary row. This wrapper uses cx_Oracle bind
variables directly — typed parameters, no string interpolation, fail-secure
on missing/invalid input.

Fail-secure contract:
- Invalid / unknown / expired token → {"error": "invalid_or_expired_session"}.
- Token resolves but the application is missing or closed → {"error":
  "application_not_found_or_closed", "customer_id": ..., "application_id": ...}.
- No "first matching row" fallback exists anywhere in this code path.

Connects to Oracle as CUSTOMER_AGENT_RO, the client user for CHAT_FLOW's read
path. It is granted SELECT on the customer-safe BANK_VIEWS.chat_v_* set and on
the two BANK_CORE tables the session-scoped tools resolve against — and on
nothing in the backoffice research_v_* set (Liquibase changeset 020).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx
import oracledb
from fastmcp import FastMCP

from gate import (aml_input, amount_value, documents_payload, factors_for, gate_decision,
                  tier_from, unusable_application_fields)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


_AUDIT_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8090").rstrip("/") + "/v1/audit/tool-call"
_OPA_URL = os.getenv("OPA_URL", "http://127.0.0.1:8181").rstrip("/")
_REGISTRY_URL = os.getenv("REGISTRY_URL", "http://127.0.0.1:8600").rstrip("/")


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


def _f(v):
    return None if v is None else float(v)


def _i(v):
    return None if v is None else int(v)

mcp = FastMCP("banking-mcp")


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


_SESSION_LOOKUP_SQL = """
    SELECT customer_id, application_id
      FROM BANK_CORE.auth_session
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
                  FROM BANK_VIEWS.chat_v_existing_facilities f
                 WHERE f.customer_id = la.customer_id), 0) AS existing_monthly_debt
      FROM BANK_VIEWS.chat_v_loan_application  la
      JOIN BANK_VIEWS.chat_v_applicant_profile p ON p.customer_id = la.customer_id
      LEFT JOIN BANK_VIEWS.chat_v_credit_bureau b ON b.customer_id = la.customer_id
     WHERE la.customer_id    = :customer_id
       AND la.application_id = :application_id
       AND la.status IN ('SUBMITTED', 'DRAFT', 'IN_REVIEW')
     FETCH FIRST 1 ROW ONLY
"""

_CUSTOMER_BY_TOKEN_SQL = """
    SELECT customer_id
      FROM BANK_CORE.auth_session
     WHERE session_token = :token
       AND (expires_at IS NULL OR expires_at > SYSTIMESTAMP)
"""

_PROFILE_SQL = """
    SELECT p.customer_id,
           p.full_name,
           p.age_years,
           LOWER(p.residency)        AS residency,
           p.kyc_status,
           p.kyc_updated_at,
           LOWER(p.employment_type)  AS employment_type,
           p.monthly_salary,
           p.employer_name,
           b.score                   AS credit_score,
           NVL((SELECT SUM(f.monthly_payment)
                  FROM BANK_VIEWS.chat_v_existing_facilities f
                 WHERE f.customer_id = p.customer_id), 0) AS existing_monthly_debt,
           NVL((SELECT s.large_round_outflows_30d
                  FROM BANK_VIEWS.chat_v_aml_signals s
                 WHERE s.customer_id = p.customer_id), 0) AS large_round_outflows_30d
      FROM BANK_VIEWS.chat_v_applicant_profile p
      LEFT JOIN BANK_VIEWS.chat_v_credit_bureau b ON b.customer_id = p.customer_id
     WHERE p.customer_id = :customer_id
"""

_OPEN_APPLICATION_SQL = """
    SELECT application_id, amount_requested, term_months,
           product_type, purpose, status
      FROM BANK_VIEWS.chat_v_loan_application
     WHERE customer_id = :customer_id
       AND status IN ('DRAFT','SUBMITTED','IN_REVIEW')
     ORDER BY application_id DESC
     FETCH FIRST 1 ROW ONLY
"""

_KYC_STALE_DAYS = 180


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
        Opaque token issued at login, looked up in BANK_CORE.auth_session. Treat as
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
        (LLMs at near-zero temperature are unreliable on float division —
        server-side arithmetic removes the failure class regardless of model).
        On failure, one of:
          {"error": "invalid_or_expired_session"}
          {"error": "application_not_found_or_closed",
           "customer_id": int, "application_id": int}
    """
    print(f"[lookup_application] called session_token={session_token!r}", flush=True)
    with _connect() as conn:
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

            unusable = unusable_application_fields(result)
            if unusable:
                # Fail closed rather than divide: the caller gets a named reason
                # instead of the turn dying inside the node with nothing to
                # explain it.
                print(f"[lookup_application] -> application_incomplete {unusable}", flush=True)
                return {"error": "application_incomplete", "missing": unusable}

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


@mcp.tool()
def get_context(session_token: str) -> dict:
    """Resolve an opaque session token to the customer's full origination
    context in one call: identity + KYC freshness, profile/income, credit,
    existing debt, and their open application (or null) with the list of
    still-missing loan-request fields. Every origination agent calls this
    first so its facts come from the database, never from another agent's text.

    Returns a dict shaped:
      { customer:{...}, application:{...}|None with missing[], profile:{...},
        credit:{...}, facilities:{...}, derived:{dti,pti}|None }
    or {"error": "invalid_or_expired_session"} for a bad/expired token.
    """
    started = _now_utc()
    result = _get_context_impl(session_token)
    status = "FAILED" if isinstance(result, dict) and "error" in result else "SUCCESS"
    _audit("get_context", status, started, _now_utc(), {}, result, session_token=session_token)
    return result


def _get_context_impl(session_token: str) -> dict:
    print(f"[get_context] called session_token={session_token!r}", flush=True)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_CUSTOMER_BY_TOKEN_SQL, token=session_token)
            row = cur.fetchone()
            if row is None:
                print("[get_context] -> invalid_or_expired_session", flush=True)
                return {"error": "invalid_or_expired_session"}
            customer_id = int(row[0])

            cur.execute(_PROFILE_SQL, customer_id=customer_id)
            p = dict(zip([d[0].lower() for d in cur.description], cur.fetchone()))

            cur.execute(_OPEN_APPLICATION_SQL, customer_id=customer_id)
            app_row = cur.fetchone()
            application = None
            derived = None
            if app_row is not None:
                a = dict(zip([d[0].lower() for d in cur.description], app_row))
                missing = unusable_application_fields(a)
                application = {
                    "id": int(a["application_id"]),
                    "status": a["status"],
                    "amount_requested": amount_value(a["amount_requested"]),
                    "term_months": _i(a["term_months"]),
                    "product_type": a["product_type"],
                    "purpose": a["purpose"],
                    "missing": missing,
                }
                if not missing:
                    monthly_payment = round(float(a["amount_requested"]) / int(a["term_months"]), 2)
                    salary = float(p["monthly_salary"])
                    debt = float(p["existing_monthly_debt"])
                    derived = {
                        "monthly_payment": monthly_payment,
                        "pti": round(monthly_payment / salary, 2),
                        "dti": round((debt + monthly_payment) / salary, 2),
                    }

            kyc_updated_at = p.get("kyc_updated_at")
            kyc_age_days = None
            kyc_stale = True
            if kyc_updated_at is not None:
                ref = kyc_updated_at if kyc_updated_at.tzinfo else kyc_updated_at.replace(tzinfo=timezone.utc)
                kyc_age_days = (_now_utc() - ref).days
                kyc_stale = kyc_age_days > _KYC_STALE_DAYS

            result = {
                "customer": {
                    "id": customer_id,
                    "name": p["full_name"],
                    "age_years": _i(p["age_years"]),
                    "residency": p["residency"],
                    "kyc_status": p["kyc_status"],
                    "kyc_age_days": kyc_age_days,
                    "kyc_stale": kyc_stale,
                    "large_round_outflows_30d": _i(p["large_round_outflows_30d"]),
                },
                "application": application,
                "profile": {
                    "employment_type": p["employment_type"],
                    "employer_name": p["employer_name"],
                    "monthly_salary": _f(p["monthly_salary"]),
                    "income_stale": False,  # Phase 2: wire real income recency
                },
                "credit": {"score": _i(p["credit_score"])},
                "facilities": {"existing_monthly_debt": _f(p["existing_monthly_debt"])},
                "derived": derived,
            }
            print(f"[get_context] -> customer_id={customer_id} has_app={application is not None} "
                  f"missing={application['missing'] if application else None} kyc_stale={kyc_stale}", flush=True)
            return result


def _eligibility_impl(session_token: str) -> dict:
    """Deterministic eligibility: token in -> {allow, deny, warn} out.

    Resolves the opaque session token, builds the OPA `applicant` from the SAME
    DB-derived values get_context returns (age / income / credit_score / dti / pti),
    and evaluates the `decisioning.eligibility` Rego rule. No LLM constructs the
    payload, so the policy always sees the fields where it expects them — this is
    the deterministic counterpart to get_context, for the policy-eval step.

    Returns {"allow": bool, "deny": [str], "warn": [str]}. Fail-closed (allow=False)
    on a bad token, an incomplete application, or an OPA error.
    """
    started = _now_utc()
    print(f"[evaluate_eligibility_for_session] called session_token={session_token!r}", flush=True)
    ctx = _get_context_impl(session_token)
    if ctx.get("error"):
        out = {"allow": False, "deny": ["invalid_or_expired_session"], "warn": []}
        _audit("evaluate_eligibility_for_session", "FAILED", started, _now_utc(), {}, out,
               session_token=session_token)
        return out
    app = ctx.get("application") or {}
    if not app or app.get("missing"):
        # Incomplete application: derived (dti/pti) is null. Unused on collecting
        # turns (the flow exits at G1 before Recommendation); fail closed.
        print("[evaluate_eligibility_for_session] -> incomplete application, fail-closed", flush=True)
        out = {"allow": False, "deny": [], "warn": []}
        _audit("evaluate_eligibility_for_session", "SKIPPED", started, _now_utc(), {}, out,
               session_token=session_token)
        return out
    cust = ctx.get("customer") or {}
    prof = ctx.get("profile") or {}
    cred = ctx.get("credit") or {}
    der = ctx.get("derived") or {}
    opa_input = {
        "applicant": {
            "age": cust.get("age_years"),
            "income": prof.get("monthly_salary"),
            "credit_score": cred.get("score"),
            "dti": der.get("dti"),
            "pti": der.get("pti"),
        },
        "application": {
            "amount_requested": app.get("amount_requested"),
            "term_months": app.get("term_months"),
        },
        "product": {"product_type": app.get("product_type") or "PERSONAL"},
    }
    try:
        resp = httpx.post(f"{_OPA_URL}/v1/data/decisioning/eligibility",
                          json={"input": opa_input}, timeout=5.0)
        resp.raise_for_status()
        res = resp.json().get("result") or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluate_eligibility_for_session] OPA error: {exc}", flush=True)
        out = {"allow": False, "deny": ["eligibility_unavailable"], "warn": []}
        _audit("evaluate_eligibility_for_session", "FAILED", started, _now_utc(), opa_input, out,
               session_token=session_token)
        return out
    out = {
        "allow": bool(res.get("allow", False)),
        "deny": res.get("deny", []),
        "warn": res.get("warn", []),
    }
    _audit("evaluate_eligibility_for_session", "SUCCESS", started, _now_utc(), opa_input, out,
           session_token=session_token)
    print(f"[evaluate_eligibility_for_session] -> allow={out['allow']} deny={out['deny']} warn={out['warn']}", flush=True)
    return out


def _pricing_impl(ctx: dict) -> dict | None:
    """Indicative pricing for the recommendation packet, from the same context.

    `opa/packages/pricing.rego` is the rate card keyed by risk band; the offer a
    customer is eventually quoted is settled after a human approves, so this is
    the reviewer's reference figure and the one the decision record keeps.

    Returns None when the inputs are not all present or OPA cannot be reached:
    the tier and its reason codes must not depend on the rate card being up.
    """
    app = ctx.get("application") or {}
    der = ctx.get("derived") or {}
    cred = ctx.get("credit") or {}
    opa_input = {
        "applicant": {"credit_score": cred.get("score"), "dti": der.get("dti")},
        "application": {"amount": app.get("amount_requested"),
                        "term_months": app.get("term_months")},
    }
    if any(v is None for v in opa_input["applicant"].values()) or \
       any(v is None for v in opa_input["application"].values()):
        return None
    try:
        resp = httpx.post(f"{_OPA_URL}/v1/data/decisioning/pricing/quote",
                          json={"input": opa_input}, timeout=5.0)
        resp.raise_for_status()
        return resp.json().get("result") or None
    except Exception as exc:  # noqa: BLE001 — pricing is informational
        print(f"[recommend_tier_for_session] pricing unavailable: {exc}", flush=True)
        return None


def _compliance_impl(package: str, opa_input: dict) -> dict | None:
    """One decisioning package, evaluated on a context the caller already has.

    These are evidence, not gates: `tier_from` is a pure function of eligibility
    and the employer record and stays that way. A reviewer sees a KYC or
    sanctions finding before it influences anything, which is the order a human
    decision wants. Returns None when OPA cannot be reached — the tier must not
    depend on the policy server being up.
    """
    try:
        resp = httpx.post(f"{_OPA_URL}/v1/data/decisioning/{package}",
                          json={"input": opa_input}, timeout=5.0)
        resp.raise_for_status()
        result = resp.json().get("result") or {}
    except Exception as exc:  # noqa: BLE001 — compliance evidence is informational
        print(f"[recommend_tier_for_session] {package} unavailable: {exc}", flush=True)
        return None
    return {
        "allow": bool(result.get("allow")),
        "deny": sorted(result.get("deny") or []),
        "warn": sorted(result.get("warn") or []),
    }


def _kyc_impl(ctx: dict) -> dict | None:
    """KYC status and ID expiry. `documents` is empty until an upload path
    exists, so the expiry rule stands ready rather than firing."""
    customer = ctx.get("customer") or {}
    if not customer.get("kyc_status"):
        return None
    return _compliance_impl("kyc", {
        "customer": {"kyc_status": customer["kyc_status"]},
        "documents": [],
        "today": _now_utc().date().isoformat(),
    })


def _aml_impl(ctx: dict) -> dict | None:
    """Sanctions, watch-list and PEP screening on the customer's name, and the
    suspicious-outflow pattern on their transactions.

    `aml.rego` carries its own synthetic screening lists, so the name needs no
    table; the outflow count comes with the customer context, read from
    `BANK_VIEWS.chat_v_aml_signals`."""
    customer = ctx.get("customer") or {}
    if not customer.get("name"):
        return None
    return _compliance_impl("aml", aml_input(customer))


def _policy_versions_impl() -> list[dict] | None:
    """Which policy modules decided this. Stamped into the packet so the
    decision record says what it was evaluated against, not just what came out."""
    try:
        resp = httpx.get(f"{_OPA_URL}/v1/policies", timeout=5.0)
        resp.raise_for_status()
        return sorted(
            ({"id": e.get("id"), "raw_bytes": len(e.get("raw", "") or "")}
             for e in resp.json().get("result", [])),
            key=lambda e: e["id"] or "",
        )
    except Exception as exc:  # noqa: BLE001 — provenance is informational
        print(f"[recommend_tier_for_session] policy versions unavailable: {exc}", flush=True)
        return None


def _documents_impl(session_token: str) -> dict:
    """Deterministic document set: token in -> the required doc_type list out.

    Resolves the opaque session token and evaluates `decisioning.required_documents`
    with the product, employment, residency and amount the DB already holds. No
    model constructs the payload, so the policy always sees the fields where it
    expects them.

    Fails closed: an invalid token or an incomplete application returns an empty
    list, which the manager treats as "no evidence yet".
    """
    started = _now_utc()
    print(f"[required_documents_for_session] called session_token={session_token!r}", flush=True)
    ctx = _get_context_impl(session_token)
    payload = documents_payload(ctx)
    if payload is None:
        print("[required_documents_for_session] -> incomplete or invalid, fail-closed", flush=True)
        out = {"required": [], "amount_band": None, "rationale": None}
        _audit("required_documents_for_session",
               "FAILED" if ctx.get("error") else "SKIPPED", started, _now_utc(), {}, out,
               session_token=session_token)
        return out
    try:
        resp = httpx.post(f"{_OPA_URL}/v1/data/decisioning/required_documents",
                          json={"input": payload}, timeout=5.0)
        resp.raise_for_status()
        res = resp.json().get("result") or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[required_documents_for_session] OPA error: {exc}", flush=True)
        out = {"required": [], "amount_band": None, "rationale": None}
        _audit("required_documents_for_session", "FAILED", started, _now_utc(), payload, out,
               session_token=session_token)
        return out
    out = {
        "required": res.get("required", []),
        "amount_band": res.get("amount_band"),
        "rationale": res.get("rationale"),
    }
    _audit("required_documents_for_session", "SUCCESS", started, _now_utc(), payload, out,
           session_token=session_token)
    print(f"[required_documents_for_session] -> {out['required']}", flush=True)
    return out


def _employer_impl(session_token: str) -> dict:
    """Deterministic employer check: token in -> the registry record out.

    Reads profile.employer_name from the DB-derived context and queries the
    company registry directly. The name is never copied by a model, which is
    what makes a wrong-company answer impossible.

    Fails closed: an invalid token or a missing employer name returns
    registered=false with trading_status "unknown".
    """
    started = _now_utc()
    print(f"[verify_employer_for_session] called session_token={session_token!r}", flush=True)
    closed = {"name": None, "registered": False, "trading_status": "unknown"}
    ctx = _get_context_impl(session_token)
    if ctx.get("error"):
        print("[verify_employer_for_session] -> invalid session, fail-closed", flush=True)
        _audit("verify_employer_for_session", "FAILED", started, _now_utc(), {}, closed,
               session_token=session_token)
        return closed
    name = ((ctx.get("profile") or {}).get("employer_name") or "").strip()
    if not name:
        print("[verify_employer_for_session] -> no employer name, fail-closed", flush=True)
        _audit("verify_employer_for_session", "SKIPPED", started, _now_utc(), {}, closed,
               session_token=session_token)
        return closed
    try:
        resp = httpx.get(f"{_REGISTRY_URL}/v1/companies/verify",
                         params={"name": name}, timeout=5.0)
        resp.raise_for_status()
        out = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[verify_employer_for_session] registry error: {exc}", flush=True)
        out = {**closed, "name": name}
        _audit("verify_employer_for_session", "FAILED", started, _now_utc(), {"name": name}, out,
               session_token=session_token)
        return out
    _audit("verify_employer_for_session", "SUCCESS", started, _now_utc(), {"name": name}, out,
           session_token=session_token)
    print(f"[verify_employer_for_session] -> registered={out.get('registered')} "
          f"trading_status={out.get('trading_status')}", flush=True)
    return out


@mcp.tool()
def evaluate_eligibility_for_session(session_token: str) -> dict:
    """Deterministic eligibility: token in -> {allow, deny, warn} out. The OPA
    `applicant` is built from the same DB-derived values get_context returns, so
    the policy always sees the fields where it expects them. Fail-closed."""
    return _eligibility_impl(session_token)


@mcp.tool()
def required_documents_for_session(session_token: str) -> dict:
    """Deterministic document set: token in -> {required, amount_band, rationale}
    out, from the product, employment, residency and amount the DB holds.
    Fail-closed: an invalid token or incomplete application returns an empty list."""
    return _documents_impl(session_token)


@mcp.tool()
def verify_employer_for_session(session_token: str) -> dict:
    """Deterministic employer check: token in -> the company registry record out.
    The employer name is read from the DB and never copied by a model.
    Fail-closed: registered=false, trading_status "unknown"."""
    return _employer_impl(session_token)




@mcp.tool()
def recommend_tier_for_session(session_token: str) -> dict:
    """Deterministic recommendation: token in -> the decision packet out.

    Computes eligibility, the employer record, the required documents and the
    KYC and AML findings from the values the token resolves to, then applies the
    tier rule:
      DECLINE if eligibility.deny OR employer.registered is false
              OR a KYC or AML deny — those are legal bars, not signals to weigh
      REVIEW  if eligibility.warn OR trading_status is "dormant"
              OR a KYC or AML warn
      APPROVE otherwise

    No model chooses the tier, re-words the evidence or files a value in the
    wrong slot: the returned `evidence` is the packet the reviewer's portal
    reads, built from the same records the decision rests on.

    Returns {"tier", "reasoning", "factors", "evidence"}, or tier "UNAVAILABLE"
    with evidence null for an invalid session or an incomplete application.
    `factors` is the customer-safe vocabulary for the reason codes — the only
    words about the outcome that may reach the customer.
    """
    started = _now_utc()
    print(f"[recommend_tier_for_session] called session_token={session_token!r}", flush=True)
    ctx = _get_context_impl(session_token)
    application = ctx.get("application") or {}
    if ctx.get("error") or not application or application.get("missing"):
        out = {"tier": "UNAVAILABLE", "reasoning": None, "evidence": None}
        _audit("recommend_tier_for_session",
               "FAILED" if ctx.get("error") else "SKIPPED", started, _now_utc(),
               {}, out, session_token=session_token)
        print("[recommend_tier_for_session] -> UNAVAILABLE, fail-closed", flush=True)
        return out

    eligibility = _eligibility_impl(session_token)
    employer = _employer_impl(session_token)
    documents = (_documents_impl(session_token) or {}).get("required") or []
    kyc = _kyc_impl(ctx)
    aml = _aml_impl(ctx)
    tier, codes = tier_from(eligibility, employer, kyc, aml)

    deny = eligibility.get("deny") or []
    warn = eligibility.get("warn") or []
    parts = []
    if deny:
        parts.append("eligibility deny: " + "; ".join(deny))
    if warn:
        parts.append("eligibility warn: " + "; ".join(warn))
    if employer.get("registered") is False:
        parts.append("employer not on the company registry")
    elif (employer.get("trading_status") or "").lower() == "dormant":
        parts.append("employer trading status dormant")
    for message in ((kyc or {}).get("deny") or []) + ((aml or {}).get("deny") or []):
        parts.append("compliance bar: " + message)
    for message in ((kyc or {}).get("warn") or []) + ((aml or {}).get("warn") or []):
        parts.append("compliance warn: " + message)
    if not parts:
        parts.append("no deny or warn messages; employer registered and active; "
                     "identity and screening checks clear")
    reasoning = "; ".join(parts) + "."

    out = {
        "tier": tier,
        "reasoning": reasoning,
        "factors": factors_for(codes),
        "evidence": {
            "reason_codes": codes,
            "eligibility": eligibility,
            "employer": employer,
            "documents": documents,
            # The ratios the tier rests on and the indicative rate. They are
            # computed on this turn and nowhere else, so the packet is where the
            # decision record reads them from when the reviewer closes the task.
            "derived": ctx.get("derived"),
            "pricing": _pricing_impl(ctx),
            # Compliance evidence. Served by OPA all along and never asked for:
            # the reviewer reads these next to the tier, and neither moves it.
            "kyc": kyc,
            "aml": aml,
            "policy_versions": _policy_versions_impl(),
        },
    }
    _audit("recommend_tier_for_session", "SUCCESS", started, _now_utc(), {}, out,
           session_token=session_token)
    print(f"[recommend_tier_for_session] -> {tier} codes={codes}", flush=True)
    return out


@mcp.tool()
def hitl_status_for_session(session_token: str, reply: str = "") -> dict:
    """Deterministic turn check: token (+ the manager's reply) in ->
    {"gate", "stage", "task_id"} out.

    Reads the context and the HITL queue and reports where the application
    stands: still collecting, awaiting a decision, or complete with a task
    recorded. `gate` fails on an invalid session, and fails when `reply`
    announces a decision (one of the customer-facing decision sentences) but
    no HITL task is recorded for the application — the case where a customer
    would be told their application is progressing with nothing recorded.
    Every other turn on a valid session passes. `stage` carries the rest for
    observability. The flow's final gate matches the bare word in `gate`,
    because a Deterministic MCP node escapes the inner quotes of its JSON
    envelope.
    """
    started = _now_utc()
    print(f"[hitl_status_for_session] called session_token={session_token!r}", flush=True)
    ctx = _get_context_impl(session_token)
    task_id = None
    application = ctx.get("application") or {}
    application_id = application.get("id") if application else None
    if application_id is not None:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(task_id) FROM BANK_CORE.hitl_task WHERE application_id = :a",
                    a=int(application_id),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    task_id = int(row[0])
    out = gate_decision(ctx, task_id, reply)
    _audit("hitl_status_for_session", "SUCCESS", started, _now_utc(),
           {"application_id": application_id}, out, session_token=session_token)
    print(f"[hitl_status_for_session] -> gate={out['gate']} stage={out['stage']} "
          f"task_id={out['task_id']}", flush=True)
    return out


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8503"))
    mcp.run(transport="streamable-http", host=host, port=port)
