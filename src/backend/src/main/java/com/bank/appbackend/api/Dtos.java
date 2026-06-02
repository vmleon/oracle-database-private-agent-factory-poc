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
}
