# Configuration defaults referenced by every decisioning package.
#
# Values mirror APP.system_config seeds (database/liquibase/oracle/
# 005-system-config.yaml). Today they're baked into Rego; once the
# Application Service can sync system_config changes into OPA, the
# MCP wrapper will `PUT /v1/data/decisioning/config` on every
# parameter edit (planned for v1 — see docs/DESIGN.md §11
# "OPA bundle reload on parameter change").
#
# Other packages reference `data.decisioning.config.<key>` rather
# than hardcoding constants, so the future sync is a one-place change.
package decisioning.config

# Eligibility thresholds
min_age := 18
dti_hard_cap := 0.45
pti_hard_cap := 0.25
score_floor := 600
score_caution_band_upper := 670

# Fair-lending 4/5 rule threshold
fair_lending_dpi_ratio := 0.80

# Amount band split used by required_documents.rego
amount_band_small_max := 15000

# Rate card per risk band (currency-agnostic — pricing_model lives in
# product_catalog and the App Service interprets it).
rate_card := {
    "LOW": 0.045,
    "MID": 0.075,
    "HIGH": 0.120,
}

# Risk band cutoffs (score-driven, demo defaults)
risk_band_low_floor := 720
risk_band_mid_floor := 650

# Required documents matrix keyed by
# (product_type, employment_type, residency, amount_band).
# Mirrors APP.system_config.document_requirements_matrix.
required_documents_matrix := {
    "PERSONAL_LOAN": {
        "salaried": {
            "resident": {
                "small": ["ID", "PAYSLIP", "STATEMENT"],
                "large": ["ID", "PAYSLIP", "STATEMENT", "ADDRESS_PROOF"],
            },
            "expat": {
                "small": ["ID", "PAYSLIP", "STATEMENT", "ADDRESS_PROOF"],
                "large": ["ID", "PAYSLIP", "STATEMENT", "ADDRESS_PROOF"],
            },
        },
        "self_employed": {
            "resident": {
                "small": ["ID", "TAX_RETURN", "STATEMENT"],
                "large": ["ID", "TAX_RETURN", "STATEMENT", "ADDRESS_PROOF"],
            },
            "expat": {
                "small": ["ID", "TAX_RETURN", "STATEMENT", "ADDRESS_PROOF"],
                "large": ["ID", "TAX_RETURN", "STATEMENT", "ADDRESS_PROOF"],
            },
        },
    },
}
