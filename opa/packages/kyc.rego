# KYC — ID validity, doc expiry, OCR quality gates.
#
# Input shape:
#   {
#     "customer":  { "kyc_status": "PASSED|PENDING|FAILED" },
#     "documents": [ {"doc_type": "ID", "expires_at": "2027-01-15",
#                     "quality_tier": "USABLE|MARGINAL|UNUSABLE"}, ... ],
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

deny contains msg if {
    some doc in input.documents
    doc.quality_tier == "UNUSABLE"
    msg := sprintf("Document %v is UNUSABLE (re-upload required)", [doc.doc_type])
}

warn contains msg if {
    input.customer.kyc_status == "PENDING"
    msg := "KYC status is PENDING — reviewer should verify before approval"
}

warn contains msg if {
    some doc in input.documents
    doc.quality_tier == "MARGINAL"
    msg := sprintf("Document %v quality is MARGINAL", [doc.doc_type])
}

allow if {
    count(deny) == 0
    count(warn) == 0
}
