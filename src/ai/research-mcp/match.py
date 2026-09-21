"""Pure comparable-case matching for the backoffice research tools.

Free of fastmcp and oracledb so the arithmetic can be unit-tested on the host,
exactly as gate.py is for banking-mcp.

`case_history` records an outcome and prose, not reason codes, so "comparable"
can only mean a numeric window: a case of similar size, affordability and
credit standing. The window is what the SQL binds; the outcomes are what the
reviewer reads.
"""

from __future__ import annotations

from typing import Any

# How far a closed case may sit from the case under review and still be
# comparable. Wide enough that a few dozen seeded cases return something,
# narrow enough that the word means something.
AMOUNT_TOLERANCE = 0.25
DTI_TOLERANCE = 0.05
SCORE_TOLERANCE = 40

# The reviewer reads these beside everything else on the screen; a long list
# stops being evidence and starts being a table.
MAX_COMPARABLES = 6

# What a case must supply before any window can be centred on it.
MATCH_KEYS = ("amount", "dti", "credit_score")


def missing_match_keys(case: dict[str, Any] | None) -> list[str]:
    """The comparison keys this case cannot supply.

    An amount of zero or less is as unusable as an absent one: a window of
    +/-25% around zero matches every case ever closed.
    """
    row = case or {}
    missing: list[str] = []
    for key in MATCH_KEYS:
        value = row.get(key)
        if value is None:
            missing.append(key)
        elif key == "amount" and float(value) <= 0:
            missing.append(key)
    return missing


def bands_for(case: dict[str, Any] | None) -> dict[str, Any] | None:
    """The numeric window a comparable case falls in.

    None when the case under review cannot supply every key — the caller then
    reports no comparables, rather than matching on whichever half was present
    and calling the result comparable.
    """
    if missing_match_keys(case):
        return None
    amount = float(case["amount"])
    dti = float(case["dti"])
    score = int(case["credit_score"])
    return {
        "amount_low": round(amount * (1 - AMOUNT_TOLERANCE), 2),
        "amount_high": round(amount * (1 + AMOUNT_TOLERANCE), 2),
        "dti_low": round(dti - DTI_TOLERANCE, 2),
        "dti_high": round(dti + DTI_TOLERANCE, 2),
        "score_low": score - SCORE_TOLERANCE,
        "score_high": score + SCORE_TOLERANCE,
    }


def outcome_split(cases: list[dict[str, Any]] | None) -> dict[str, int]:
    """How the comparable cases were decided. Both keys are always present, so
    an empty match reads as "none either way" rather than as missing data."""
    split = {"APPROVE": 0, "DECLINE": 0}
    for case in cases or []:
        outcome = case.get("outcome")
        if outcome in split:
            split[outcome] += 1
    return split
