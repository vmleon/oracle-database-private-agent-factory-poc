package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchView;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
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
        // The ledger is append-only: a rejected summary must never reach it.
        verify(jdbc, never()).update(anyString(), any(), any(), any(), any(), any());
    }

    @Test
    void anUnknownTaskIsNotResearched() {
        when(jdbc.queryForObject(anyString(), eq(Long.class), any())).thenReturn(null);

        ResearchView view = service.run(42L, "Backoffice Reviewer");

        assertThat(view.summary()).isEqualTo(ResearchSummary.BLOCKED);
        verify(paf, never()).run(anyString());
        verify(jdbc, never()).update(anyString(), any(), any(), any(), any(), any());
    }
}
