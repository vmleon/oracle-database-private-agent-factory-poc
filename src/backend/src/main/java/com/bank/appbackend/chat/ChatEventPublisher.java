package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.AgentEvent;
import com.bank.appbackend.api.Dtos.ErrorEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Holds one open SSE channel per session token and pushes turn results to it. */
@Component
public class ChatEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(ChatEventPublisher.class);
    // The channel lives for the chat session; matches the 8h session TTL.
    private static final long STREAM_TIMEOUT_MS = Duration.ofHours(8).toMillis();

    private final Map<String, SseEmitter> emitters = new ConcurrentHashMap<>();

    /** Open (or replace) the SSE channel for a session token. */
    public SseEmitter register(String token) {
        SseEmitter emitter = new SseEmitter(STREAM_TIMEOUT_MS);
        SseEmitter previous = emitters.put(token, emitter);
        if (previous != null) {
            try {
                previous.complete();
            } catch (RuntimeException ignored) {
                // already closed
            }
        }
        emitter.onCompletion(() -> emitters.remove(token, emitter));
        emitter.onTimeout(() -> emitters.remove(token, emitter));
        emitter.onError(e -> emitters.remove(token, emitter));
        // Flush an initial comment so the response commits immediately and the browser's
        // EventSource fires 'open' right away — otherwise headers aren't sent until the first
        // real event (minutes later) and the client sits in "connecting" for the whole turn.
        try {
            emitter.send(SseEmitter.event().comment("connected"));
        } catch (IOException e) {
            emitters.remove(token, emitter);
        }
        return emitter;
    }

    public void pushAgent(String token, String turnId, String reply, String pafRoomId) {
        send(token, "agent", new AgentEvent(turnId, reply, pafRoomId));
    }

    public void pushError(String token, String turnId, String message) {
        send(token, "error", new ErrorEvent(turnId, message));
    }

    /** Reserved for the future HITL outcome push — not called yet. */
    public void pushSystem(String token, String turnId, String body) {
        send(token, "system", Map.of("turnId", turnId, "body", body));
    }

    /** Proactively close + drop the channel (e.g. on logout). Idempotent. */
    public void remove(String token) {
        SseEmitter emitter = emitters.remove(token);
        if (emitter != null) {
            try {
                emitter.complete();
            } catch (RuntimeException ignored) {
                // already closed
            }
        }
    }

    // --- test seams ---
    boolean hasEmitter(String token) {
        return emitters.containsKey(token);
    }

    int emitterCount() {
        return emitters.size();
    }

    private void send(String token, String event, Object data) {
        SseEmitter emitter = emitters.get(token);
        if (emitter == null) {
            log.debug("no SSE emitter for token; dropping '{}' event", event);
            return;
        }
        try {
            emitter.send(SseEmitter.event().name(event).data(data, MediaType.APPLICATION_JSON));
        } catch (IOException | IllegalStateException e) {
            log.warn("SSE '{}' send failed; dropping emitter", event, e);
            if (emitters.remove(token, emitter)) {
                try {
                    emitter.completeWithError(e);
                } catch (RuntimeException ignored) {
                    // already closed
                }
            }
        }
    }
}
