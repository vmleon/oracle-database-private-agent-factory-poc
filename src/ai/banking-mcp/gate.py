"""Pure decision helpers for the session-scoped banking-mcp tools.

Free of fastmcp and oracledb so the logic can be unit-tested on the host,
where neither package is installed.
"""

from __future__ import annotations

from typing import Any

GATE_OK = "GATE_OK"
GATE_FAIL = "GATE_FAIL"


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


def gate_decision(context: dict[str, Any], task_id: int | None) -> dict[str, Any]:
    """Decide whether this turn is safe to show the customer.

    The gate passes any turn carried on a valid session and fails only when
    the session itself is invalid. The flow's final gate matches the bare
    word in `gate`. `stage` reports where the application stands —
    collecting, awaiting a decision, or decided — for observability.
    """
    if context.get("error"):
        return {"gate": GATE_FAIL, "stage": "INVALID_SESSION", "task_id": None}
    application = context.get("application") or {}
    if not application or application.get("missing"):
        return {"gate": GATE_OK, "stage": "COLLECTING", "task_id": None}
    if task_id is not None:
        return {"gate": GATE_OK, "stage": "DECIDED", "task_id": task_id}
    return {"gate": GATE_OK, "stage": "AWAITING_DECISION", "task_id": None}
