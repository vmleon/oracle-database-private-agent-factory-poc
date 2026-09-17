# AML — sanctions / PEP / suspicious-pattern flags.
#
# Synthetic sanctions and PEP lists are embedded here so the demo runs
# without external data; production would load them via `data` (e.g. a
# bundle from the bank's compliance feed). Names are pre-uppercased to
# make the substring match case-insensitive.
package decisioning.aml

import future.keywords.in

default allow := false

sanctions_list := [
    "OSAMA BIN BAD",
    "PABLO ESCOBAR",
    "MARLOWE LOANSHARK",
    "SANCTIONED ENTITY LLC",
]

deny contains msg if {
    upper_name := upper(input.customer.full_name)
    some entry in sanctions_list
    contains(upper_name, entry)
    msg := sprintf("Sanctions / watch-list match: %v", [entry])
}

pep_list := [
    "PAULA STATESMAN",
]

# PEPs (Politically Exposed Persons) require enhanced due diligence,
# not automatic rejection. Surface as a warn so the reviewer applies
# institution-specific policy.
warn contains msg if {
    upper_name := upper(input.customer.full_name)
    some entry in pep_list
    contains(upper_name, entry)
    msg := "Politically Exposed Person — enhanced due diligence required"
}

# Suspicious pattern: many large round-number transfers out in the
# past 30 days. Crude heuristic — production would call a fraud
# scoring service.
warn contains msg if {
    input.transactions.large_round_outflows_30d > 5
    msg := sprintf("Suspicious pattern: %v large round outflows in last 30 days", [input.transactions.large_round_outflows_30d])
}

allow if {
    count(deny) == 0
    count(warn) == 0
}
