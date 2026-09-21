"""Unit tests for research-mcp's pure comparable-case matching.

These run on the host: match.py imports neither fastmcp nor oracledb.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ai" / "research-mcp"))

from match import (  # noqa: E402
    MAX_COMPARABLES,
    bands_for,
    missing_match_keys,
    outcome_split,
)

COMPLETE = {"amount": 20000, "dti": 0.32, "credit_score": 700}


def test_a_complete_case_has_nothing_missing():
    assert missing_match_keys(COMPLETE) == []


@pytest.mark.parametrize("key", ["amount", "dti", "credit_score"])
def test_an_absent_key_is_reported(key):
    case = dict(COMPLETE)
    case[key] = None
    assert missing_match_keys(case) == [key]


@pytest.mark.parametrize("amount", [0, -5000])
def test_a_non_positive_amount_cannot_be_matched_on(amount):
    # A band of +/-25% around zero matches every case ever closed.
    assert missing_match_keys({**COMPLETE, "amount": amount}) == ["amount"]


def test_no_case_at_all_reports_every_key():
    assert missing_match_keys(None) == ["amount", "dti", "credit_score"]


def test_bands_are_centred_on_the_case_under_review():
    assert bands_for(COMPLETE) == {
        "amount_low": 15000.0,
        "amount_high": 25000.0,
        "dti_low": 0.27,
        "dti_high": 0.37,
        "score_low": 660,
        "score_high": 740,
    }


def test_an_incomplete_case_yields_no_bands():
    # Fail closed: a partial window would match on whatever happened to be
    # present, and report the result as "comparable".
    assert bands_for({**COMPLETE, "dti": None}) is None
    assert bands_for(None) is None


def test_outcome_split_counts_how_comparable_cases_were_decided():
    cases = [{"outcome": "APPROVE"}, {"outcome": "DECLINE"}, {"outcome": "APPROVE"}]
    assert outcome_split(cases) == {"APPROVE": 2, "DECLINE": 1}


def test_outcome_split_of_nothing_is_zero_of_each():
    # The summary says "no comparable cases" from this, so both keys are present.
    assert outcome_split([]) == {"APPROVE": 0, "DECLINE": 0}


def test_the_comparable_cap_is_small_enough_to_read():
    assert MAX_COMPARABLES == 6
