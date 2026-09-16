package com.bank.appbackend.hitl;

import com.bank.appbackend.api.Dtos.DecisionRequest;
import com.bank.appbackend.api.Dtos.DecisionResponse;
import com.bank.appbackend.domain.HitlRepository;
import com.bank.appbackend.domain.HitlTaskRow;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class HitlServiceTest {

    private final HitlRepository repo = mock(HitlRepository.class);
    private final ClaimQueue claims = mock(ClaimQueue.class);
    private final HitlService service = new HitlService(repo, claims);

    @Test
    void decideClosesTaskAndWritesDecisionRow() {
        when(repo.findDetail(5L)).thenReturn(Optional.of(row(5L, "OPEN")));
        when(repo.closeTask(5L, "DECLINE", "DTI over cap", "Backoffice Reviewer")).thenReturn(1);

        DecisionResponse resp = service.decide(5L, new DecisionRequest("DECLINE", "DTI over cap", null));

        assertThat(resp.state()).isEqualTo("CLOSED");
        assertThat(resp.humanOutcome()).isEqualTo("DECLINE");
        assertThat(resp.humanUser()).isEqualTo("Backoffice Reviewer");
        verify(repo).insertDecision(5L, "DECLINE", "DTI over cap", "Backoffice Reviewer");
    }

    @Test
    void decideUsesProvidedReviewerName() {
        when(repo.findDetail(5L)).thenReturn(Optional.of(row(5L, "OPEN")));
        when(repo.closeTask(5L, "APPROVE", "looks good", "Sam")).thenReturn(1);

        DecisionResponse resp = service.decide(5L, new DecisionRequest("APPROVE", "looks good", "Sam"));

        assertThat(resp.humanUser()).isEqualTo("Sam");
        verify(repo).insertDecision(5L, "APPROVE", "looks good", "Sam");
    }

    @Test
    void decideOnAlreadyClosedTaskReturns409AndWritesNothing() {
        when(repo.findDetail(5L)).thenReturn(Optional.of(row(5L, "CLOSED")));
        when(repo.closeTask(eq(5L), any(), any(), any())).thenReturn(0);

        assertThatThrownBy(() -> service.decide(5L, new DecisionRequest("APPROVE", "ok", "Sam")))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("409");
        verify(repo, never()).insertDecision(anyLong(), any(), any(), any());
    }

    @Test
    void decideOnMissingTaskReturns404() {
        when(repo.findDetail(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.decide(99L, new DecisionRequest("APPROVE", "ok", "Sam")))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("404");
        verify(repo, never()).closeTask(anyLong(), any(), any(), any());
    }

    @Test
    void decideRejectsInvalidOutcome() {
        assertThatThrownBy(() -> service.decide(5L, new DecisionRequest("MAYBE", "x", "Sam")))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("400");
        verify(repo, never()).closeTask(anyLong(), any(), any(), any());
    }

    private HitlTaskRow row(Long id, String state) {
        return new HitlTaskRow() {
            public Long getTaskId() { return id; }
            public Long getApplicationId() { return 1L; }
            public String getCustomerName() { return "David HighDti"; }
            public BigDecimal getAmountRequested() { return new BigDecimal("20000"); }
            public Integer getTermMonths() { return 36; }
            public String getPurpose() { return "Debt consolidation"; }
            public String getState() { return state; }
            public String getAgentRecommendation() { return "DECLINE"; }
            public String getAgentReasoning() { return "DTI over cap"; }
            public String getAgentExploreHints() { return null; }
            public String getAgentEvidence() { return "{}"; }
            public String getAgentRunId() { return "run-1"; }
            public String getHumanOutcome() { return null; }
            public Instant getCreatedAt() { return Instant.EPOCH; }
            public Instant getClosedAt() { return null; }
        };
    }

    @Test
    void claimNextReturnsTheTaskTheQueueHandedOver() {
        when(claims.claimNext("Ada")).thenReturn(42L);
        when(repo.findDetail(42L)).thenReturn(Optional.of(row(42L, "OPEN")));
        when(repo.findDecisionAudit(anyLong())).thenReturn(List.of());

        assertThat(service.claimNext("Ada").taskId()).isEqualTo(42L);
    }

    @Test
    void claimNextReturnsNullWhenNothingIsWaiting() {
        when(claims.claimNext(anyString())).thenReturn(null);

        assertThat(service.claimNext("Ada")).isNull();
        verify(repo, never()).findDetail(anyLong());
    }

    @Test
    void claimNextFallsBackToTheDefaultReviewer() {
        when(claims.claimNext("Backoffice Reviewer")).thenReturn(null);

        assertThat(service.claimNext("  ")).isNull();
        verify(claims).claimNext("Backoffice Reviewer");
    }
}
