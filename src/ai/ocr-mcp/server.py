"""OCR MCP server (STUB) — placeholder for the YOLO + PaddleOCR pipeline.

Returns canned OCR results keyed on the filename in `storage_uri`. The
canned table is aligned with the documents seeded by
`010-seed-synthetic.yaml` and the test-bench scenarios in
`docs/DECISIONING-ENGINE-USE-CASE.md §Scenarios`:

  - `henry-payslip.pdf`     → PAYSLIP, MARGINAL (scenario 8)
  - `iris-id.pdf`           → ID, UNUSABLE     (scenario 9)
  - `iris-payslip.pdf`      → PAYSLIP, UNUSABLE (scenario 9)
  - `iris-statement.pdf`    → STATEMENT, UNUSABLE (scenario 9)
  - `alice-payslip.pdf`     → PAYSLIP, USABLE  (smoke / 002 seed)
  - anything else           → falls through to a USABLE default whose
                              doc_type is inferred from a substring match
                              on the filename, with synthetic field data.

This stub bypasses the async OCR_REQUEST queue path entirely — the agent
gets a synchronous extraction result. Real OCR (YOLO classifier +
PaddleOCR/Tesseract, async via OCR_REQUEST → worker → write-back to
APP.loan_application_document) is a separate workstream.

Wires into `CHAT_WORKFLOW` only, same as opa-mcp. `RESEARCH_WORKFLOW` is
read-only and has no MCP tools.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP

mcp = FastMCP("ocr-mcp")


# Canned responses for the seeded documents. Keys are the basename of the
# storage_uri; matched case-insensitively.
_CANNED: dict[str, dict[str, Any]] = {
    "alice-payslip.pdf": {
        "doc_type": "PAYSLIP",
        "quality_tier": "USABLE",
        "ocr_confidence": 0.95,
        "ocr_payload": {
            "employer": "Acme Tech Ltd",
            "pay_period": "2026-04",
            "gross_amount": 5500.00,
            "net_amount": 4280.00,
            "currency": "USD",
        },
        "note": "Smoke-seed payslip; clean extraction.",
    },
    "henry-payslip.pdf": {
        "doc_type": "PAYSLIP",
        "quality_tier": "MARGINAL",
        "ocr_confidence": 0.55,
        "ocr_payload": {
            "employer": "Wayne Enterprises",
            "pay_period": "2026-04",
            "gross_amount": 6000.00,
            "net_amount": None,
            "currency": "USD",
            "low_confidence_fields": ["net_amount"],
        },
        "note": "Scenario 8: one field below confidence threshold — agent should ask for re-upload before recommending.",
    },
    "iris-id.pdf": {
        "doc_type": "ID",
        "quality_tier": "UNUSABLE",
        "ocr_confidence": 0.20,
        "ocr_payload": {
            "name": None,
            "date_of_birth": None,
            "id_number": None,
            "expiry_date": None,
            "low_confidence_fields": ["name", "date_of_birth", "id_number", "expiry_date"],
        },
        "note": "Scenario 9: image quality below readable threshold.",
    },
    "iris-payslip.pdf": {
        "doc_type": "PAYSLIP",
        "quality_tier": "UNUSABLE",
        "ocr_confidence": 0.18,
        "ocr_payload": {
            "employer": None,
            "pay_period": None,
            "gross_amount": None,
            "net_amount": None,
            "low_confidence_fields": ["employer", "pay_period", "gross_amount", "net_amount"],
        },
        "note": "Scenario 9: image quality below readable threshold.",
    },
    "iris-statement.pdf": {
        "doc_type": "STATEMENT",
        "quality_tier": "UNUSABLE",
        "ocr_confidence": 0.22,
        "ocr_payload": {
            "account_number": None,
            "period_start": None,
            "period_end": None,
            "ending_balance": None,
            "low_confidence_fields": ["account_number", "period_start", "period_end", "ending_balance"],
        },
        "note": "Scenario 9: image quality below readable threshold.",
    },
}


# Substring → (doc_type, synthetic_fields) for the fallback path.
_TYPE_HINTS: list[tuple[str, str]] = [
    ("payslip", "PAYSLIP"),
    ("tax",     "TAX_RETURN"),
    ("statement", "STATEMENT"),
    ("address", "ADDRESS_PROOF"),
    ("id",      "ID"),
]


def _basename(storage_uri: str) -> str:
    path = urlparse(storage_uri).path or storage_uri
    return path.rsplit("/", 1)[-1].lower()


def _infer_doc_type(name: str, requested_doc_type: str | None) -> str:
    if requested_doc_type:
        return requested_doc_type.upper()
    for needle, doc_type in _TYPE_HINTS:
        if needle in name:
            return doc_type
    return "OTHER"


def _synthetic_payload(doc_type: str) -> dict[str, Any]:
    """Plausible-looking extracted fields for USABLE fallback responses."""
    if doc_type == "PAYSLIP":
        return {
            "employer": "Synthetic Employer Ltd",
            "pay_period": "2026-04",
            "gross_amount": 5000.00,
            "net_amount": 3900.00,
            "currency": "USD",
        }
    if doc_type == "ID":
        return {
            "name": "Synthetic Holder",
            "date_of_birth": "1985-01-01",
            "id_number": "ID-0000-0000",
            "expiry_date": "2031-01-01",
        }
    if doc_type == "STATEMENT":
        return {
            "account_number": "0000-1234",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "ending_balance": 4200.00,
        }
    if doc_type == "TAX_RETURN":
        return {
            "tax_year": 2025,
            "filing_status": "single",
            "total_income": 60000.00,
        }
    if doc_type == "ADDRESS_PROOF":
        return {
            "address": "1 Synthetic Street, Demo City",
            "issued_at": "2026-02-15",
        }
    return {"raw_text": "synthetic placeholder content"}


@mcp.tool()
def extract_document(
    storage_uri: str,
    requested_doc_type: str | None = None,
) -> dict[str, Any]:
    """Classify a document and extract its structured fields.

    STUB IMPLEMENTATION. Returns canned data keyed on the filename in
    `storage_uri`; falls back to a USABLE synthetic response whose
    `doc_type` is inferred from a substring match on the filename or from
    the optional `requested_doc_type` hint.

    Returns:
        {
            "doc_type":       "ID" | "PAYSLIP" | "STATEMENT" | "TAX_RETURN" | "ADDRESS_PROOF" | "OTHER",
            "quality_tier":   "USABLE" | "MARGINAL" | "UNUSABLE",
            "ocr_confidence": float in [0, 1],
            "ocr_payload":    dict of extracted fields,
            "note":           short human-readable explanation (stub-only),
        }
    """
    name = _basename(storage_uri)
    canned = _CANNED.get(name)
    if canned is not None:
        return {"storage_uri": storage_uri, **canned}

    doc_type = _infer_doc_type(name, requested_doc_type)
    return {
        "storage_uri": storage_uri,
        "doc_type": doc_type,
        "quality_tier": "USABLE",
        "ocr_confidence": 0.90,
        "ocr_payload": _synthetic_payload(doc_type),
        "note": "Fallback USABLE response from the OCR stub — real pipeline not yet wired.",
    }


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8501"))
    mcp.run(transport="streamable-http", host=host, port=port)
