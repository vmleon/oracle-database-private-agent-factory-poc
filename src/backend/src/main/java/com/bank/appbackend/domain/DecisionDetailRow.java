package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for a single decision record (JSON columns as text). */
public interface DecisionDetailRow {
    Long getDecisionId();
    Long getApplicationId();
    String getCustomerName();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    String getPurpose();
    String getHumanOutcome();
    String getHumanUser();
    String getHumanNote();
    Instant getDecidedAt();
    String getAgentRecommendation();
    String getAgentReasoning();
    String getAgentExploreHints();
    String getAgentEvidence();
    String getAgentRunId();
    String getPricingOffer();
    String getReasonCodes();
    BigDecimal getComputedDti();
    BigDecimal getComputedPti();
}
