"""Pure decision helpers for the session-scoped banking-mcp tools.

Free of fastmcp and oracledb so the logic can be unit-tested on the host,
where neither package is installed.
"""

from __future__ import annotations

from typing import Any

GATE_OK = "GATE_OK"
GATE_FAIL = "GATE_FAIL"

# The customer-facing decision sentences, matched as substrings. These must stay
# in step with the Recommendation worker's Custom Instructions in
# paf/flows/CHAT_FLOW.md and with TIER_REPLY in tests/test_chat_workflow.py.
DECISION_PHRASES = (
    "final approval",
    "a reviewer will follow up",
    "a specialist needs to review",
)


def announces_a_decision(reply: str) -> bool:
    """True when a reply carries one of the customer-facing decision sentences."""
    text = (reply or "").lower()
    return any(phrase in text for phrase in DECISION_PHRASES)


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
