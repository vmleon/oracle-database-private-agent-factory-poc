package com.bank.appbackend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "HITL_TASK")
@Getter
@NoArgsConstructor
public class HitlTask {

    @Id
    @Column(name = "TASK_ID")
    private Long taskId;

    @Column(name = "APPLICATION_ID")
    private Long applicationId;

    @Column(name = "STATE")
    private String state;

    @Column(name = "AGENT_RECOMMENDATION")
    private String agentRecommendation;

    @Column(name = "AGENT_RUN_ID")
    private String agentRunId;
}
