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
}
