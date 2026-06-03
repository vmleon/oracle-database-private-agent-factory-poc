package com.bank.appbackend.api;

import java.time.Instant;

/** Request/response payloads for the chat-slice API. */
public final class Dtos {

    private Dtos() {
    }

    public record LoginRequest(Long customerId) {
    }

    public record LoginResponse(String sessionToken, Long customerId, Long applicationId, String roomId) {
    }

    public record CustomerSummary(Long customerId, String name, Long applicationId,
                                  String productType, java.math.BigDecimal amountRequested,
                                  Integer termMonths, boolean hasOpenApplication) {
    }

    public record ChatRequest(String message) {
    }

    /** Returned by POST /v1/chat — the async turn id the SSE reply will reference. */
    public record TurnAccepted(String turnId) {
    }

    /** SSE "agent" event payload: the completed reply for a turn. */
    public record AgentEvent(String turnId, String reply, String pafRoomId) {
    }

    /** SSE "error" event payload: the turn failed. */
    public record ErrorEvent(String turnId, String message) {
    }

    public record ChatMessageView(String sender, String body, Instant createdAt) {
    }

    public record HitlQueueItem(Long taskId, Long applicationId, String customerName,
                                String agentRecommendation, java.math.BigDecimal amountRequested,
                                Integer termMonths, Instant createdAt) {
    }

    public record HitlTaskView(Long taskId, Long applicationId, String customerName,
                               java.math.BigDecimal amountRequested, Integer termMonths, String purpose,
                               String state, String agentRecommendation, String agentReasoning,
                               String agentExploreHints, String agentEvidence, String agentRunId,
                               String humanOutcome, Instant createdAt, Instant closedAt) {
    }

    public record DecisionRequest(String outcome, String note, String reviewer) {
    }

    public record DecisionResponse(Long taskId, String state, String humanOutcome, String humanUser) {
    }

    public record DecisionListItem(Long decisionId, Long applicationId, String customerName,
                                   String humanOutcome, String humanUser, Instant decidedAt,
                                   String agentRecommendation, java.math.BigDecimal amountRequested,
                                   Integer termMonths) {
    }

    public record DecisionToolCall(Long auditId, Integer stepNo, String toolName, String toolInput,
                                   String toolOutput, Instant startedAt, Instant endedAt,
                                   Long durationMs, String status) {
    }

    /** Posted by an MCP tool wrapper after each CHAT_WORKFLOW tool call. The application is
     *  resolved server-side from the opaque sessionToken — never trusted from the caller, so
     *  a row can only be written for the application the token authenticates. */
    public record ToolCallAudit(String sessionToken, String toolName,
                                String status, Instant startedAt, Instant endedAt,
                                String toolInput, String toolOutput) {
    }

    public record DecisionView(Long decisionId, Long applicationId, String customerName,
                               java.math.BigDecimal amountRequested, Integer termMonths, String purpose,
                               String humanOutcome, String humanUser, String humanNote, Instant decidedAt,
                               String agentRecommendation, String agentReasoning, String agentExploreHints,
                               String agentEvidence, String agentRunId, String pricingOffer,
                               String reasonCodes, java.math.BigDecimal computedDti,
                               java.math.BigDecimal computedPti, java.util.List<DecisionToolCall> toolCalls) {
    }
}
