package com.bank.appbackend.audit;

import com.bank.appbackend.api.Dtos.ResearchAudit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;

/**
 * Collects the per-tool research trail posted by research-mcp and writes it to
 * BANK_CORE.research_audit, which is kept separate from decision_audit so a
 * reviewer's research never pollutes the decisioning trail.
 *
 * <p>The wrapper holds no write grant, so this is the only path to the table.
 * Best-effort: a failure here never breaks a live research run.
 */
@Service
public class ResearchAuditService {

    private static final Logger log = LoggerFactory.getLogger(ResearchAuditService.class);

    /**
     * The run id a row carries until the service that owns the run stamps it. It is
     * scoped to the task because uq_research_audit_step is unique on
     * (research_run_id, step_no): one placeholder shared across tasks collides as
     * soon as two of them are un-stamped at the same time.
     */
    public static final String PENDING_RUN_ID_PREFIX = "pending-";

    public static String pendingRunId(Long hitlTaskId) {
        return PENDING_RUN_ID_PREFIX + hitlTaskId;
    }

    private final JdbcTemplate jdbc;

    public ResearchAuditService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void record(ResearchAudit req) {
        try {
            if (req.hitlTaskId() == null) {
                log.warn("research audit skipped: no task id (tool={})", req.toolName());
                return;
            }
            if (!taskExists(req.hitlTaskId())) {
                log.warn("research audit skipped: task {} does not resolve (tool={})",
                        req.hitlTaskId(), req.toolName());
                return;
            }
            String pending = pendingRunId(req.hitlTaskId());
            Long durationMs = (req.startedAt() != null && req.endedAt() != null)
                    ? Duration.between(req.startedAt(), req.endedAt()).toMillis()
                    : null;
            // Counted over the same key the unique index constrains, so the counter
            // and the index share one scope by construction.
            Integer stepNo = jdbc.queryForObject(
                    "SELECT NVL(MAX(step_no), 0) + 1 FROM BANK_CORE.research_audit "
                            + "WHERE research_run_id = ?",
                    Integer.class, pending);
            jdbc.update("""
                    INSERT INTO BANK_CORE.research_audit
                        (research_run_id, hitl_task_id, reviewer, step_no, tool_name,
                         tool_input, tool_output, started_at, ended_at, duration_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    pending, req.hitlTaskId(), "Backoffice Reviewer",
                    stepNo, req.toolName(), req.toolInput(), req.toolOutput(),
                    toTimestamp(req.startedAt()), toTimestamp(req.endedAt()), durationMs,
                    req.status() == null ? "SUCCESS" : req.status());
        } catch (RuntimeException e) {
            log.warn("research audit write failed (tool={})", req.toolName(), e);
        }
    }

    private static Timestamp toTimestamp(Instant i) {
        return i == null ? null : Timestamp.from(i);
    }

    // Unlike /v1/audit/tool-call, which resolves the session from its own token,
    // this endpoint takes hitlTaskId straight from the request body. This is the
    // cheap check that keeps a bad id from landing a row against a case that was
    // never under review.
    private boolean taskExists(Long hitlTaskId) {
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM BANK_CORE.hitl_task WHERE task_id = ?",
                Integer.class, hitlTaskId);
        return count != null && count > 0;
    }
}
