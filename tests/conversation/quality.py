"""Deterministic signals for whether a reply was worth the customer's time.

Pure functions over `(customer_text, reply, application_row)` — stable, free,
and reviewable, which is why they come before the opt-in rubric judge. They
run on the host, so `tests/unit/` covers them with no deployment.

A signal answers one narrow question and returns evidence, never a verdict:
the suite composes them into the property it is asserting.
"""
from __future__ import annotations

import re

STOPWORDS = frozenset("""
a an and are as at be been but by can could do does for from had has have he her
his how i if in is it its me my of on or our so than that the their them then
there they this to up us was we were what when which who will with would you
your de la el los las un una y que es en para con por mi su
""".split())

_WORD = re.compile(r"[\w']+", re.UNICODE)

# What a reply asking for a field looks like. Keyed by the loan_application
# column, so a re-ask is checkable against the row the agent already wrote.
FIELD_QUESTIONS = {
    "amount_requested": re.compile(
        r"(?i)how much|what amount|amount (?:would|do|are) you|"
        r"like to borrow|size of the loan"),
    "term_months": re.compile(
        r"(?i)how long|how many months|over what (?:period|term)|"
        r"repayment (?:period|term)|term would you"),
    "purpose": re.compile(
        r"(?i)what (?:is|will|would) .{0,30}\b(?:for|purpose)\b|"
        r"what do you need (?:it|the (?:money|loan)) for|purpose of"),
}

_CONFIRMS = re.compile(
    r"(?i)(?:could|can|would) you (?:please )?confirm|"
    r"just to confirm|would you like (?:to|us to) (?:proceed|continue|go ahead)|"
    r"(?:do you )?confirm that you")

_POSITIVE = re.compile(
    r"(?i)\b(yes|that works|we can|should be fine|looks good|looks strong|"
    r"affordable|manageable|comfortable|within reach)\b")
_NEGATIVE = re.compile(
    r"(?i)\b(no|unfortunately|too high|too large|cannot|can(?:'|’)?t|"
    r"unable|not (?:possible|affordable|something))\b")


def tokens(text: str) -> list[str]:
    """Lowercased words, punctuation dropped."""
    return [m.group(0).lower() for m in _WORD.finditer(text or "")]


def content_tokens(text: str) -> set[str]:
    """The words that carry meaning — stopwords removed, order discarded, and a
    trailing plural `s` dropped so "how long does this take" and "processing
    takes two days" are recognised as the same subject."""
    return {t.rstrip("s") if len(t) > 3 else t
            for t in tokens(text) if t not in STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Token-set overlap of two replies, 0.0 to 1.0. Two empty replies are
    identical; one empty reply shares nothing."""
    first, second = content_tokens(a), content_tokens(b)
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def is_repetitive(previous: str, reply: str, threshold: float = 0.8) -> bool:
    """True when a reply says what the one before it already said."""
    return similarity(previous, reply) >= threshold


def only_a_question(text: str) -> bool:
    """True when the reply asks and says nothing else — every sentence in it
    ends in a question mark."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]
    return bool(sentences) and all(s.endswith("?") for s in sentences)


def asks_to_confirm(text: str) -> bool:
    """True when the reply asks the customer to confirm something. On a turn
    where they just said it, that is a stall."""
    return bool(_CONFIRMS.search(text or ""))


def re_asks(reply: str, application_row: dict | None) -> list[str]:
    """The fields the reply asks for that the application already holds."""
    row = application_row or {}
    return [field for field, pattern in FIELD_QUESTIONS.items()
            if row.get(field) is not None and pattern.search(reply or "")]


def asks_for(reply: str) -> list[str]:
    """Every field the reply asks for, whether or not it is already known."""
    return [field for field, pattern in FIELD_QUESTIONS.items()
            if pattern.search(reply or "")]


def acknowledges(customer_text: str, reply: str) -> bool:
    """True when the reply refers to what the customer actually said."""
    said = content_tokens(customer_text)
    return bool(said and said & content_tokens(reply))


def length_ok(text: str, low: int = 15, high: int = 900) -> bool:
    """A reply too short to mean anything, or long enough to be a wall."""
    return low <= len((text or "").strip()) <= high


def encouragement(text: str) -> int:
    """How encouraging a reply reads, as affirmatives minus negatives.

    A customer bisecting for a cap learns it from the *shape* of a sequence of
    these, without any single reply containing a digit — which is the leak the
    per-reply patterns cannot see.
    """
    return len(_POSITIVE.findall(text or "")) - len(_NEGATIVE.findall(text or ""))
