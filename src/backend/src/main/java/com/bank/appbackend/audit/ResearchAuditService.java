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
     * What a row carries until the service that owns the run stamps it. The
     * wrapper is called from inside the PAF run and cannot know the run id, so
     * the trail is written first and correlated afterwards.
     */
    public static final String PENDING_RUN_ID = "pending";

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
            Long durationMs = (req.startedAt() != null && req.endedAt() != null)
                    ? Duration.between(req.startedAt(), req.endedAt()).toMillis()
                    : null;
            Integer stepNo = jdbc.queryForObject(
                    "SELECT NVL(MAX(step_no), 0) + 1 FROM BANK_CORE.research_audit WHERE hitl_task_id = ?",
                    Integer.class, req.hitlTaskId());
            jdbc.update("""
                    INSERT INTO BANK_CORE.research_audit
                        (research_run_id, hitl_task_id, reviewer, step_no, tool_name,
                         tool_input, tool_output, started_at, ended_at, duration_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    PENDING_RUN_ID, req.hitlTaskId(), "Backoffice Reviewer",
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
}
