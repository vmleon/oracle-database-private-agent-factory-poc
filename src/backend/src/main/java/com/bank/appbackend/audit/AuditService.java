package com.bank.appbackend.audit;

import com.bank.appbackend.api.Dtos.ToolCallAudit;
import com.bank.appbackend.domain.LoanApplication;
import com.bank.appbackend.domain.LoanApplicationRepository;
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
 * them to BANK_CORE.decision_audit. The application is resolved server-side from the opaque
 * session token only — never from a caller-supplied field — so a row can only ever be
 * written for the application that token authenticates (no cross-application forgery).
 * The session's cached application_id is a login-time snapshot and is null for a customer
 * who had no application when they signed in, so the customer's open application is looked
 * up fresh on every call — a trace must cover the turn that creates the application.
 * Best-effort: any failure here is swallowed so an audit problem can never break the live
 * decisioning run.
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    private final JdbcTemplate jdbc;
    private final SessionService sessions;
    private final LoanApplicationRepository applications;

    public AuditService(JdbcTemplate jdbc, SessionService sessions,
                        LoanApplicationRepository applications) {
        this.jdbc = jdbc;
        this.sessions = sessions;
        this.applications = applications;
    }

    public void record(ToolCallAudit req) {
        try {
            // Authoritative: the application is whatever the session token resolves to.
            // Never trust a caller-supplied id — that would let a tool forge audit rows
            // for another customer's application.
            Long customerId = resolveQuietly(req.sessionToken());
            if (customerId == null) {
                log.warn("tool-call audit skipped: invalid or expired session (tool={})", req.toolName());
                return;
            }
            Long applicationId = applications.findOpenByCustomer(customerId)
                    .map(LoanApplication::getApplicationId)
                    .orElse(null);
            if (applicationId == null) {
                log.debug("tool-call audit skipped: customer {} has no open application yet (tool={})",
                        customerId, req.toolName());
                return;
            }

            Long durationMs = (req.startedAt() != null && req.endedAt() != null)
                    ? Duration.between(req.startedAt(), req.endedAt()).toMillis()
                    : null;
            Integer stepNo = jdbc.queryForObject(
                    "SELECT NVL(MAX(step_no), 0) + 1 FROM BANK_CORE.decision_audit WHERE application_id = ?",
                    Integer.class, applicationId);

            jdbc.update("""
                    INSERT INTO BANK_CORE.decision_audit
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

    /** The customer the token authenticates, or null if the token is unusable. */
    private Long resolveQuietly(String token) {
        if (token == null || token.isBlank()) {
            return null;
        }
        try {
            return sessions.resolve(token).getCustomerId();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static Timestamp toTimestamp(Instant i) {
        return i == null ? null : Timestamp.from(i);
    }
}
