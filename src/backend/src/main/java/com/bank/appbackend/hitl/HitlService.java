package com.bank.appbackend.hitl;

import com.bank.appbackend.api.Dtos.DecisionListItem;
import com.bank.appbackend.api.Dtos.DecisionRequest;
import com.bank.appbackend.api.Dtos.DecisionResponse;
import com.bank.appbackend.api.Dtos.DecisionToolCall;
import com.bank.appbackend.api.Dtos.DecisionView;
import com.bank.appbackend.api.Dtos.HitlQueueItem;
import com.bank.appbackend.api.Dtos.HitlTaskView;
import com.bank.appbackend.domain.DecisionDetailRow;
import com.bank.appbackend.domain.HitlRepository;
import com.bank.appbackend.domain.HitlTaskRow;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@Service
public class HitlService {

    private static final String DEFAULT_REVIEWER = "Backoffice Reviewer";

    private final HitlRepository repo;
    private final ClaimQueue claims;

    public HitlService(HitlRepository repo, ClaimQueue claims) {
        this.repo = repo;
        this.claims = claims;
    }

    /** The review queue: cases waiting, and cases a reviewer is holding. */
    public List<HitlQueueItem> listQueue() {
        return repo.findQueue().stream()
                .map(r -> new HitlQueueItem(r.getTaskId(), r.getApplicationId(), r.getCustomerName(),
                        r.getAgentRecommendation(), r.getAmountRequested(), r.getTermMonths(),
                        r.getCreatedAt(), r.getState(), r.getAssignedTo()))
                .toList();
    }

    /**
     * Take the next waiting case for this reviewer. The message leaves
     * HITL_REQUEST and the task moves OPEN → IN_REVIEW in one transaction, so two
     * reviewers are never handed the same case and a rolled-back claim puts the
     * message back. Returns null when nothing is waiting.
     */
    @Transactional
    public HitlTaskView claimNext(String reviewer) {
        Long taskId = claims.claimNext(reviewer == null || reviewer.isBlank()
                ? DEFAULT_REVIEWER : reviewer);
        return taskId == null ? null : getDetail(taskId);
    }

    /** Full recommendation packet for one task, including the agent tool trace. 404 if unknown. */
    public HitlTaskView getDetail(Long taskId) {
        return toView(repo.findDetail(taskId).orElseThrow(this::notFound));
    }

    private List<DecisionToolCall> toolTrace(Long applicationId) {
        return repo.findDecisionAudit(applicationId).stream()
                .map(a -> new DecisionToolCall(a.getAuditId(), a.getStepNo(), a.getToolName(),
                        a.getToolInput(), a.getToolOutput(), a.getStartedAt(), a.getEndedAt(),
                        a.getDurationMs(), a.getStatus()))
                .toList();
    }

    /**
     * Close a task with the human decision: update hitl_task and write the blockchain
     * decision row, atomically. 400 on a bad outcome, 404 if the task is unknown,
     * 409 if it was already closed.
     */
    @Transactional
    public DecisionResponse decide(Long taskId, DecisionRequest req) {
        String outcome = req.outcome();
        if (!"APPROVE".equals(outcome) && !"DECLINE".equals(outcome)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "outcome must be APPROVE or DECLINE");
        }
        repo.findDetail(taskId).orElseThrow(this::notFound);

        String reviewer = (req.reviewer() == null || req.reviewer().isBlank())
                ? DEFAULT_REVIEWER : req.reviewer().trim();

        int closed = repo.closeTask(taskId, outcome, req.note(), reviewer);
        if (closed == 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "task already closed");
        }
        repo.insertDecision(taskId, outcome, req.note(), reviewer);
        return new DecisionResponse(taskId, "CLOSED", outcome, reviewer);
    }

    /** Decision history, newest first. Both filters optional. */
    public List<DecisionListItem> listDecisions(Long customerId, Long applicationId) {
        return repo.findDecisions(customerId, applicationId).stream()
                .map(r -> new DecisionListItem(r.getDecisionId(), r.getApplicationId(),
                        r.getCustomerName(), r.getHumanOutcome(), r.getHumanUser(), r.getDecidedAt(),
                        r.getAgentRecommendation(), r.getAmountRequested(), r.getTermMonths()))
                .toList();
    }

    /** Full decision record with the agent tool trace. 404 if unknown. */
    public DecisionView getDecision(Long decisionId) {
        DecisionDetailRow d = repo.findDecision(decisionId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "decision not found"));
        List<DecisionToolCall> toolCalls = toolTrace(d.getApplicationId());
        return new DecisionView(d.getDecisionId(), d.getApplicationId(), d.getCustomerName(),
                d.getAmountRequested(), d.getTermMonths(), d.getPurpose(), d.getHumanOutcome(),
                d.getHumanUser(), d.getHumanNote(), d.getDecidedAt(), d.getAgentRecommendation(),
                d.getAgentReasoning(), d.getAgentExploreHints(), d.getAgentEvidence(), d.getAgentRunId(),
                d.getPricingOffer(), d.getReasonCodes(), d.getComputedDti(), d.getComputedPti(), toolCalls);
    }

    private HitlTaskView toView(HitlTaskRow r) {
        return new HitlTaskView(r.getTaskId(), r.getApplicationId(), r.getCustomerName(),
                r.getAmountRequested(), r.getTermMonths(), r.getPurpose(), r.getState(),
                r.getAgentRecommendation(), r.getAgentReasoning(), r.getAgentExploreHints(),
                r.getAgentEvidence(), r.getAgentRunId(), r.getHumanOutcome(),
                r.getCreatedAt(), r.getClosedAt(), toolTrace(r.getApplicationId()));
    }

    private ResponseStatusException notFound() {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found");
    }
}
