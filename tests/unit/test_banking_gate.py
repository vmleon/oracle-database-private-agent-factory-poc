"""Unit tests for banking-mcp's pure decision helpers.

These run on the host: gate.py imports neither fastmcp nor oracledb.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ai" / "banking-mcp"))

from gate import (  # noqa: E402
    GATE_FAIL,
    GATE_OK,
    announces_a_decision,
    documents_payload,
    factors_for,
    gate_decision,
    reason_code,
    tier_from,
)

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


def test_gate_passes_a_complete_application_awaiting_a_decision():
    assert gate_decision(COMPLETE, None) == {
        "gate": GATE_OK, "stage": "AWAITING_DECISION", "task_id": None,
    }


def test_gate_rejects_a_decision_sentence_with_no_recorded_task():
    reply = "Looks strong — it's with our team for final approval; we'll confirm shortly."
    assert gate_decision(COMPLETE, None, reply) == {
        "gate": GATE_FAIL, "stage": "DECISION_NOT_RECORDED", "task_id": None,
    }


def test_gate_passes_a_question_with_no_recorded_task():
    reply = "Please confirm: 18000 over 36 months for home improvement. Shall I submit it?"
    assert gate_decision(COMPLETE, None, reply) == {
        "gate": GATE_OK, "stage": "AWAITING_DECISION", "task_id": None,
    }


def test_gate_passes_a_decision_sentence_when_the_task_exists():
    reply = "Before we can proceed, a specialist needs to review this in detail."
    assert gate_decision(COMPLETE, 42, reply) == {
        "gate": GATE_OK, "stage": "DECIDED", "task_id": 42,
    }


# The worker writes its own wording, so the gate has to recognise a decision in
# whatever words it lands on — including the paraphrases seen in live runs.
@pytest.mark.parametrize("reply", [
    "[[DECISION tier=DECLINE]]\nWe can't take this forward as it stands.",
    "Looks strong — it's with our team for final approval; we'll confirm shortly.",
    "Before we can proceed, a specialist needs to review this in detail.",
    "We'd like a closer look at affordability; a reviewer will follow up.",
    "A specialist will review your application and get back to you shortly.",
    "I've forwarded your request and a reviewer will take a closer look.",
    "Your loan application is being processed and we'll confirm shortly.",
    "I'm sorry, but your loan cannot be submitted right now.",
])
def test_announces_a_decision_detects_the_language_of_a_decision(reply):
    assert announces_a_decision(reply)


@pytest.mark.parametrize("reply", [
    "Please confirm: 18000 over 36 months for home improvement. Shall I submit it?",
    "Welcome! How much would you like to borrow?",
    "Thanks — and over how many months would you like to repay it?",
])
def test_announces_a_decision_ignores_an_intake_turn(reply):
    assert not announces_a_decision(reply)


@pytest.mark.parametrize("codes,expected", [
    ([], []),
    (["DTI_TOO_HIGH"], ["affordability"]),
    (["DTI_TOO_HIGH", "PTI_TOO_HIGH"], ["affordability"]),
    (["SCORE_CAUTION_BAND"], ["your credit history"]),
    (["EMPLOYER_DORMANT"], ["your employer's trading status"]),
    (["SCORE_BELOW_FLOOR", "EMPLOYER_UNVERIFIED"],
     ["your credit history", "your employer's registration"]),
])
def test_factors_for_maps_codes_to_customer_safe_words(codes, expected):
    assert factors_for(codes) == expected


ACTIVE = {"registered": True, "trading_status": "active"}
DORMANT = {"registered": True, "trading_status": "dormant"}
UNREGISTERED = {"registered": False, "trading_status": "unknown"}
CLEAN = {"allow": True, "deny": [], "warn": []}


@pytest.mark.parametrize("eligibility,employer,expected_tier,expected_code", [
    # The seeded scenarios, as the harness asserts them.
    (CLEAN, ACTIVE, "APPROVE", None),
    ({"allow": False, "deny": ["DTI 0.48 exceeds cap 0.45"], "warn": []},
     ACTIVE, "DECLINE", "DTI_TOO_HIGH"),
    ({"allow": False, "deny": ["Credit score 540 below floor 600"], "warn": []},
     ACTIVE, "DECLINE", "SCORE_BELOW_FLOOR"),
    ({"allow": False, "deny": [], "warn": ["Credit score 660 in caution band (< 670)"]},
     ACTIVE, "REVIEW", "SCORE_CAUTION_BAND"),
    (CLEAN, UNREGISTERED, "DECLINE", "EMPLOYER_UNVERIFIED"),
    (CLEAN, DORMANT, "REVIEW", "EMPLOYER_DORMANT"),
])
def test_tier_from(eligibility, employer, expected_tier, expected_code):
    tier, codes = tier_from(eligibility, employer)
    assert tier == expected_tier
    if expected_code is None:
        assert codes == []
    else:
        assert expected_code in codes


def test_deny_outranks_a_warn():
    """A deny and a warn together still DECLINE — deny is evaluated first."""
    tier, codes = tier_from(
        {"allow": False, "deny": ["DTI 0.48 exceeds cap 0.45"],
         "warn": ["Credit score 660 in caution band (< 670)"]}, ACTIVE)
    assert tier == "DECLINE"
    assert {"DTI_TOO_HIGH", "SCORE_CAUTION_BAND"} <= set(codes)


def test_unregistered_employer_outranks_a_dormant_warning():
    tier, codes = tier_from(CLEAN, UNREGISTERED)
    assert tier == "DECLINE"
    assert "EMPLOYER_DORMANT" not in codes


def test_missing_keys_default_to_approve():
    """An empty record must not crash the rule; it carries no adverse signal."""
    assert tier_from({}, {}) == ("APPROVE", [])


@pytest.mark.parametrize("message,code", [
    ("DTI 0.48 exceeds cap 0.45", "DTI_TOO_HIGH"),
    ("PTI 0.30 exceeds cap 0.25", "PTI_TOO_HIGH"),
    ("Credit score 660 in caution band (< 670)", "SCORE_CAUTION_BAND"),
    ("Credit score 540 below floor 600", "SCORE_BELOW_FLOOR"),
    ("Applicant age 17 below minimum", "AGE_OUT_OF_RANGE"),
    ("something the policy added later", "POLICY_OTHER"),
])
def test_reason_code(message, code):
    assert reason_code(message) == code
