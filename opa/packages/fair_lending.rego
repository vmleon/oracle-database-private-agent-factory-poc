# Fair-lending pre-flight on a single decision.
#
# Per the design, this is a SIGNAL that something looks like a
# disparate-impact pattern the institution chose to monitor — not a
# decision. The bigger picture (4/5 rule across cohorts) is the
# periodic backoffice sampler that writes APP.fair_lending_review.
#
# Input shape:
#   {
#     "protected_attrs":   {"age_band": "26-35", "gender": "F", "nationality": "resident"},
#     "decision_draft":    {"tier": "DECLINE", "deny_reasons": [...]},
#     "monitored_patterns": [ {"attr": "age_band", "value": "66+", "tier": "DECLINE"}, ... ]
#   }
package decisioning.fair_lending

import future.keywords.in

default flag := false

# A monitored pattern fires when both the protected attribute matches
# AND the recommended tier matches a configured concern (typically
# DECLINE on a protected cohort).
flag if some_match

reason := msg if {
    flag
    some pattern in input.monitored_patterns
    input.protected_attrs[pattern.attr] == pattern.value
    input.decision_draft.tier == pattern.tier
    msg := sprintf(
        "Pattern flag: %v=%v with %v — disparate-impact monitoring",
        [pattern.attr, pattern.value, pattern.tier],
    )
}

some_match if {
    some pattern in input.monitored_patterns
    input.protected_attrs[pattern.attr] == pattern.value
    input.decision_draft.tier == pattern.tier
}
