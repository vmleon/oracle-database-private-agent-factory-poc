package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for the review queue: waiting and claimed cases. */
public interface HitlQueueRow {
    Long getTaskId();
    Long getApplicationId();
    String getCustomerName();
    String getAgentRecommendation();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    Instant getCreatedAt();
    String getState();
    String getAssignedTo();
}
