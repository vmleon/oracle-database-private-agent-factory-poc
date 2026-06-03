package com.bank.appbackend.domain;

import java.time.Instant;

/** Spring Data projection for one agent tool call in the decision audit trail. */
public interface DecisionAuditRow {
    Long getAuditId();
    Integer getStepNo();
    String getToolName();
    String getToolInput();
    String getToolOutput();
    Instant getStartedAt();
    Instant getEndedAt();
    Long getDurationMs();
    String getStatus();
}
