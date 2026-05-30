package com.paf.backend.api;

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

    public record ChatResponse(String reply, String agentRunId) {
    }

    public record ChatMessageView(String sender, String body, Instant createdAt) {
    }
}
