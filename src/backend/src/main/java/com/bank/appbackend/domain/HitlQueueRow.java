package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for the OPEN-task queue list. */
public interface HitlQueueRow {
    Long getTaskId();
    Long getApplicationId();
    String getCustomerName();
    String getAgentRecommendation();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    Instant getCreatedAt();
}
