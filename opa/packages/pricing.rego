# Pricing — risk-band → rate from the configured rate card.
#
# Risk band is derived from credit score (configurable cutoffs in
# `data.decisioning.config`). The CHAT_AGENT calls this last as
# indicative pricing for the recommendation packet; the final priced
# offer is only quoted to the customer after the human reviewer
# approves the HITL task.
#
# Input shape:
#   {
#     "applicant":   {"credit_score": 742, "dti": 0.30},
#     "application": {"amount": 10000, "term_months": 24}
#   }
package decisioning.pricing

risk_band := "LOW" if {
    input.applicant.credit_score >= data.decisioning.config.risk_band_low_floor
    input.applicant.dti <= data.decisioning.config.dti_hard_cap
}

risk_band := "MID" if {
    input.applicant.credit_score >= data.decisioning.config.risk_band_mid_floor
    input.applicant.credit_score < data.decisioning.config.risk_band_low_floor
}

risk_band := "HIGH" if {
    input.applicant.credit_score < data.decisioning.config.risk_band_mid_floor
}

rate_value := data.decisioning.config.rate_card[risk_band]

# Convenience aggregate so the MCP tool returns one object.
quote := {
    "risk_band":  risk_band,
    "rate_value": rate_value,
    "amount":     input.application.amount,
    "term_months": input.application.term_months,
}
