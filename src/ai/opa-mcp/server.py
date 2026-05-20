"""OPA MCP server — exposes the decisioning Rego rules as typed MCP tools.

Wires into `CHAT_AGENT` only (per the design's two-agent security model
in DESIGN.md §10). `RESEARCH_AGENT` is read-only and has no MCP tools
attached.

Tool surface (one per Rego rule the agent consumes):
  - required_documents           → decisioning.required_documents
  - evaluate_eligibility         → decisioning.eligibility
  - evaluate_aml                 → decisioning.aml
  - evaluate_kyc                 → decisioning.kyc
  - evaluate_fair_lending_flags  → decisioning.fair_lending
  - lookup_pricing               → decisioning.pricing.quote
  - list_policy_versions         → /v1/policies (audit)

Tool outputs intentionally mirror Rego's signal model — `allow`,
`deny[]`, `warn[]` — so the agent folds them into the recommendation
packet as evidence, not as decision gates.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

import opa_client

mcp = FastMCP("opa-mcp")


@mcp.tool()
def required_documents(
    product_type: str,
    employment_type: str,
    residency: str,
    amount: float,
) -> dict[str, Any]:
    """Required `doc_type` set for an applicant.

    Looked up from `data.decisioning.config.required_documents_matrix`
    keyed by (product_type, employment_type, residency, amount_band).
    """
    result = opa_client.eval_rule(
        "decisioning.required_documents",
        {
            "product_type": product_type,
            "employment_type": employment_type,
            "residency": residency,
            "amount": amount,
        },
    ) or {}
    return {
        "required": result.get("required", []),
        "amount_band": result.get("amount_band"),
        "rationale": result.get("rationale"),
    }


@mcp.tool()
def evaluate_eligibility(
    applicant: dict[str, Any],
    application: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Eligibility evaluation — age / DTI / PTI / score.

    Returns `{allow, deny[], warn[]}`. Each `deny`/`warn` entry is a
    short, human-readable message safe to surface in the agent's
    recommendation reasoning.
    """
    result = opa_client.eval_rule(
        "decisioning.eligibility",
        {"applicant": applicant, "application": application or {}, "product": product or {}},
    ) or {}
    return {
        "allow": bool(result.get("allow", False)),
        "deny": result.get("deny", []),
        "warn": result.get("warn", []),
    }


@mcp.tool()
def evaluate_aml(
    customer: dict[str, Any],
    transactions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """AML — sanctions / PEP / suspicious-pattern flags."""
    result = opa_client.eval_rule(
        "decisioning.aml",
        {"customer": customer, "transactions": transactions or {}},
    ) or {}
    return {
        "allow": bool(result.get("allow", False)),
        "deny": result.get("deny", []),
        "warn": result.get("warn", []),
    }


@mcp.tool()
def evaluate_kyc(
    customer: dict[str, Any],
    documents: list[dict[str, Any]],
    today: str,
) -> dict[str, Any]:
    """KYC — ID validity, doc expiry, OCR quality gates."""
    result = opa_client.eval_rule(
        "decisioning.kyc",
        {"customer": customer, "documents": documents, "today": today},
    ) or {}
    return {
        "allow": bool(result.get("allow", False)),
        "deny": result.get("deny", []),
        "warn": result.get("warn", []),
    }


@mcp.tool()
def evaluate_fair_lending_flags(
    protected_attrs: dict[str, Any],
    decision_draft: dict[str, Any],
    monitored_patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fair-lending pre-flight on a single decision — returns a flag.

    `monitored_patterns` defaults to empty (no false positives in the
    PoC's default state). The institution loads its own patterns when
    wiring this in production.
    """
    result = opa_client.eval_rule(
        "decisioning.fair_lending",
        {
            "protected_attrs": protected_attrs,
            "decision_draft": decision_draft,
            "monitored_patterns": monitored_patterns or [],
        },
    ) or {}
    return {
        "flag": bool(result.get("flag", False)),
        "reason": result.get("reason"),
    }


@mcp.tool()
def lookup_pricing(
    applicant: dict[str, Any],
    application: dict[str, Any],
) -> dict[str, Any]:
    """Indicative pricing — risk-band → rate from the configured card."""
    result = opa_client.eval_rule(
        "decisioning.pricing.quote",
        {"applicant": applicant, "application": application},
    ) or {}
    return result


@mcp.tool()
def list_policy_versions() -> list[dict[str, Any]]:
    """List loaded Rego modules — useful for the per-decision audit."""
    return opa_client.policy_versions()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8500"))
    mcp.run(transport="streamable-http", host=host, port=port)
