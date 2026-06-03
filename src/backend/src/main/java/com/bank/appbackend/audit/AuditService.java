package com.bank.appbackend.audit;

import com.bank.appbackend.api.Dtos.ToolCallAudit;
import com.bank.appbackend.login.SessionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;

/**
 * Collects per-tool CHAT_WORKFLOW audit rows posted by the MCP tool wrappers and writes
 * them to APP.decision_audit, keyed by application_id (resolved from the session token when
 * the tool doesn't carry the id directly). Best-effort: any failure here is swallowed so an
 * audit problem can never break the live decisioning run.
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    private final JdbcTemplate jdbc;
    private final SessionService sessions;

    public AuditService(JdbcTemplate jdbc, SessionService sessions) {
        this.jdbc = jdbc;
        this.sessions = sessions;
    }

    public void record(ToolCallAudit req) {
        try {
            Long applicationId = req.applicationId() != null
                    ? req.applicationId()
                    : resolveQuietly(req.sessionToken());
            if (applicationId == null) {
                log.warn("tool-call audit skipped: no application correlation (tool={})", req.toolName());
                return;
            }

            Long durationMs = (req.startedAt() != null && req.endedAt() != null)
                    ? Duration.between(req.startedAt(), req.endedAt()).toMillis()
                    : null;
            Integer stepNo = jdbc.queryForObject(
                    "SELECT NVL(MAX(step_no), 0) + 1 FROM APP.decision_audit WHERE application_id = ?",
                    Integer.class, applicationId);

            jdbc.update("""
                    INSERT INTO APP.decision_audit
                        (application_id, step_no, tool_name, tool_input, tool_output,
                         started_at, ended_at, duration_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    applicationId, stepNo, req.toolName(), req.toolInput(), req.toolOutput(),
                    toTimestamp(req.startedAt()), toTimestamp(req.endedAt()), durationMs,
                    req.status() == null ? "SUCCESS" : req.status());
        } catch (RuntimeException e) {
            // Audit is fire-and-forget; never propagate to the caller (an agent tool).
            log.warn("tool-call audit write failed (tool={})", req.toolName(), e);
        }
    }

    private Long resolveQuietly(String token) {
        if (token == null || token.isBlank()) {
            return null;
        }
        try {
            return sessions.resolve(token).getApplicationId();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static Timestamp toTimestamp(Instant i) {
        return i == null ? null : Timestamp.from(i);
    }
}
