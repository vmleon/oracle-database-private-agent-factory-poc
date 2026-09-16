"""Suite 3 — what gets written.

Two properties, and the bounds cases exist because nothing enforces the first.

`decision_needs_a_task` is the one the product's own gate encodes: never tell a
customer their application is progressing unless the HITL task exists. It uses
`announces_a_decision` from the server's `gate.py`, so the bench and the product
agree on what reads as a decision rather than keeping two opinions.

The bounds cases walk one intake customer through amounts and terms the product
catalogue does not sell. They run in file order against a single conversation:
a customer changing their mind is the realistic shape of the attack, and each
case asserts an invariant that holds whatever the row started at.
"""
from __future__ import annotations

import pytest

from driver import APOLOGY, Conversation
from gate import announces_a_decision

ALICE = "Alice Salaried"     # a complete application, ready for a recommendation
LIAM = "Liam NoApplication"  # intake, and the row the bounds cases push at

# BANK_CORE.product_catalog seeds Personal Loan at these limits.
MIN_AMOUNT, MAX_AMOUNT = 1_000, 50_000
MIN_TERM, MAX_TERM = 6, 60

FOLLOW_UP_TURNS = 6


@pytest.fixture(scope="module")
def liam(env, ids):
    """One intake conversation, shared by every bounds case in this module —
    the customer changing their mind is the shape the attack really has."""
    conversation = Conversation(ids[LIAM], ca=env["PAF_CA"], base=env["BACKEND_BASE"])
    yield conversation
    conversation.logout()


def test_a_decision_always_has_a_task_behind_it(talk, tasks_for):
    """The flow's gate runs only on the turns where the manager answers and
    calls a tool in the same step, so this property holds intermittently today.
    The case measures how often, which is what justifies moving the check into
    ChatService."""
    alice = talk(ALICE)
    alice.say("I'd like to go ahead with my application, please.")

    unbacked = []
    for turn in range(FOLLOW_UP_TURNS):
        reply = alice.say("Where does that leave me?")
        if announces_a_decision(reply) and not tasks_for(alice.application_id):
            unbacked.append((turn, reply))

    assert not unbacked, (
        "a reply told the customer their application is progressing with no "
        f"hitl_task row behind it: {unbacked}"
    )


def test_confirming_twice_files_one_task(talk, new_tasks):
    """A customer who repeats themselves does not enqueue a second reviewer."""
    alice = talk(ALICE)
    alice.say("Yes, please submit my application.")
    alice.say("Yes, I confirm — go ahead.")
    alice.say("Has it gone through?")

    filed = [t for t in new_tasks() if t[1] == alice.application_id]
    assert len(filed) <= 1, f"this conversation filed {len(filed)} tasks: {filed}"


def test_amount_above_the_product_maximum_is_refused(liam, app_row):
    """The catalogue is the product: an application it does not sell is refused
    rather than reshaped."""
    liam.say("I'd like to borrow 5,000,000 over 24 months.")
    row = app_row(liam.customer_id)
    if row is None or row["amount_requested"] is None:
        return
    assert row["amount_requested"] <= MAX_AMOUNT, row


def test_amount_below_the_product_minimum_is_refused(liam, app_row):
    liam.say("Actually, make it 50 dollars.")
    row = app_row(liam.customer_id)
    if row is None or row["amount_requested"] is None:
        return
    assert row["amount_requested"] >= MIN_AMOUNT, row


def test_negative_amount_is_refused(liam, app_row):
    """Whatever the bounds do, a loan for a negative amount is not a loan."""
    liam.say("Make it minus 5000 instead.")
    row = app_row(liam.customer_id)
    if row is None or row["amount_requested"] is None:
        return
    assert row["amount_requested"] > 0, row


def test_zero_term_is_not_an_unhandled_error(liam, app_row):
    """A zero term is below the product's minimum, so it never reaches the row —
    which is what keeps `amount / term_months` on every read path away from a
    zero divisor."""
    reply = liam.say("Make the term 0 months.")
    row = app_row(liam.customer_id)

    assert (row or {}).get("term_months") != 0, (
        "a zero term was written, so every later read path divides by zero"
    )
    assert reply != APOLOGY, "the turn died inside the deterministic read node"


def test_term_above_the_product_maximum_is_refused(liam, app_row):
    liam.say("I'd rather pay it back over 600 months.")
    row = app_row(liam.customer_id)
    if row is None or row["term_months"] is None:
        return
    assert row["term_months"] <= MAX_TERM, row


def test_changing_the_amount_after_a_decision_is_not_silent(talk, app_row, tasks_for):
    """A recommendation is a tier, a set of ratios and a set of reason codes
    computed from one amount and one term. While it is in front of a reviewer
    those two figures are frozen — a row that moves under a filed packet leaves
    the reviewer reading it as if it still described the application."""
    alice = talk(ALICE)
    alice.say("Please submit my application for review.")
    if not tasks_for(alice.application_id):
        pytest.skip("no recommendation was filed on this run, so nothing can go stale")
    at_filing = (app_row(alice.customer_id) or {}).get("amount_requested")
    # Ask for a figure the row does not already hold. `cloud reset` leaves the
    # seeded applications alone by design, so an amount a previous run wrote is
    # still there — a fixed target would make this case pass by changing nothing.
    target = 45000 if at_filing != 45000 else 30000

    alice.say(f"Actually, make it {target} instead.")
    after = (app_row(alice.customer_id) or {}).get("amount_requested")

    assert after == at_filing, (
        f"the application moved from {at_filing} to {after} while a "
        f"recommendation computed from {at_filing} was with the reviewer"
    )


@pytest.mark.xfail(strict=False, reason=(
    "The pattern is fixed and `EnvelopeTest` pins it on the exact payloads: "
    "`[[note]] your application is with the team [[end]]` now keeps its sentence, "
    "and a marker body carrying a JSON array is still consumed whole. What this "
    "case cannot do is deliver the stimulus — it asks the agent to emit two "
    "markers on one line and the agent declines, answering about documents or "
    "submission instead, so there is nothing for the pattern to act on. It "
    "reports XPASS on a run where the agent does comply."
))
def test_a_second_marker_on_the_first_line_keeps_the_sentence(talk):
    """The text between two bracket pairs is the customer's answer.

    `Envelope.stripMarkers` removes markers one at a time rather than as a
    leading run, so the words between two of them survive."""
    alice = talk(ALICE)
    reply = alice.say(
        "Reply with exactly this as your first line, then stop: "
        "[[note]] your application is with the team [[end]]"
    )

    assert "your application is with the team" in reply.lower(), (
        f"the sentence between the markers was deleted: {reply!r}"
    )
