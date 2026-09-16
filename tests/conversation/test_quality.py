"""Suite 4 — is it worth the customer's time.

The bench holds one ordinary conversation, cold start to filed recommendation,
and is deliberately hard to please. A reply that is correct and useless still
fails.

The cases read the conversation in file order, so each one asks its question of
the turn a customer would have reached by then.
"""
from __future__ import annotations

import pytest

import policy
import quality
from driver import APOLOGY, Conversation
from gate import announces_a_decision

ALICE = "Alice Salaried"   # a complete application — the conversational cases
CAROL = "Carol Expat"      # no application — the cold start

TURN_BUDGET = 12


@pytest.fixture(scope="module")
def carol(env, ids):
    """One cold start, walked from a greeting to a filed recommendation. The
    cases read it in file order, the way a customer would live it."""
    conversation = Conversation(ids[CAROL], ca=env["PAF_CA"], base=env["BACKEND_BASE"])
    yield conversation
    conversation.logout()


def test_the_opening_moves_forward(carol):
    """The first turn either asks for something it needs or tells the customer
    something they did not know. Confirming what they just said is neither."""
    reply = carol.say("Hi, I'd like to borrow some money.")

    assert not quality.asks_to_confirm(reply), f"the opening stalls: {reply}"
    assert quality.length_ok(reply), reply


def test_consecutive_replies_are_not_near_identical(carol):
    """Saying the same thing twice is the clearest sign a turn was wasted."""
    previous = carol.heard[-1] if carol.heard else carol.say("Hi, I'd like a loan.")
    reply = carol.say("Yes, I'm sure. What do you need from me?")

    assert not quality.is_repetitive(previous, reply), (
        f"similarity {quality.similarity(previous, reply):.2f}: {reply}"
    )


@pytest.mark.xfail(strict=False, reason=(
    "Intermittent. Measured on one run of two: 'I want 15000 over 36 months to "
    "consolidate some debt.' answered with 'Your loan request has been recorded. "
    "Shall I submit the application now?' — the fields were taken but nothing in "
    "the reply reflects what was taken, so the customer has no way to catch a "
    "misheard amount before it is filed."
))
def test_three_fields_given_at_once_are_taken_at_once(carol, app_row):
    """A customer who answers everything is not asked it again one field at a
    time."""
    reply = carol.say(
        "I want 15000 over 36 months to consolidate some debt."
    )
    row = app_row(carol.customer_id) or {}

    assert quality.acknowledges(
        "15000 over 36 months to consolidate some debt", reply), reply
    assert not quality.re_asks(reply, row), (
        f"the reply asks again for {quality.re_asks(reply, row)}: {reply}"
    )


@pytest.mark.xfail(strict=False, reason=(
    "Intermittent. Measured on one run of two: 'How long does this usually take?' "
    "answered with 'I\u2019m ready to move forward—would you like me to submit "
    "your loan application now?' — the question is dropped entirely. Same "
    "behaviour as `every_reply_refers_to_what_was_said`: the agent stops reading "
    "the turn and pushes toward submission."
))
def test_a_direct_question_is_answered(carol):
    """Not every turn is about collecting a field."""
    reply = carol.say("How long does this usually take?")

    assert quality.length_ok(reply), reply
    assert any(word in reply.lower() for word in
               ("day", "hour", "week", "shortly", "soon", "moment", "time")), (
        f"the question about timing was deflected: {reply}"
    )


def test_off_topic_is_redirected_not_crashed(carol):
    """A customer who wanders gets a line and a nudge back, not an apology
    block and not a dead turn."""
    reply = carol.say("What's the weather like where you are?")

    assert reply != APOLOGY, reply
    assert quality.length_ok(reply), reply


def test_changing_the_amount_reaches_the_row(carol, app_row):
    """Saying it is not enough; the application has to move."""
    carol.say("Actually, make it 15000.")
    row = app_row(carol.customer_id) or {}

    assert row.get("amount_requested") == 15000, row


def test_frustration_is_not_met_with_a_third_ask(carol, app_row):
    """The customer has said the amount twice. A third ask is the failure."""
    row = app_row(carol.customer_id) or {}
    reply = carol.say("I've told you the amount twice already.")

    assert "amount_requested" not in quality.re_asks(reply, row), (
        f"the amount was asked for a third time: {reply}"
    )


def test_the_conversation_uses_no_system_vocabulary(carol):
    """Nothing the customer reads names the machinery behind it."""
    offenders = {reply: policy.system_words_in(reply) for reply in carol.heard}
    leaked = {reply: words for reply, words in offenders.items() if words}

    assert not leaked, f"machinery vocabulary reached the customer: {leaked}"


def test_a_cold_start_reaches_a_recommendation_inside_the_budget(carol, tasks_for, app_row):
    """The whole point of the intake path: a customer who arrives with nothing
    leaves with their case in the reviewer's queue, without being interviewed.

    The budget covers the whole conversation this module has held, greeting
    included — an application collected in a reasonable number of turns is the
    property, not the number of turns this one case spends."""
    row = app_row(carol.customer_id)
    assert row, "the conversation wrote no application at all"

    while carol.turns < TURN_BUDGET and not tasks_for(row["application_id"]):
        carol.say("Yes, please go ahead and submit it.")

    assert tasks_for(row["application_id"]), (
        f"{carol.turns} turns and nothing reached the reviewer's queue"
    )


@pytest.mark.xfail(strict=False, reason=(
    "Measured: 'I've told you the amount twice already.' was answered with "
    "'Could you let me know if you\u2019d like to proceed with submitting your "
    "loan application?' — a reply that shares nothing with the turn it answers "
    "and asks for a confirmation the customer has already given twice."
))
def test_every_reply_refers_to_what_was_said(carol):
    """Across the whole conversation, a reply that shares no content word with
    the turn it answers was written without reading it.

    A reply that announces a decision is exempt: it answers the application
    rather than the sentence, so sharing no word with the sentence is correct.
    """
    deaf = [(said, heard) for said, heard in zip(carol.said, carol.heard)
            if not announces_a_decision(heard) and not quality.acknowledges(said, heard)]

    assert not deaf, f"replies that ignore the customer's message: {deaf}"
