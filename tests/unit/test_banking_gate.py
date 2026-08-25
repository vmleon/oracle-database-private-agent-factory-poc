"""Unit tests for banking-mcp's pure decision helpers.

These run on the host: gate.py imports neither fastmcp nor oracledb.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ai" / "banking-mcp"))

from gate import GATE_FAIL, GATE_OK, documents_payload, gate_decision  # noqa: E402

COMPLETE = {
    "customer": {"residency": "resident"},
    "application": {"product_type": "PERSONAL_LOAN", "amount_requested": 10000, "missing": []},
    "profile": {"employment_type": "salaried"},
}
COLLECTING = {
    "customer": {"residency": "resident"},
    "application": {"product_type": "PERSONAL_LOAN", "amount_requested": None,
                    "missing": ["amount_requested"]},
    "profile": {"employment_type": "salaried"},
}
NO_APP = {"customer": {"residency": "resident"}, "application": None,
          "profile": {"employment_type": "salaried"}}
BAD = {"error": "invalid_or_expired_session"}


def test_documents_payload_builds_the_opa_input():
    assert documents_payload(COMPLETE) == {
        "product_type": "PERSONAL_LOAN",
        "employment_type": "salaried",
        "residency": "resident",
        "amount": 10000,
    }


@pytest.mark.parametrize("ctx", [COLLECTING, NO_APP, BAD], ids=["collecting", "no-app", "bad"])
def test_documents_payload_is_none_when_the_application_is_not_complete(ctx):
    assert documents_payload(ctx) is None


def test_gate_fails_on_an_invalid_session():
    assert gate_decision(BAD, None) == {"gate": GATE_FAIL, "stage": "INVALID_SESSION", "task_id": None}


@pytest.mark.parametrize("ctx", [COLLECTING, NO_APP], ids=["collecting", "no-app"])
def test_gate_passes_a_collecting_turn_with_no_decision(ctx):
    assert gate_decision(ctx, None) == {"gate": GATE_OK, "stage": "COLLECTING", "task_id": None}


def test_gate_passes_a_complete_application_with_a_recorded_decision():
    assert gate_decision(COMPLETE, 42) == {"gate": GATE_OK, "stage": "DECIDED", "task_id": 42}


def test_gate_fails_a_complete_application_with_no_decision():
    assert gate_decision(COMPLETE, None) == {
        "gate": GATE_FAIL, "stage": "DECISION_MISSING", "task_id": None,
    }
