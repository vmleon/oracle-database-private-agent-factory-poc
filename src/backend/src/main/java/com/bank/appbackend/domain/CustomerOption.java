package com.bank.appbackend.domain;

import java.math.BigDecimal;

/** Spring Data projection for the login dropdown. */
public interface CustomerOption {
    Long getCustomerId();
    String getName();
    Long getApplicationId();
    String getProductType();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    String getApplicationStatus();
    String getPurpose();
    Long getMessageCount();
    /** State of the newest review task for this application, or null if none was ever filed. */
    String getReviewState();
}
