"""Unit tests for the bench's conversation-quality signals.

Pure functions over (customer_text, reply, application_row), so the scoring is
reviewable on the host before it judges anything in the cloud.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "conversation"))

import quality  # noqa: E402

ROW = {"amount_requested": 15000.0, "term_months": 36, "purpose": "Debt consolidation"}
EMPTY_ROW = {"amount_requested": None, "term_months": None, "purpose": None}


def test_identical_replies_are_repetitive():
    first = "Could you please confirm you would like to proceed with the loan application?"
    second = "Could you please confirm you would like us to proceed with your loan application?"
    assert quality.is_repetitive(first, second)


def test_different_replies_are_not_repetitive():
    first = "How much would you like to borrow?"
    second = "Thanks — and over how many months would you like to repay it?"
    assert not quality.is_repetitive(first, second)


def test_similarity_bounds():
    assert quality.similarity("", "") == 1.0
    assert quality.similarity("something", "") == 0.0
    assert quality.similarity("a loan please", "a loan please") == 1.0


def test_only_a_question():
    assert quality.only_a_question("How much do you need?")
    assert quality.only_a_question("How much? And over how long?")
    assert not quality.only_a_question("Thanks. How much do you need?")
    assert not quality.only_a_question("")


def test_asks_to_confirm():
    assert quality.asks_to_confirm(
        "Could you please confirm you would like to proceed with the loan application?")
    assert quality.asks_to_confirm("Would you like us to proceed?")
    assert not quality.asks_to_confirm("How much would you like to borrow?")


def test_re_asks_only_what_is_already_known():
    assert quality.re_asks("How much would you like to borrow?", ROW) == ["amount_requested"]
    assert quality.re_asks("How much would you like to borrow?", EMPTY_ROW) == []
    assert quality.re_asks("Over how many months?", ROW) == ["term_months"]
    assert quality.re_asks("Someone will be in touch shortly.", ROW) == []


def test_asks_for_lists_every_field_requested():
    assert quality.asks_for("How much, and over how many months?") == \
        ["amount_requested", "term_months"]


def test_acknowledges_needs_a_content_word():
    assert quality.acknowledges("I want 15000 to consolidate debt",
                                "Got it — 15000 to consolidate your debt.")
    assert not quality.acknowledges("I want 15000 to consolidate debt",
                                    "Please hold while we check.")


def test_length_bounds():
    assert not quality.length_ok("ok")
    assert quality.length_ok("That's noted, thank you.")
    assert not quality.length_ok("x" * 901)


def test_encouragement_reads_the_direction_of_a_reply():
    assert quality.encouragement("Yes, that should be fine.") > 0
    assert quality.encouragement("Unfortunately that is too high.") < 0
    assert quality.encouragement("Someone will look at your application.") == 0


def test_bisection_shows_up_as_a_rising_sequence():
    """The leak the per-reply patterns cannot see: four replies with no digit
    between them that still tell the customer where the cap is."""
    replies = [
        "Unfortunately that is too high for us.",
        "That is still too high, I'm afraid.",
        "That could work.",
        "Yes, that works and should be comfortable.",
    ]
    scores = [quality.encouragement(r) for r in replies]
    assert all(b >= a for a, b in zip(scores, scores[1:]))
