"""Pure decision helpers for the session-scoped banking-mcp tools.

Free of fastmcp and oracledb so the logic can be unit-tested on the host,
where neither package is installed.
"""

from __future__ import annotations

import re
from typing import Any

GATE_OK = "GATE_OK"
GATE_FAIL = "GATE_FAIL"

# What an application needs before anything can be derived from it.
REQUIRED_APPLICATION_FIELDS = ("amount_requested", "term_months", "purpose")
# Of those, the ones a read path divides by or multiplies out. Zero and negative
# are as unusable as absent — `amount / term_months` runs on every read path.
_POSITIVE_APPLICATION_FIELDS = ("amount_requested", "term_months")

# The Recommendation worker writes its own sentence, so a decision turn is
# recognised by the language a decision uses, not by one fixed string. The
# worker also prefixes `[[DECISION tier=...]]`, which the backend strips before
# the customer sees the reply — that marker is the exact signal, and the
# patterns below catch a decision announced without it.
DECISION_MARKER = re.compile(r"\[\[\s*DECISION\b", re.IGNORECASE)
DECISION_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bfinal approval\b",
    r"\b(?:a|our|the)\s+(?:reviewer|specialist|review team)\b",
    r"\b(?:reviewer|specialist)\s+will\b",
    r"\bcloser look\b",
    r"\bbeing processed\b",
    r"\b(?:we(?:'|’)?ll|we will)\s+(?:confirm|be in touch|get back)\b",
    r"\bget back to you\b",
    r"\bcannot\s+(?:be submitted|proceed|go ahead)\b",
    r"\b(?:forwarded|submitted)\s+(?:it|this|your)\b",
))

# What a customer may be told a decision turned on: the factor, never the
# number behind it. Keyed by the reason codes `tier_from` produces.
CUSTOMER_FACTORS = {
    "DTI_TOO_HIGH": "affordability",
    "PTI_TOO_HIGH": "affordability",
    "INCOME_INSUFFICIENT": "affordability",
    "SCORE_BELOW_FLOOR": "your credit history",
    "SCORE_CAUTION_BAND": "your credit history",
    "AGE_OUT_OF_RANGE": "your eligibility for this product",
    "EMPLOYER_UNVERIFIED": "your employer's registration",
    "EMPLOYER_DORMANT": "your employer's trading status",
    "POLICY_OTHER": "your application details",
}


def announces_a_decision(reply: str) -> bool:
    """True when a reply tells the customer where their application stands."""
    text = reply or ""
    if DECISION_MARKER.search(text):
        return True
    return any(pattern.search(text) for pattern in DECISION_PATTERNS)


def unusable_application_fields(application: dict[str, Any] | None) -> list[str]:
    """The fields a read path cannot work with.

    A field that is present but nonsensical is as good as absent: the
    application is not ready to derive a payment from, and the agent should
    collect the value again rather than the read path dividing by it. Guarding
    on `is None` alone is what let a term of zero reach `amount / term_months`
    inside the deterministic node every read path starts with.
    """
    row = application or {}
    unusable: list[str] = []
    for field in REQUIRED_APPLICATION_FIELDS:
        value = row.get(field)
        if value is None:
            unusable.append(field)
        elif field in _POSITIVE_APPLICATION_FIELDS and float(value) <= 0:
            unusable.append(field)
    return unusable


def factors_for(codes: list[str] | None) -> list[str]:
    """The customer-safe factor phrases for a set of reason codes, in order and
    without repeats. The Recommendation worker may name these and nothing else —
    no number, threshold or code ever reaches the customer."""
    factors: list[str] = []
    for code in codes or []:
        factor = CUSTOMER_FACTORS.get(code)
        if factor and factor not in factors:
            factors.append(factor)
    return factors


def documents_payload(context: dict[str, Any]) -> dict[str, Any] | None:
    """Build the OPA `decisioning.required_documents` input from a context.

    Returns None when the application is absent or still collecting, so the
    caller fails closed instead of evaluating a partial payload.
    """
    if context.get("error"):
        return None
    application = context.get("application") or {}
    if not application or application.get("missing"):
        return None
    profile = context.get("profile") or {}
    customer = context.get("customer") or {}
    return {
        "product_type": application.get("product_type") or "PERSONAL_LOAN",
        "employment_type": profile.get("employment_type"),
        "residency": customer.get("residency"),
        "amount": application.get("amount_requested"),
    }


def gate_decision(
    context: dict[str, Any], task_id: int | None, reply: str = ""
) -> dict[str, Any]:
    """Decide whether this turn is safe to show the customer.

    Rejects an invalid session, and rejects a reply that announces a decision
    when no HITL task exists for the application — the case where a customer
    would be told their application is progressing with nothing recorded.
    Every other turn on a valid session passes; `stage` reports where the
    application stands.
    """
    if context.get("error"):
        return {"gate": GATE_FAIL, "stage": "INVALID_SESSION", "task_id": None}
    if task_id is not None:
        return {"gate": GATE_OK, "stage": "DECIDED", "task_id": task_id}
    if announces_a_decision(reply):
        return {"gate": GATE_FAIL, "stage": "DECISION_NOT_RECORDED", "task_id": None}
    application = context.get("application") or {}
    if not application or application.get("missing"):
        return {"gate": GATE_OK, "stage": "COLLECTING", "task_id": None}
    return {"gate": GATE_OK, "stage": "AWAITING_DECISION", "task_id": None}

def tier_from(eligibility: dict, employer: dict) -> tuple[str, list[str]]:
    """The recommendation tier and its reason codes — a pure function of the
    server-computed eligibility and employer records. No model decides this."""
    deny = eligibility.get("deny") or []
    warn = eligibility.get("warn") or []
    registered = employer.get("registered")
    status = (employer.get("trading_status") or "").lower()
    codes: list[str] = []
    for message in deny:
        codes.append(reason_code(message))
    for message in warn:
        codes.append(reason_code(message))
    if registered is False:
        codes.append("EMPLOYER_UNVERIFIED")
    elif status == "dormant":
        codes.append("EMPLOYER_DORMANT")
    if deny or registered is False:
        return "DECLINE", codes
    if warn or status == "dormant":
        return "REVIEW", codes
    return "APPROVE", codes


def reason_code(message: str) -> str:
    """Map an OPA message to a stable reason code for the reviewer's queue."""
    text = (message or "").lower()
    if "dti" in text:
        return "DTI_TOO_HIGH"
    if "pti" in text:
        return "PTI_TOO_HIGH"
    if "caution band" in text:
        return "SCORE_CAUTION_BAND"
    if "score" in text:
        return "SCORE_BELOW_FLOOR"
    if "age" in text:
        return "AGE_OUT_OF_RANGE"
    if "income" in text:
        return "INCOME_INSUFFICIENT"
    return "POLICY_OTHER"
