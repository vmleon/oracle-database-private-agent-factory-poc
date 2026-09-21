package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchView;
import com.bank.appbackend.audit.ResearchAuditService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResearchServiceTest {

    private final ResearchPafClient paf = mock(ResearchPafClient.class);
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final ResearchService service = new ResearchService(paf, jdbc);

    private static final String ORGANISED =
            "SUPPORTS APPROVING\n- 4 comparable cases approved\n\nARGUES AGAINST\n- 3 round outflows";

    @Test
    void runEnvelopesTheTaskId() {
        when(paf.run(anyString())).thenReturn(ORGANISED);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        service.run(42L, "Backoffice Reviewer");

        verify(paf).run(eq("[[TASK 42]]"));
    }

    @Test
    void anOrganisedSummaryIsPersistedAndReturned() {
        when(paf.run(anyString())).thenReturn(ORGANISED);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ORGANISED);
        assertThat(view.researchRunId()).isNotBlank();
        verify(jdbc).update(anyString(), eq(7L), eq(42L), eq(view.researchRunId()),
                eq("Backoffice Reviewer"), eq(ORGANISED));
    }

    @Test
    void aSummaryThatConcludesIsNeverPersisted() {
        when(paf.run(anyString())).thenReturn("On balance, I recommend approving this.");
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ResearchSummary.BLOCKED);
        // The ledger is append-only: a rejected summary must never reach it. Matched by
        // statement, not argument count, so a change to the INSERT's arity can't make
        // this pass vacuously.
        verify(jdbc, never()).update(contains("research_summary"), any(), any(), any(), any(), any());
    }

    @Test
    void anUnknownTaskIsNotResearched() {
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(null);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ResearchSummary.BLOCKED);
        verify(paf, never()).run(anyString());
        verify(jdbc, never()).update(contains("research_summary"), any(), any(), any(), any(), any());
    }

    @Test
    void theAuditTrailIsStampedWithTheRunIdAndReviewer() {
        when(paf.run(anyString())).thenReturn(ORGANISED);
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(7L);

        ResearchView view = service.run(42L, "Jordan Reviewer");

        ArgumentCaptor<Object[]> args = ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(contains("UPDATE BANK_CORE.research_audit"), args.capture());
        Object[] bound = args.getValue();
        assertThat(bound[0]).isEqualTo(view.researchRunId());
        assertThat(bound[1]).isEqualTo("Jordan Reviewer");
        assertThat(bound[2]).isEqualTo(42L);
        assertThat(bound[3]).isEqualTo(ResearchAuditService.pendingRunId(42L));
    }

    @Test
    void latestReturnsNullWhenNoRowsExist() {
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenReturn(List.of());

        assertThat(service.latest(42L)).isNull();
    }

    @Test
    void latestMapsAnUppercaseKeyedRow() {
        Instant created = Instant.parse("2026-09-21T10:15:30Z");
        Map<String, Object> row = Map.of(
                "SUMMARY", "organised evidence",
                "REVIEWER", "Jordan Reviewer",
                "CREATED_AT", java.sql.Timestamp.from(created),
                "RESEARCH_RUN_ID", "run-123");
        when(jdbc.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(row));

        ResearchView view = service.latest(42L);

        assertThat(view.taskId()).isEqualTo(42L);
        assertThat(view.summary()).isEqualTo("organised evidence");
        assertThat(view.reviewer()).isEqualTo("Jordan Reviewer");
        assertThat(view.createdAt()).isEqualTo(created);
        assertThat(view.researchRunId()).isEqualTo("run-123");
    }
}
