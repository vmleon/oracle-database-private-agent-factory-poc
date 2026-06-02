# Chat backend: async turns + SSE + logout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chat backend non-blocking — `POST /v1/chat` returns immediately with a `turnId`, the ~4-min PAF turn runs on a background executor, and the reply is pushed to the browser over a per-session SSE channel; plus a real `POST /v1/logout` that revokes the session.

**Architecture:** A `ChatEventPublisher` holds one `SseEmitter` per session token. `ChatService.startTurn` persists the customer message, submits `runTurn` to a small executor, and returns a `turnId`; `runTurn` calls PAF (existing apology-retry), persists the agent row, and pushes an `agent`/`error` SSE event. `GET /v1/chat/stream?token=…` registers the emitter. `POST /v1/logout` invalidates the `auth_session` row and drops the emitter.

**Tech Stack:** Java 21, Spring Boot 3 (Spring MVC `SseEmitter`, `ThreadPoolTaskExecutor`), JUnit 5 + Mockito + MockMvc, Gradle.

**Spec:** `docs/superpowers/specs/2026-06-02-chat-ui-async-sse-design.md` (backend portions). The React UI is a separate follow-on plan.

**Deploy note:** podman's `--build` has served stale jars in this project. After implementing, rebuild with `podman compose -f deploy/podman/compose.local.yml build --no-cache application-backend` and verify the class before any live test (see Task 8).

---

## File Structure

- `api/Dtos.java` (modify) — add `TurnAccepted`, `AgentEvent`, `ErrorEvent` records.
- `chat/ChatEventPublisher.java` (create) — per-session `SseEmitter` registry + `pushAgent`/`pushError`/`pushSystem`/`remove`.
- `chat/ChatAsyncConfig.java` (create) — the `chatExecutor` bean.
- `chat/ChatService.java` (modify) — replace `handleTurn` with `startTurn` + async `runTurn` + `openStream`.
- `chat/ChatController.java` (modify) — `POST` → `202 {turnId}`; add `GET /stream`; keep `/history`.
- `login/SessionService.java` (modify) — add `invalidate(token)`.
- `login/LoginService.java` (modify) — add `logout(token)`.
- `login/LoginController.java` (modify) — add `POST /logout`.
- Tests: `chat/ChatEventPublisherTest.java` (create), `chat/ChatServiceTest.java` (rewrite), `chat/ChatControllerTest.java` (modify), `login/SessionServiceTest.java` (modify), `login/LoginServiceTest.java` (modify), `login/LoginControllerTest.java` (create).

All paths below are under `src/backend/src/{main,test}/java/com/bank/appbackend/`.

---

### Task 1: Event + response DTOs

**Files:**

- Modify: `src/backend/src/main/java/com/bank/appbackend/api/Dtos.java`

- [ ] **Step 1: Add the records**

In `Dtos.java`, after the existing `ChatResponse` record, add:

```java
    /** Returned by POST /v1/chat — the async turn id the SSE reply will reference. */
    public record TurnAccepted(String turnId) {
    }

    /** SSE "agent" event payload: the completed reply for a turn. */
    public record AgentEvent(String turnId, String reply, String pafRoomId) {
    }

    /** SSE "error" event payload: the turn failed. */
    public record ErrorEvent(String turnId, String message) {
    }
```

- [ ] **Step 2: Compile**

Run: `cd src/backend && ./gradlew compileJava -q`
Expected: builds with no errors.

- [ ] **Step 3: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/api/Dtos.java
git commit -m "feat(chat): add turn/SSE event DTOs"
```

---

### Task 2: ChatEventPublisher (per-session SSE registry)

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/chat/ChatEventPublisher.java`
- Test: `src/backend/src/test/java/com/bank/appbackend/chat/ChatEventPublisherTest.java`

- [ ] **Step 1: Write the failing test**

Create `ChatEventPublisherTest.java`:

```java
package com.bank.appbackend.chat;

import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

class ChatEventPublisherTest {

    private final ChatEventPublisher publisher = new ChatEventPublisher();

    @Test
    void registerMakesEmitterRetrievableByToken() {
        SseEmitter emitter = publisher.register("sess_a");
        assertThat(emitter).isNotNull();
        assertThat(publisher.hasEmitter("sess_a")).isTrue();
    }

    @Test
    void registerTwiceKeepsOneEmitterPerToken() {
        publisher.register("sess_a");
        publisher.register("sess_a");
        assertThat(publisher.emitterCount()).isEqualTo(1);
        assertThat(publisher.hasEmitter("sess_a")).isTrue();
    }

    @Test
    void removeDropsTheEmitter() {
        publisher.register("sess_a");
        publisher.remove("sess_a");
        assertThat(publisher.hasEmitter("sess_a")).isFalse();
    }

    @Test
    void pushToUnknownTokenIsSafeNoop() {
        assertThatCode(() -> publisher.pushAgent("nobody", "t1", "hi", null)).doesNotThrowAnyException();
        assertThatCode(() -> publisher.pushError("nobody", "t1", "boom")).doesNotThrowAnyException();
    }

    @Test
    void removeUnknownTokenIsSafeNoop() {
        assertThatCode(() -> publisher.remove("nobody")).doesNotThrowAnyException();
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.chat.ChatEventPublisherTest' -q`
Expected: FAIL — `ChatEventPublisher` does not exist.

- [ ] **Step 3: Write the implementation**

Create `ChatEventPublisher.java`:

```java
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.chat.ChatEventPublisherTest' -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/chat/ChatEventPublisher.java \
        src/backend/src/test/java/com/bank/appbackend/chat/ChatEventPublisherTest.java
git commit -m "feat(chat): add per-session SSE event publisher"
```

---

### Task 3: Async executor bean

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/chat/ChatAsyncConfig.java`

No dedicated unit test (a thread-pool bean is exercised by Task 5/6 tests and Task 8).

- [ ] **Step 1: Write the config**

Create `ChatAsyncConfig.java`:

```java
package com.bank.appbackend.chat;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * Executor for chat turns. PAF/vLLM is the bottleneck (~4 min per turn) and turns are
 * one-at-a-time per session, so a small pool is sufficient for the PoC. A turn that can't
 * be queued is rejected and surfaces as an SSE error on that turn.
 */
@Configuration
public class ChatAsyncConfig {

    @Bean(name = "chatExecutor")
    public Executor chatExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(50);
        executor.setThreadNamePrefix("chat-turn-");
        executor.initialize();
        return executor;
    }
}
```

- [ ] **Step 2: Compile**

Run: `cd src/backend && ./gradlew compileJava -q`
Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/chat/ChatAsyncConfig.java
git commit -m "feat(chat): add bounded executor for async turns"
```

---

### Task 4: SessionService.invalidate

**Files:**

- Modify: `src/backend/src/main/java/com/bank/appbackend/login/SessionService.java`
- Test: `src/backend/src/test/java/com/bank/appbackend/login/SessionServiceTest.java`

- [ ] **Step 1: Write the failing test**

Append to `SessionServiceTest.java` (inside the class; it already mocks `AuthSessionRepository repo`):

```java
    @Test
    void invalidateDeletesAnExistingSession() {
        AuthSession session = new AuthSession();
        session.setSessionToken("sess_x");
        when(repo.findById("sess_x")).thenReturn(java.util.Optional.of(session));

        service.invalidate("sess_x");

        verify(repo).delete(session);
    }

    @Test
    void invalidateIsNoopForBlankOrUnknownToken() {
        service.invalidate("   ");
        service.invalidate(null);
        when(repo.findById("ghost")).thenReturn(java.util.Optional.empty());
        service.invalidate("ghost");

        verify(repo, never()).delete(any());
    }
```

If the existing test file lacks them, add imports:

```java
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.login.SessionServiceTest' -q`
Expected: FAIL — `invalidate` is undefined.

- [ ] **Step 3: Add the method**

In `SessionService.java`, add (after `resolve`):

```java
    /** Revoke a session so its token can no longer be used. Idempotent. */
    public void invalidate(String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        repo.findById(token).ifPresent(repo::delete);
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.login.SessionServiceTest' -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/login/SessionService.java \
        src/backend/src/test/java/com/bank/appbackend/login/SessionServiceTest.java
git commit -m "feat(login): add session invalidation"
```

---

### Task 5: ChatService — startTurn / runTurn / openStream

**Files:**

- Modify: `src/backend/src/main/java/com/bank/appbackend/chat/ChatService.java`
- Test: `src/backend/src/test/java/com/bank/appbackend/chat/ChatServiceTest.java` (rewrite)

- [ ] **Step 1: Rewrite the test**

Replace the entire body of `ChatServiceTest.java` with:

```java
package com.bank.appbackend.chat;

import com.bank.appbackend.domain.AuthSession;
import com.bank.appbackend.domain.ChatMessage;
import com.bank.appbackend.domain.ChatMessageRepository;
import com.bank.appbackend.login.SessionService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ChatServiceTest {

    private final SessionService sessions = mock(SessionService.class);
    private final ChatMessageRepository messages = mock(ChatMessageRepository.class);
    private final PafClient paf = mock(PafClient.class);
    private final ChatEventPublisher events = mock(ChatEventPublisher.class);
    // Synchronous executor so submitted runTurn runs inline within the test.
    private final ChatService service =
            new ChatService(sessions, messages, paf, events, Runnable::run);

    private static final String APOLOGY =
            "Sorry — we couldn't process your application right now. Please try again in a moment.";

    private AuthSession session() {
        AuthSession s = new AuthSession();
        s.setSessionToken("sess_1");
        s.setCustomerId(1L);
        s.setApplicationId(7L);
        return s;
    }

    @Test
    void startTurnPersistsBothMessagesPushesAgentAndReturnsTurnId() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString())).thenReturn(new PafClient.Result("agent reply", "paf-room-1"));

        String turnId = service.startTurn("sess_1", "hello");

        assertThat(turnId).isNotBlank();
        ArgumentCaptor<ChatMessage> captor = ArgumentCaptor.forClass(ChatMessage.class);
        verify(messages, times(2)).save(captor.capture());
        assertThat(captor.getAllValues().get(0).getSender()).isEqualTo("CUSTOMER");
        assertThat(captor.getAllValues().get(0).getRoomId()).isEqualTo("room-cust-1");
        assertThat(captor.getAllValues().get(1).getSender()).isEqualTo("AGENT");
        assertThat(captor.getAllValues().get(1).getBody()).isEqualTo("agent reply");
        assertThat(captor.getAllValues().get(1).getPafRoomId()).isEqualTo("paf-room-1");
        verify(events).pushAgent(eq("sess_1"), eq(turnId), eq("agent reply"), eq("paf-room-1"));
    }

    @Test
    void runTurnEnvelopesTheToken() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        ArgumentCaptor<String> sent = ArgumentCaptor.forClass(String.class);
        when(paf.run(sent.capture())).thenReturn(new PafClient.Result("ok", null));

        service.startTurn("sess_1", "I want a loan");

        assertThat(sent.getValue()).isEqualTo("[[SESSION sess_1]]\nI want a loan");
    }

    @Test
    void pafFailurePushesErrorAndPersistsNoAgentRow() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString())).thenThrow(new ResponseStatusException(
                org.springframework.http.HttpStatus.BAD_GATEWAY, "boom"));

        String turnId = service.startTurn("sess_1", "hello");

        verify(messages, times(1)).save(any(ChatMessage.class)); // CUSTOMER only
        verify(events).pushError(eq("sess_1"), eq(turnId), anyString());
        verify(events, never()).pushAgent(anyString(), anyString(), anyString(), any());
    }

    @Test
    void retriesPastTheApologyThenPushesTheRealReply() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString()))
                .thenReturn(new PafClient.Result(APOLOGY, "room-a"))
                .thenReturn(new PafClient.Result("agent reply", "room-b"));

        String turnId = service.startTurn("sess_1", "hello");

        verify(paf, times(2)).run(anyString());
        verify(events).pushAgent(eq("sess_1"), eq(turnId), eq("agent reply"), eq("room-b"));
    }

    @Test
    void givesUpAfterMaxAttemptsAndPushesTheApology() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString())).thenReturn(new PafClient.Result(APOLOGY, "room-x"));

        String turnId = service.startTurn("sess_1", "hello");

        verify(paf, times(3)).run(anyString()); // 1 try + 2 retries
        verify(events).pushAgent(eq("sess_1"), eq(turnId), eq(APOLOGY), eq("room-x"));
    }

    @Test
    void openStreamResolvesSessionThenRegistersEmitter() {
        when(sessions.resolve("sess_1")).thenReturn(session());

        service.openStream("sess_1");

        verify(sessions).resolve("sess_1");
        verify(events).register("sess_1");
    }

    @Test
    void historyReturnsOrderedViews() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        ChatMessage m = new ChatMessage();
        m.setSender("CUSTOMER");
        m.setBody("hi");
        when(messages.findByCustomerIdOrderByMessageIdAsc(1L)).thenReturn(java.util.List.of(m));

        var views = service.history("sess_1");

        assertThat(views).hasSize(1);
        assertThat(views.get(0).sender()).isEqualTo("CUSTOMER");
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.chat.ChatServiceTest' -q`
Expected: FAIL — constructor arity and `startTurn`/`openStream` don't exist.

- [ ] **Step 3: Rewrite ChatService**

Replace the whole `ChatService.java` with:

```java
package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import com.bank.appbackend.domain.AuthSession;
import com.bank.appbackend.domain.ChatMessage;
import com.bank.appbackend.domain.ChatMessageRepository;
import com.bank.appbackend.login.SessionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executor;

@Service
public class ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    // The fixed fail-secure apology the flow returns when get_context can't resolve the session
    // (in practice: PAF's streamed tool-call corrupted the token). Used to detect-and-retry.
    private static final String PAF_APOLOGY =
            "Sorry — we couldn't process your application right now. Please try again in a moment.";
    private static final int MAX_PAF_ATTEMPTS = 3; // 1 try + 2 retries

    private final SessionService sessions;
    private final ChatMessageRepository messages;
    private final PafClient paf;
    private final ChatEventPublisher events;
    private final Executor chatExecutor;

    public ChatService(SessionService sessions, ChatMessageRepository messages, PafClient paf,
                       ChatEventPublisher events, @Qualifier("chatExecutor") Executor chatExecutor) {
        this.sessions = sessions;
        this.messages = messages;
        this.paf = paf;
        this.events = events;
        this.chatExecutor = chatExecutor;
    }

    /** Open (or replace) the customer's SSE channel. Fails 401 if the token is bad. */
    public SseEmitter openStream(String token) {
        sessions.resolve(token);
        return events.register(token);
    }

    /** Persist the customer message, kick off the PAF turn in the background, return its id. */
    public String startTurn(String token, String message) {
        AuthSession session = sessions.resolve(token);
        String roomId = roomId(session);
        save(session, roomId, "CUSTOMER", message, null);
        String turnId = UUID.randomUUID().toString();
        chatExecutor.execute(() -> runTurn(token, message, session, roomId, turnId));
        return turnId;
    }

    /** Background worker: call PAF (with apology-retry), persist the reply, push it over SSE. */
    void runTurn(String token, String message, AuthSession session, String roomId, String turnId) {
        try {
            String enveloped = Envelope.build(token, message);
            PafClient.Result result = paf.run(enveloped);
            // PAF streams agent tool-calls; vLLM occasionally corrupts the session_token, so
            // get_context fails and the flow returns the fixed apology. Re-run a couple of times.
            for (int attempt = 2; attempt <= MAX_PAF_ATTEMPTS && PAF_APOLOGY.equals(result.reply()); attempt++) {
                result = paf.run(enveloped);
            }
            save(session, roomId, "AGENT", result.reply(), result.pafRoomId());
            events.pushAgent(token, turnId, result.reply(), result.pafRoomId());
        } catch (RuntimeException e) {
            log.warn("chat turn {} failed", turnId, e);
            events.pushError(token, turnId, "We couldn't get a response. Please try again.");
        }
    }

    @Transactional(readOnly = true)
    public List<ChatMessageView> history(String token) {
        AuthSession session = sessions.resolve(token);
        return messages.findByCustomerIdOrderByMessageIdAsc(session.getCustomerId()).stream()
                .map(m -> new ChatMessageView(m.getSender(), m.getBody(), m.getCreatedAt()))
                .toList();
    }

    private void save(AuthSession session, String roomId, String sender, String body, String pafRoomId) {
        ChatMessage m = new ChatMessage();
        m.setRoomId(roomId);
        m.setCustomerId(session.getCustomerId());
        m.setApplicationId(session.getApplicationId());
        m.setSender(sender);
        m.setBody(body);
        m.setPafRoomId(pafRoomId);
        messages.save(m);
    }

    private String roomId(AuthSession session) {
        return "room-cust-" + session.getCustomerId();
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.chat.ChatServiceTest' -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/chat/ChatService.java \
        src/backend/src/test/java/com/bank/appbackend/chat/ChatServiceTest.java
git commit -m "feat(chat): async startTurn/runTurn with SSE push"
```

---

### Task 6: ChatController — 202 + SSE stream

**Files:**

- Modify: `src/backend/src/main/java/com/bank/appbackend/chat/ChatController.java`
- Test: `src/backend/src/test/java/com/bank/appbackend/chat/ChatControllerTest.java`

- [ ] **Step 1: Rewrite the controller test**

Replace the whole `ChatControllerTest.java` with:

```java
package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(ChatController.class)
class ChatControllerTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    ChatService chatService;

    @Test
    void chatReturns202WithTurnId() throws Exception {
        when(chatService.startTurn(eq("sess_1"), eq("hi"))).thenReturn("turn-9");

        mvc.perform(post("/v1/chat")
                        .header("X-Session-Token", "sess_1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message\":\"hi\"}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.turnId").value("turn-9"));
    }

    @Test
    void chatWithBadTokenIs401() throws Exception {
        when(chatService.startTurn(eq(null), eq("hi")))
                .thenThrow(new ResponseStatusException(org.springframework.http.HttpStatus.UNAUTHORIZED));

        mvc.perform(post("/v1/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message\":\"hi\"}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void streamStartsAnSseResponse() throws Exception {
        when(chatService.openStream(eq("sess_1"))).thenReturn(new SseEmitter());

        mvc.perform(get("/v1/chat/stream").param("token", "sess_1"))
                .andExpect(request().asyncStarted());
    }

    @Test
    void historyReturnsMessages() throws Exception {
        when(chatService.history(eq("sess_1")))
                .thenReturn(List.of(new ChatMessageView("AGENT", "hello", null)));

        mvc.perform(get("/v1/chat/history").header("X-Session-Token", "sess_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].sender").value("AGENT"))
                .andExpect(jsonPath("$[0].body").value("hello"));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.chat.ChatControllerTest' -q`
Expected: FAIL — `startTurn`/`openStream` not on controller, `POST` returns the old shape.

- [ ] **Step 3: Rewrite the controller**

Replace the whole `ChatController.java` with:

```java
package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import com.bank.appbackend.api.Dtos.ChatRequest;
import com.bank.appbackend.api.Dtos.TurnAccepted;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

@RestController
@RequestMapping("/v1/chat")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    /** Start a turn; the reply arrives later on the SSE channel. */
    @PostMapping
    public ResponseEntity<TurnAccepted> chat(
            @RequestHeader(value = "X-Session-Token", required = false) String token,
            @RequestBody ChatRequest request) {
        String turnId = chatService.startTurn(token, request.message());
        return ResponseEntity.accepted().body(new TurnAccepted(turnId));
    }

    /**
     * Per-session SSE channel. The browser's native EventSource cannot send headers, so the
     * token comes as a query parameter (PoC tradeoff documented in the design spec).
     */
    @GetMapping("/stream")
    public SseEmitter stream(@RequestParam("token") String token) {
        return chatService.openStream(token);
    }

    @GetMapping("/history")
    public List<ChatMessageView> history(
            @RequestHeader(value = "X-Session-Token", required = false) String token) {
        return chatService.history(token);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.chat.ChatControllerTest' -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/chat/ChatController.java \
        src/backend/src/test/java/com/bank/appbackend/chat/ChatControllerTest.java
git commit -m "feat(chat): 202 + SSE stream endpoints"
```

---

### Task 7: Logout — service + endpoint

**Files:**

- Modify: `src/backend/src/main/java/com/bank/appbackend/login/LoginService.java`
- Modify: `src/backend/src/main/java/com/bank/appbackend/login/LoginController.java`
- Modify: `src/backend/src/test/java/com/bank/appbackend/login/LoginServiceTest.java`
- Create: `src/backend/src/test/java/com/bank/appbackend/login/LoginControllerTest.java`

- [ ] **Step 1: Write the failing service test**

In `LoginServiceTest.java`, the `LoginService` constructor is gaining a `ChatEventPublisher` param. Update the test's construction of `LoginService` to pass a mock, add a field `private final ChatEventPublisher events = mock(ChatEventPublisher.class);`, then add:

```java
    @Test
    void logoutInvalidatesSessionAndDropsEmitter() {
        service.logout("sess_7");

        verify(sessionService).invalidate("sess_7");
        verify(events).remove("sess_7");
    }
```

Ensure these imports exist:

```java
import com.bank.appbackend.chat.ChatEventPublisher;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
```

(`sessionService` is the existing mock in that test; if it is currently a real instance, change it to `mock(SessionService.class)` and update the constructor call accordingly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.login.LoginServiceTest' -q`
Expected: FAIL — constructor arity / `logout` undefined.

- [ ] **Step 3: Add logout to LoginService**

In `LoginService.java`: import `com.bank.appbackend.chat.ChatEventPublisher`; add the field, constructor param, and method:

```java
    private final ChatEventPublisher events;
```

Update the constructor signature to also accept `ChatEventPublisher events` and assign `this.events = events;`. Then add:

```java
    /** Revoke the session and drop its SSE channel. Idempotent / best-effort. */
    public void logout(String token) {
        sessionService.invalidate(token);
        events.remove(token);
    }
```

- [ ] **Step 4: Run service test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.login.LoginServiceTest' -q`
Expected: PASS.

- [ ] **Step 5: Write the failing controller test**

Create `LoginControllerTest.java`:

```java
package com.bank.appbackend.login;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(LoginController.class)
class LoginControllerTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    LoginService loginService;

    @Test
    void logoutReturns204AndInvalidatesSession() throws Exception {
        mvc.perform(post("/v1/logout").header("X-Session-Token", "sess_1"))
                .andExpect(status().isNoContent());

        verify(loginService).logout("sess_1");
    }

    @Test
    void logoutWithoutTokenStillReturns204() throws Exception {
        mvc.perform(post("/v1/logout"))
                .andExpect(status().isNoContent());

        verify(loginService).logout(null);
    }
}
```

- [ ] **Step 6: Run controller test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.login.LoginControllerTest' -q`
Expected: FAIL — no `/v1/logout` mapping.

- [ ] **Step 7: Add the endpoint**

In `LoginController.java`: import `org.springframework.http.ResponseEntity` and `org.springframework.web.bind.annotation.RequestHeader`; add:

```java
    @PostMapping("/logout")
    public ResponseEntity<Void> logout(
            @RequestHeader(value = "X-Session-Token", required = false) String token) {
        loginService.logout(token);
        return ResponseEntity.noContent().build();
    }
```

- [ ] **Step 8: Run both logout tests to verify they pass**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.login.LoginServiceTest' --tests 'com.bank.appbackend.login.LoginControllerTest' -q`
Expected: PASS.

- [ ] **Step 9: Full suite + commit**

Run: `cd src/backend && ./gradlew test -q`
Expected: BUILD SUCCESSFUL, 0 failures.

```bash
git add src/backend/src/main/java/com/bank/appbackend/login/LoginService.java \
        src/backend/src/main/java/com/bank/appbackend/login/LoginController.java \
        src/backend/src/test/java/com/bank/appbackend/login/LoginServiceTest.java \
        src/backend/src/test/java/com/bank/appbackend/login/LoginControllerTest.java
git commit -m "feat(login): add POST /v1/logout session revocation"
```

---

### Task 8: Manual end-to-end verification (live stack)

No code. Confirms the async + SSE + logout path works against the running stack, and guards against the stale-jar trap.

- [ ] **Step 1: Rebuild the backend image WITHOUT cache and recreate**

```bash
cd /Users/vmartina/Documents/ws/oracle-database-private-agent-factory-poc
podman compose -f deploy/podman/compose.local.yml build --no-cache application-backend
podman compose -f deploy/podman/compose.local.yml up -d --force-recreate --no-deps application-backend
```

- [ ] **Step 2: Verify the new code is actually deployed**

```bash
rm -rf ./_jc && mkdir -p ./_jc && podman cp application-backend:/app/app.jar ./_jc/app.jar
cd ./_jc && unzip -o -q app.jar 'BOOT-INF/classes/com/bank/appbackend/chat/*'
grep -a -o "openStream" BOOT-INF/classes/com/bank/appbackend/chat/ChatService.class && echo "NEW CODE DEPLOYED"
cd .. && rm -rf ./_jc
```

Expected: prints `openStream` then `NEW CODE DEPLOYED`.

- [ ] **Step 3: Health + login**

```bash
curl -s -m 10 http://localhost:8090/actuator/health; echo
TOK=$(curl -s -m 20 -X POST http://localhost:8090/v1/login -H 'Content-Type: application/json' -d '{"customerId":1}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["sessionToken"])')
echo "token=$TOK"
```

Expected: `{"status":"UP"}` and a `sess_...` token.

- [ ] **Step 4: Open the SSE stream in the background, then send a turn**

In one command, open the stream to a file, fire a chat turn, and watch for the pushed event (the turn takes ~3–4 min):

```bash
( curl -sN -m 360 "http://localhost:8090/v1/chat/stream?token=$TOK" > /tmp/sse.out & echo $! > /tmp/sse.pid )
sleep 2
curl -s -m 20 -X POST http://localhost:8090/v1/chat -H 'Content-Type: application/json' \
  -H "X-Session-Token: $TOK" -d '{"message":"What is the status of my loan application?"}' -w '\n[HTTP %{http_code}]\n'
```

Expected: immediate `[HTTP 202]` with a `{"turnId":"..."}` body.

- [ ] **Step 5: Wait for the pushed reply, then inspect the stream**

Use Monitor (or re-read the file) until the `agent` event lands, then:

```bash
cat /tmp/sse.out
```

Expected: an SSE frame like `event:agent` / `data:{"turnId":"...","reply":"Looks strong — ...","pafRoomId":"..."}`.

- [ ] **Step 6: Confirm persistence (history) and logout revocation**

```bash
curl -s -m 20 http://localhost:8090/v1/chat/history -H "X-Session-Token: $TOK" | python3 -m json.tool | tail -8
curl -s -m 10 -o /dev/null -w "logout HTTP %{http_code}\n" -X POST http://localhost:8090/v1/logout -H "X-Session-Token: $TOK"
curl -s -m 10 -o /dev/null -w "chat-after-logout HTTP %{http_code}\n" -X POST http://localhost:8090/v1/chat \
  -H 'Content-Type: application/json' -H "X-Session-Token: $TOK" -d '{"message":"hi"}'
kill "$(cat /tmp/sse.pid)" 2>/dev/null
```

Expected: history shows the CUSTOMER + AGENT rows; `logout HTTP 204`; `chat-after-logout HTTP 401` (token revoked).

- [ ] **Step 7: Done**

No commit (verification only). If any step fails, fix the relevant task before proceeding to the UI plan.

---

## Self-review notes

- **Spec coverage:** `POST /v1/chat`→202 (Task 6), SSE channel + `agent`/`error` push (Tasks 2,5,6), executor (Task 3), apology-retry preserved (Task 5), `pafRoomId` preserved (Task 5), `GET /history` unchanged (Task 6), `POST /v1/logout` revoke + emitter drop (Tasks 4,7), `pushSystem` path laid uncalled (Task 2). The `?token=` SSE auth is implemented in Task 6.
- **Out of scope (this plan):** the React UI (separate plan), production CORS/serving, HITL push wiring.
- **Type consistency:** `startTurn(String,String)→String`, `runTurn(String,String,AuthSession,String,String)`, `openStream(String)→SseEmitter`, `ChatEventPublisher.{register,pushAgent,pushError,pushSystem,remove}`, `SessionService.invalidate(String)`, `LoginService.logout(String)`, DTOs `TurnAccepted/AgentEvent/ErrorEvent` — used consistently across tasks.
