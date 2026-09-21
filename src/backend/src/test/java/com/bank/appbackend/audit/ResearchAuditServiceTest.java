package com.bank.appbackend.audit;

import com.bank.appbackend.api.Dtos.ResearchAudit;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResearchAuditServiceTest {

    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final ResearchAuditService service = new ResearchAuditService(jdbc);

    @Test
    void theStepNumberQueryIsScopedToThePerTaskPendingRunId() {
        when(jdbc.queryForObject(anyString(), eq(Integer.class), any())).thenReturn(1);

        service.record(new ResearchAudit(42L, "compare_cases", "SUCCESS",
                Instant.now(), Instant.now(), "{}", "{}"));

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> bind = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).queryForObject(sql.capture(), eq(Integer.class), bind.capture());

        // Scoped to the placeholder run id, not the task id directly — the unique
        // index the counter must not collide with is on (research_run_id, step_no).
        assertThat(sql.getValue()).contains("research_run_id");
        assertThat(sql.getValue()).doesNotContain("hitl_task_id");
        assertThat(bind.getValue()).containsExactly(ResearchAuditService.pendingRunId(42L));
    }

    @Test
    void theInsertSuppliesEveryNotNullColumn() {
        when(jdbc.queryForObject(anyString(), eq(Integer.class), any())).thenReturn(3);

        service.record(new ResearchAudit(42L, "compare_cases", null,
                Instant.now(), Instant.now(), "{\"taskId\":42}", "{\"rows\":4}"));

        ArgumentCaptor<Object[]> args = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(anyString(), args.capture());
        Object[] bound = args.getValue();

        // Positional order matches the INSERT column list: research_run_id, hitl_task_id,
        // reviewer, step_no, tool_name, tool_input, tool_output, started_at, ended_at,
        // duration_ms, status.
        assertThat(bound[0]).as("research_run_id").isNotNull();
        assertThat(bound[2]).as("reviewer").isNotNull();
        assertThat(bound[3]).as("step_no").isNotNull();
        assertThat(bound[4]).as("tool_name").isNotNull();
        assertThat(bound[7]).as("started_at").isNotNull();
        assertThat(bound[10]).as("status").isNotNull();
    }

    @Test
    void aNullTaskIdRecordsNothing() {
        service.record(new ResearchAudit(null, "compare_cases", "SUCCESS",
                Instant.now(), Instant.now(), "{}", "{}"));

        verify(jdbc, never()).update(anyString(), (Object[]) any());
    }

    @Test
    void aNullStatusDefaultsToSuccess() {
        when(jdbc.queryForObject(anyString(), eq(Integer.class), any())).thenReturn(1);

        service.record(new ResearchAudit(42L, "compare_cases", null,
                Instant.now(), Instant.now(), "{}", "{}"));

        ArgumentCaptor<Object[]> args = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(anyString(), args.capture());
        assertThat(args.getValue()[10]).isEqualTo("SUCCESS");
    }
}
