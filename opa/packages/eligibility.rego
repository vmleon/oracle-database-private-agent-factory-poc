# Eligibility — age, DTI, PTI, credit score.
#
# Returns three collections of human-readable messages that the
# CHAT_WORKFLOW folds into the recommendation packet's reasoning:
#   - deny : hard fail signals; weight toward DECLINE tier
#   - warn : caution signals;   weight toward REVIEW tier
#   - allow: true iff no deny and no warn fired
#
# These are signals, not decisions. Per the design (DESIGN.md §11),
# the human reviewer is always the decision-maker; CHAT_WORKFLOW writes
# a recommendation packet to hitl_task carrying these messages as
# evidence.
package decisioning.eligibility

import future.keywords.in

default allow := false

deny contains msg if {
    input.applicant.age < data.decisioning.config.min_age
    msg := sprintf("Applicant under minimum age (%v)", [data.decisioning.config.min_age])
}

deny contains msg if {
    input.applicant.dti > data.decisioning.config.dti_hard_cap
    msg := sprintf("DTI %.2f exceeds cap %.2f", [input.applicant.dti, data.decisioning.config.dti_hard_cap])
}

deny contains msg if {
    input.applicant.pti > data.decisioning.config.pti_hard_cap
    msg := sprintf("PTI %.2f exceeds cap %.2f", [input.applicant.pti, data.decisioning.config.pti_hard_cap])
}

deny contains msg if {
    input.applicant.credit_score < data.decisioning.config.score_floor
    msg := sprintf("Credit score %v below floor %v", [input.applicant.credit_score, data.decisioning.config.score_floor])
}

warn contains msg if {
    input.applicant.credit_score >= data.decisioning.config.score_floor
    input.applicant.credit_score < data.decisioning.config.score_caution_band_upper
    msg := sprintf("Credit score %v in caution band (< %v)", [input.applicant.credit_score, data.decisioning.config.score_caution_band_upper])
}

allow if {
    count(deny) == 0
    count(warn) == 0
}
