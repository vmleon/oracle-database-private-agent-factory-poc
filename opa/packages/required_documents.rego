# required_documents — agent-driven document collection.
#
# Looks up the required doc_type list for an applicant against the
# matrix in `data.decisioning.config.required_documents_matrix`,
# keyed by (product_type, employment_type, residency, amount_band).
# The CHAT_WORKFLOW calls this once per application and asks the
# customer for exactly those documents — not a fixed bundle.
#
# Input shape:
#   {
#     "product_type":    "PERSONAL_LOAN",
#     "employment_type": "salaried" | "self_employed",
#     "residency":       "resident" | "expat",
#     "amount":          25000
#   }
package decisioning.required_documents

import future.keywords.in

# Amount band derived from the requested amount and the configured cap.
amount_band := "small" if input.amount <= data.decisioning.config.amount_band_small_max

amount_band := "large" if input.amount > data.decisioning.config.amount_band_small_max

required := docs if {
    docs := data.decisioning.config.required_documents_matrix[input.product_type][input.employment_type][input.residency][amount_band]
}

rationale := msg if {
    msg := sprintf(
        "Document set for (product=%v, employment=%v, residency=%v, amount_band=%v) per policy.",
        [input.product_type, input.employment_type, input.residency, amount_band],
    )
}
