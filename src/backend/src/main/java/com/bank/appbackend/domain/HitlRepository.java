package com.bank.appbackend.domain;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface HitlRepository extends JpaRepository<HitlTask, Long> {

    @Query(value = """
            SELECT t.task_id            AS taskId,
                   t.application_id      AS applicationId,
                   c.full_name           AS customerName,
                   t.agent_recommendation AS agentRecommendation,
                   la.amount_requested   AS amountRequested,
                   la.term_months        AS termMonths,
                   t.created_at          AS createdAt
              FROM BANK_CORE.hitl_task t
              JOIN BANK_CORE.loan_application la ON la.application_id = t.application_id
              JOIN BANK_CORE.customer c          ON c.customer_id = la.customer_id
             WHERE t.state = :state
             ORDER BY t.created_at
            """, nativeQuery = true)
    List<HitlQueueRow> findQueue(@Param("state") String state);

    @Query(value = """
            SELECT t.task_id            AS taskId,
                   t.application_id      AS applicationId,
                   c.full_name           AS customerName,
                   la.amount_requested   AS amountRequested,
                   la.term_months        AS termMonths,
                   la.purpose            AS purpose,
                   t.state               AS state,
                   t.agent_recommendation AS agentRecommendation,
                   TO_CHAR(t.agent_reasoning) AS agentReasoning,
                   JSON_SERIALIZE(t.agent_explore_hints RETURNING VARCHAR2) AS agentExploreHints,
                   JSON_SERIALIZE(t.agent_evidence RETURNING VARCHAR2)      AS agentEvidence,
                   t.agent_run_id        AS agentRunId,
                   t.human_outcome       AS humanOutcome,
                   t.created_at          AS createdAt,
                   t.closed_at           AS closedAt
              FROM BANK_CORE.hitl_task t
              JOIN BANK_CORE.loan_application la ON la.application_id = t.application_id
              JOIN BANK_CORE.customer c          ON c.customer_id = la.customer_id
             WHERE t.task_id = :taskId
            """, nativeQuery = true)
    Optional<HitlTaskRow> findDetail(@Param("taskId") Long taskId);

    @Modifying
    @Query(value = """
            UPDATE BANK_CORE.hitl_task
               SET state        = 'CLOSED',
                   human_outcome = :outcome,
                   human_note    = :note,
                   human_user    = :reviewer,
                   closed_at     = SYSTIMESTAMP
             WHERE task_id = :taskId
               AND state <> 'CLOSED'
            """, nativeQuery = true)
    int closeTask(@Param("taskId") Long taskId, @Param("outcome") String outcome,
                  @Param("note") String note, @Param("reviewer") String reviewer);

    /**
     * One row per bank decision. The evidence packet carries the ratios, the reason
     * codes and the indicative rate as JSON; they are lifted into their own columns
     * here because the table is append-only — a value not written on the first
     * insert can never be added to that row.
     *
     * pricing_offer follows the human's outcome, not the agent's tier: the packet
     * prices every application it can so the reviewer sees the figure, but a
     * declined application was never offered a rate.
     */
    @Modifying
    @Query(value = """
            INSERT INTO BANK_CORE.decision
                (application_id, human_outcome, human_user, human_note,
                 agent_recommendation, agent_reasoning, agent_explore_hints,
                 agent_evidence, agent_run_id,
                 pricing_offer, reason_codes, computed_dti, computed_pti)
            SELECT application_id, :outcome, :reviewer, :note,
                   agent_recommendation, agent_reasoning, agent_explore_hints,
                   agent_evidence, agent_run_id,
                   CASE WHEN :outcome = 'APPROVE'
                        THEN JSON_QUERY(agent_evidence, '$.pricing') END,
                   JSON_QUERY(agent_evidence, '$.reason_codes'),
                   JSON_VALUE(agent_evidence, '$.derived.dti' RETURNING NUMBER),
                   JSON_VALUE(agent_evidence, '$.derived.pti' RETURNING NUMBER)
              FROM BANK_CORE.hitl_task
             WHERE task_id = :taskId
            """, nativeQuery = true)
    void insertDecision(@Param("taskId") Long taskId, @Param("outcome") String outcome,
                        @Param("note") String note, @Param("reviewer") String reviewer);

    /** Decision-history list. Both filters are optional (null = no filter). */
    @Query(value = """
            SELECT d.decision_id        AS decisionId,
                   d.application_id      AS applicationId,
                   c.full_name          AS customerName,
                   d.human_outcome      AS humanOutcome,
                   d.human_user         AS humanUser,
                   d.decided_at         AS decidedAt,
                   d.agent_recommendation AS agentRecommendation,
                   la.amount_requested  AS amountRequested,
                   la.term_months       AS termMonths
              FROM BANK_CORE.decision d
              JOIN BANK_CORE.loan_application la ON la.application_id = d.application_id
              JOIN BANK_CORE.customer c          ON c.customer_id = la.customer_id
             WHERE (:customerId IS NULL OR c.customer_id = :customerId)
               AND (:applicationId IS NULL OR d.application_id = :applicationId)
             ORDER BY d.decided_at DESC
            """, nativeQuery = true)
    List<DecisionRow> findDecisions(@Param("customerId") Long customerId,
                                    @Param("applicationId") Long applicationId);

    /** Full record for one decision. */
    @Query(value = """
            SELECT d.decision_id        AS decisionId,
                   d.application_id      AS applicationId,
                   c.full_name          AS customerName,
                   la.amount_requested  AS amountRequested,
                   la.term_months       AS termMonths,
                   la.purpose           AS purpose,
                   d.human_outcome      AS humanOutcome,
                   d.human_user         AS humanUser,
                   TO_CHAR(d.human_note) AS humanNote,
                   d.decided_at         AS decidedAt,
                   d.agent_recommendation AS agentRecommendation,
                   TO_CHAR(d.agent_reasoning) AS agentReasoning,
                   JSON_SERIALIZE(d.agent_explore_hints RETURNING VARCHAR2) AS agentExploreHints,
                   JSON_SERIALIZE(d.agent_evidence RETURNING VARCHAR2)      AS agentEvidence,
                   d.agent_run_id       AS agentRunId,
                   JSON_SERIALIZE(d.pricing_offer RETURNING VARCHAR2) AS pricingOffer,
                   JSON_SERIALIZE(d.reason_codes RETURNING VARCHAR2)  AS reasonCodes,
                   d.computed_dti       AS computedDti,
                   d.computed_pti       AS computedPti
              FROM BANK_CORE.decision d
              JOIN BANK_CORE.loan_application la ON la.application_id = d.application_id
              JOIN BANK_CORE.customer c          ON c.customer_id = la.customer_id
             WHERE d.decision_id = :decisionId
            """, nativeQuery = true)
    Optional<DecisionDetailRow> findDecision(@Param("decisionId") Long decisionId);

    /** Per-tool agent trace for a decision, by application id (the per-call rows are written
     *  by the tool wrappers at run time and keyed on application_id). Ordered by step number,
     *  which the portal shows: a nested call completes before its caller, so start time and
     *  step number disagree and only step number matches the labels. */
    @Query(value = """
            SELECT a.audit_id      AS auditId,
                   a.step_no       AS stepNo,
                   a.tool_name     AS toolName,
                   JSON_SERIALIZE(a.tool_input RETURNING VARCHAR2)  AS toolInput,
                   JSON_SERIALIZE(a.tool_output RETURNING VARCHAR2) AS toolOutput,
                   a.started_at    AS startedAt,
                   a.ended_at      AS endedAt,
                   a.duration_ms   AS durationMs,
                   a.status        AS status
              FROM BANK_CORE.decision_audit a
             WHERE a.application_id = :applicationId
             ORDER BY a.step_no
            """, nativeQuery = true)
    List<DecisionAuditRow> findDecisionAudit(@Param("applicationId") Long applicationId);
}
