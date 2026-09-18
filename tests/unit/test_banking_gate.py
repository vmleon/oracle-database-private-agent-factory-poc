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
    aml_input,
    GATE_OK,
    amount_value,
    announces_a_decision,
    unusable_application_fields,
    documents_payload,
    factors_for,
    gate_decision,
    reason_code,
    tier_from,
    compliance_code,
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


def test_amount_value_is_a_whole_number_when_the_amount_is_whole():
    # The worker reads the amount back to the customer, and a decimal in a reply
    # is a ratio to the disclosure screen, so a whole amount carries no ".0".
    assert amount_value(10000) == 10000
    assert amount_value(10000.0) == 10000
    assert isinstance(amount_value(10000.0), int)
    assert amount_value(1250.5) == 1250.5
    assert amount_value(None) is None


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


# A field that is present but nonsensical is as good as absent: `amount /
# term_months` runs inside the deterministic node every read path starts with.

def test_a_complete_application_has_nothing_unusable():
    assert unusable_application_fields(
        {"amount_requested": 10000, "term_months": 24, "purpose": "Home"}) == []


@pytest.mark.parametrize("term", [0, -6, 0.0])
def test_a_non_positive_term_is_unusable(term):
    assert unusable_application_fields(
        {"amount_requested": 10000, "term_months": term, "purpose": "Home"}) \
        == ["term_months"]


@pytest.mark.parametrize("amount", [0, -5000])
def test_a_non_positive_amount_is_unusable(amount):
    assert unusable_application_fields(
        {"amount_requested": amount, "term_months": 24, "purpose": "Home"}) \
        == ["amount_requested"]


def test_absent_fields_are_still_reported():
    assert unusable_application_fields(
        {"amount_requested": 10000, "term_months": None, "purpose": None}) \
        == ["term_months", "purpose"]
    assert unusable_application_fields(None) == \
        ["amount_requested", "term_months", "purpose"]


def test_a_zero_purpose_is_not_a_number_and_stays_usable():
    # Only the fields a read path divides by are range-checked; a purpose is text.
    assert unusable_application_fields(
        {"amount_requested": 10000, "term_months": 24, "purpose": "0"}) == []


# KYC and AML are hard bars, not signals to weigh: recommending APPROVE beside a
# sanctions match would misinform the human who decides.

CLEAN_ELIGIBILITY = {"deny": [], "warn": []}
ACTIVE_EMPLOYER = {"registered": True, "trading_status": "active"}


def test_a_sanctions_match_declines():
    tier, codes = tier_from(
        CLEAN_ELIGIBILITY, ACTIVE_EMPLOYER,
        aml={"deny": ["Sanctions / watch-list match: PABLO ESCOBAR"], "warn": []})
    assert tier == "DECLINE"
    assert codes == ["SANCTIONS_MATCH"]


def test_a_failed_identity_check_declines():
    tier, codes = tier_from(CLEAN_ELIGIBILITY, ACTIVE_EMPLOYER,
                            kyc={"deny": ["KYC status is FAILED"], "warn": []})
    assert tier == "DECLINE"
    assert codes == ["KYC_FAILED"]


def test_a_pending_check_asks_for_review():
    tier, codes = tier_from(
        CLEAN_ELIGIBILITY, ACTIVE_EMPLOYER,
        kyc={"deny": [], "warn": ["KYC status is PENDING — reviewer should verify"]})
    assert tier == "REVIEW"
    assert codes == ["KYC_PENDING"]


def test_a_politically_exposed_person_asks_for_review():
    tier, codes = tier_from(
        CLEAN_ELIGIBILITY, ACTIVE_EMPLOYER,
        aml={"deny": [], "warn": ["Politically Exposed Person — enhanced due diligence required"]})
    assert tier == "REVIEW"
    assert codes == ["PEP_REVIEW"]


def test_clear_compliance_leaves_the_tier_alone():
    clear = {"allow": True, "deny": [], "warn": []}
    assert tier_from(CLEAN_ELIGIBILITY, ACTIVE_EMPLOYER, clear, clear) == ("APPROVE", [])


def test_absent_compliance_leaves_the_tier_alone():
    # OPA unreachable: the tier must not depend on the policy server being up.
    assert tier_from(CLEAN_ELIGIBILITY, ACTIVE_EMPLOYER, None, None) == ("APPROVE", [])


def test_screening_never_names_itself_to_the_customer():
    # Telling someone screening stopped them is tipping off. The factor phrase
    # for a screening code is the same generic one POLICY_OTHER uses.
    assert factors_for(["SANCTIONS_MATCH"]) == ["your application details"]
    assert factors_for(["PEP_REVIEW"]) == ["your application details"]
    assert factors_for(["AML_PATTERN"]) == ["your application details"]


def test_identity_checks_may_be_named():
    assert factors_for(["KYC_PENDING"]) == ["the identity checks on your application"]
    assert factors_for(["KYC_FAILED"]) == ["the identity checks on your application"]


@pytest.mark.parametrize("message,code", [
    ("Sanctions / watch-list match: PABLO ESCOBAR", "SANCTIONS_MATCH"),
    ("Politically Exposed Person — enhanced due diligence required", "PEP_REVIEW"),
    ("Suspicious pattern: 7 large round outflows in last 30 days", "AML_PATTERN"),
    ("KYC status is FAILED", "KYC_FAILED"),
    ("KYC status is PENDING — reviewer should verify before approval", "KYC_PENDING"),
    ("ID document expired on 2020-01-01", "ID_EXPIRED"),
    ("something nobody mapped", "POLICY_OTHER"),
])
def test_compliance_messages_map_to_stable_codes(message, code):
    assert compliance_code(message) == code


def test_aml_input_carries_the_name_and_the_outflow_count():
    assert aml_input({"name": "Sam RoundNumbers", "large_round_outflows_30d": 6}) == {
        "customer": {"full_name": "Sam RoundNumbers"},
        "transactions": {"large_round_outflows_30d": 6},
    }


def test_aml_input_counts_no_outflows_as_zero():
    assert aml_input({"name": "Alice Salaried"})["transactions"] == {"large_round_outflows_30d": 0}
