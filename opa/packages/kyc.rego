# KYC — customer KYC status and ID expiry gates.
#
# Input shape:
#   {
#     "customer":  { "kyc_status": "PASSED|PENDING|FAILED" },
#     "documents": [ {"doc_type": "ID", "expires_at": "2027-01-15"}, ... ],
#     "today":     "2026-05-21"
#   }
package decisioning.kyc

import future.keywords.in

default allow := false

deny contains msg if {
    input.customer.kyc_status == "FAILED"
    msg := "KYC status is FAILED"
}

deny contains msg if {
    some doc in input.documents
    doc.doc_type == "ID"
    doc.expires_at < input.today
    msg := sprintf("ID document expired on %v", [doc.expires_at])
}

warn contains msg if {
    input.customer.kyc_status == "PENDING"
    msg := "KYC status is PENDING — reviewer should verify before approval"
}

allow if {
    count(deny) == 0
    count(warn) == 0
}
