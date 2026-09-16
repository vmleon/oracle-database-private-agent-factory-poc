"""The rubric judge, off by default.

`python manage.py cloud bench` deselects this module; `cloud bench -m judge`
runs it alone. It holds its own short conversation so the deterministic suites
never pay for it.
"""
from __future__ import annotations

import pytest

import judge
from driver import Conversation

CAROL = "Carol Expat"
FLOOR = 3  # below this the exchange was not worth the customer's turn

pytestmark = pytest.mark.judge

EXCHANGES = [
    "Hi, I'd like to borrow some money.",
    "I want 15000 over 36 months to consolidate some debt.",
    "How long does this usually take?",
]


@pytest.fixture(scope="module")
def scored(env, ids):
    reason = judge.available()
    if reason:
        pytest.skip(f"the judge cannot run: {reason}")
    conversation = Conversation(ids[CAROL], ca=env["PAF_CA"], base=env["BACKEND_BASE"])
    try:
        results = []
        for said in EXCHANGES:
            reply = conversation.say(said)
            results.append((said, reply, judge.score(said, reply)))
        return results
    finally:
        conversation.logout()


@pytest.mark.parametrize("index", range(len(EXCHANGES)))
def test_the_exchange_was_worth_the_turn(scored, index):
    said, reply, scores = scored[index]
    weak = {name: value for name, value in scores.items() if value < FLOOR}
    assert not weak, f"{said!r} -> {reply!r} scored {scores}"
