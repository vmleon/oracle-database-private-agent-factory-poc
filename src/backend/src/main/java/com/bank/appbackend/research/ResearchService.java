package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchView;
import com.bank.appbackend.audit.ResearchAuditService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Runs the research agent for one review task and records what it produced.
 *
 * <p>The summary reaches the reviewer and the ledger only through
 * {@link ResearchSummary#screen}, so a summary that states an outcome is shown
 * to nobody and stored nowhere. The ledger is append-only: there is no second
 * chance to remove a row, which is why the screen runs before the insert.
 */
@Service
public class ResearchService {

    private static final Logger log = LoggerFactory.getLogger(ResearchService.class);

    /**
     * What the flow returns when its gate cannot resolve the case. It is not a case
     * file, so it is never appended to the ledger — the ledger is append-only, and a
     * transient wrapper outage must not leave a permanent non-summary row behind.
     * `paf/flows/RESEARCH_WORKFLOW.md` Step 10 sets this as the gate's False Message;
     * the two must agree.
     */
    static final String FLOW_UNAVAILABLE = "Research could not be completed for this case.";

    /**
     * How many times one research request asks the agent for a case file.
     *
     * <p>The agent's instructions ask it not to state an outcome and a model sometimes
     * does anyway, most readily on a case whose answer looks obvious. A rejected
     * summary is never stored or shown, so a second pass costs one generation and
     * turns most rejections into a usable case file without weakening the rule.
     */
    private static final int MAX_ATTEMPTS = 2;

    private final ResearchPafClient paf;
    private final JdbcTemplate jdbc;

    public ResearchService(ResearchPafClient paf, JdbcTemplate jdbc) {
        this.paf = paf;
        this.jdbc = jdbc;
    }

    /** Run research for a task and append the result. Never throws for a bad task id. */
    public ResearchView run(Long taskId, String reviewer) {
        String who = (reviewer == null || reviewer.isBlank()) ? "Backoffice Reviewer" : reviewer.trim();
        Long applicationId = applicationFor(taskId);
        if (applicationId == null) {
            log.warn("research requested for unknown task {}", taskId);
            return new ResearchView(taskId, ResearchSummary.BLOCKED, who, Instant.now(), null);
        }
        String runId = UUID.randomUUID().toString();
        Instant startedAt = Instant.now();
        String shown = null;
        for (int attempt = 1; attempt <= MAX_ATTEMPTS && shown == null; attempt++) {
            // The task id is the flow's only input, and PAF accepts no input beyond
            // the chat message, so it travels in-band exactly as the session token
            // does on the customer path.
            String raw = paf.run("[[TASK " + taskId + "]]");
            if (raw == null || raw.isBlank() || raw.startsWith(FLOW_UNAVAILABLE)) {
                log.warn("research run {} for task {} produced no case file on attempt {}",
                        runId, taskId, attempt);
                continue;
            }
            String screened = ResearchSummary.screen(raw);
            if (!screened.equals(raw)) {
                // Name the rule, never the text that broke it.
                log.warn("research run {} for task {} stated an outcome on attempt {}: {}",
                        runId, taskId, attempt, ResearchSummary.verdicts(raw));
                continue;
            }
            shown = screened;
        }
        // The wrapper wrote its trail while the run was in flight, with no way to know
        // the run id, and every attempt belongs to this one request. Stamp once, after
        // the last of them, so the summary row and all the tool calls behind it share
        // one key. Scoped to rows started at or after this run began, so an earlier
        // failed run's orphaned pending rows for the same task are left alone.
        stampAuditTrail(taskId, runId, who, startedAt);
        if (shown == null) {
            return new ResearchView(taskId, ResearchSummary.BLOCKED, who, Instant.now(), null);
        }
        jdbc.update("""
                INSERT INTO BANK_CORE.research_summary
                    (application_id, hitl_task_id, research_run_id, reviewer, summary)
                VALUES (?, ?, ?, ?, ?)
                """, applicationId, taskId, runId, who, shown);
        log.info("research run {} recorded for task {}", runId, taskId);
        return new ResearchView(taskId, shown, who, Instant.now(), runId);
    }

    /** The most recent recorded summary for a task, or null when none was ever run. */
    public ResearchView latest(Long taskId) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT summary, reviewer, created_at, research_run_id
                  FROM BANK_CORE.research_summary
                 WHERE hitl_task_id = ?
                 ORDER BY research_id DESC
                 FETCH FIRST 1 ROW ONLY
                """, taskId);
        if (rows.isEmpty()) {
            return null;
        }
        Map<String, Object> row = rows.get(0);
        Timestamp created = (Timestamp) row.get("CREATED_AT");
        return new ResearchView(taskId, String.valueOf(row.get("SUMMARY")),
                String.valueOf(row.get("REVIEWER")),
                created == null ? null : created.toInstant(),
                String.valueOf(row.get("RESEARCH_RUN_ID")));
    }

    private void stampAuditTrail(Long taskId, String runId, String reviewer, Instant startedAt) {
        try {
            jdbc.update("""
                    UPDATE BANK_CORE.research_audit
                       SET research_run_id = ?, reviewer = ?
                     WHERE hitl_task_id = ?
                       AND research_run_id = ?
                       AND started_at >= ?
                    """, runId, reviewer, taskId,
                    ResearchAuditService.pendingRunId(taskId), Timestamp.from(startedAt));
        } catch (RuntimeException e) {
            // Correlation is not worth failing a completed run over.
            log.warn("could not stamp the research trail for task {}", taskId, e);
        }
    }

    private Long applicationFor(Long taskId) {
        try {
            return jdbc.queryForObject(
                    "SELECT application_id FROM BANK_CORE.hitl_task WHERE task_id = ?",
                    Long.class, taskId);
        } catch (RuntimeException e) {
            return null;
        }
    }
}
