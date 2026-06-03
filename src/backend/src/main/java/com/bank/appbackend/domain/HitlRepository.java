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
              FROM APP.hitl_task t
              JOIN APP.loan_application la ON la.application_id = t.application_id
              JOIN APP.customer c          ON c.customer_id = la.customer_id
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
              FROM APP.hitl_task t
              JOIN APP.loan_application la ON la.application_id = t.application_id
              JOIN APP.customer c          ON c.customer_id = la.customer_id
             WHERE t.task_id = :taskId
            """, nativeQuery = true)
    Optional<HitlTaskRow> findDetail(@Param("taskId") Long taskId);

    @Modifying
    @Query(value = """
            UPDATE APP.hitl_task
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

    @Modifying
    @Query(value = """
            INSERT INTO APP.decision
                (application_id, human_outcome, human_user, human_note,
                 agent_recommendation, agent_reasoning, agent_explore_hints,
                 agent_evidence, agent_run_id)
            SELECT application_id, :outcome, :reviewer, :note,
                   agent_recommendation, agent_reasoning, agent_explore_hints,
                   agent_evidence, agent_run_id
              FROM APP.hitl_task
             WHERE task_id = :taskId
            """, nativeQuery = true)
    void insertDecision(@Param("taskId") Long taskId, @Param("outcome") String outcome,
                        @Param("note") String note, @Param("reviewer") String reviewer);
}
