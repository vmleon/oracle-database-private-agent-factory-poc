package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for the decision-history list. */
public interface DecisionRow {
    Long getDecisionId();
    Long getApplicationId();
    String getCustomerName();
    String getHumanOutcome();
    String getHumanUser();
    Instant getDecidedAt();
    String getAgentRecommendation();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
}
