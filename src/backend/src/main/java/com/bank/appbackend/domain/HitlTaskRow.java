package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for a single HITL task detail (JSON columns as text). */
public interface HitlTaskRow {
    Long getTaskId();
    Long getApplicationId();
    Long getCustomerId();
    String getCustomerName();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    String getPurpose();
    String getState();
    String getAgentRecommendation();
    String getAgentReasoning();
    String getAgentExploreHints();
    String getAgentEvidence();
    String getAgentRunId();
    String getHumanOutcome();
    Instant getCreatedAt();
    Instant getClosedAt();
}
