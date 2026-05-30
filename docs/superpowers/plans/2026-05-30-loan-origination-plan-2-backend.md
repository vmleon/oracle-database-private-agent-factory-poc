# Loan Origination — Plan 2: Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Spring backend support conversational origination: let a customer with **no** application log in, list no-application customers, strip agent marker blocks from chat replies, and key the chat room/history by customer (so the thread spans the pre-app → app transition).

**Architecture:** The session token binds to the **customer**; the application is resolved downstream (by the MCP tools from Plan 1), so the backend no longer requires an open application at login and `auth_session.application_id` is an optional cache. Chat replies from PAF carry leading `[[MARKER …]]` blocks that the backend strips before showing/persisting the customer-facing text. The chat room is `room-cust-{customerId}` and history is read by customer.

**Tech Stack:** Java 21, Spring Boot 3.4, Spring Data JPA, JUnit 5 + Mockito + AssertJ, Gradle.

**Verification style:** the backend has a real unit-test suite (25 tests, `./gradlew test`, Mockito + AssertJ). These tasks are **TDD**: write/adjust the failing test, see it fail, implement, see it pass, commit. The final task adds a live curl smoke against the running stack (the Plan-1 no-app customer `Liam NoApplication`).

This is **Plan 2 of 3**. Plan 1 (data + tools) is merged on this branch. Plan 3 = PAF flow. Spec: `docs/superpowers/specs/2026-05-30-loan-origination-chat-design.md`.

Run all backend tests from `src/backend`: `./gradlew test`.

---

## File Structure

- Modify: `src/backend/src/main/java/com/paf/backend/chat/Envelope.java` — add `stripMarkers`, apply in `extractReply`.
- Modify: `src/backend/src/main/java/com/paf/backend/api/Dtos.java` — add `CustomerSummary` record.
- Modify: `src/backend/src/main/java/com/paf/backend/domain/CustomerRepository.java` — LEFT JOIN so no-app customers are included.
- Modify: `src/backend/src/main/java/com/paf/backend/login/LoginService.java` — map to `CustomerSummary`; no-app login.
- Modify: `src/backend/src/main/java/com/paf/backend/login/LoginController.java` — return `List<CustomerSummary>`.
- Modify: `src/backend/src/main/java/com/paf/backend/chat/ChatService.java` — customer-keyed room + history.
- Modify: `src/backend/src/main/java/com/paf/backend/domain/ChatMessageRepository.java` — `findByCustomerIdOrderByMessageIdAsc`.
- Modify tests: `EnvelopeTest.java`, `LoginServiceTest.java`, `ChatServiceTest.java` (+ `ChatControllerTest.java` only if it asserts the room).

---

## Task 1: Strip agent marker blocks from replies

PAF agents emit a leading `[[MARKER …]]` block (machine-readable) before the customer-facing text. The backend must return only the human text.

**Files:**

- Modify: `src/backend/src/main/java/com/paf/backend/chat/Envelope.java`
- Test: `src/backend/src/test/java/com/paf/backend/chat/EnvelopeTest.java`

- [ ] **Step 1: Add failing tests** to `EnvelopeTest.java` (inside the class, after the existing `extractReply…` tests):

```java
    @Test
    void stripMarkersRemovesLeadingMarkerBlock() {
        assertThat(Envelope.stripMarkers("[[INTAKE status=COLLECTING]]\nHow much would you like to borrow?"))
                .isEqualTo("How much would you like to borrow?");
    }

    @Test
    void stripMarkersRemovesMultipleLeadingMarkers() {
        assertThat(Envelope.stripMarkers("[[DECISION tier=REVIEW]]\n[[EVIDENCE x=1]]\nWe'll follow up."))
                .isEqualTo("We'll follow up.");
    }

    @Test
    void stripMarkersLeavesPlainTextUntouched() {
        assertThat(Envelope.stripMarkers("Just a normal reply.")).isEqualTo("Just a normal reply.");
    }

    @Test
    void stripMarkersHandlesMarkerOnlyAndNull() {
        assertThat(Envelope.stripMarkers("[[APPLICATION_CREATED id=42]]")).isEmpty();
        assertThat(Envelope.stripMarkers(null)).isEmpty();
    }

    @Test
    void extractReplyStripsMarkerFromLiveShape() throws Exception {
        var root = mapper.readTree("{\"message\":\"[[INTAKE status=READY]]\\nGreat, let's review it.\",\"roomId\":\"r1\"}");
        assertThat(Envelope.extractReply(root)).isEqualTo("Great, let's review it.");
    }
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `./gradlew test --tests 'com.paf.backend.chat.EnvelopeTest'`
Expected: FAIL — `stripMarkers` is undefined / `extractReply` still returns the marker.

- [ ] **Step 3: Implement `stripMarkers` and apply it in `extractReply`**

In `Envelope.java`, add the pattern next to the existing `SENTINEL` pattern:

```java
    private static final Pattern LEADING_MARKERS = Pattern.compile("^(?:\\s*\\[\\[[^\\]]*\\]\\]\\s*)+");
```

Add the method (place it near `sanitize`):

```java
    /** Remove leading [[MARKER ...]] block(s) an agent emits before the customer-facing text. */
    public static String stripMarkers(String text) {
        if (text == null) {
            return "";
        }
        return LEADING_MARKERS.matcher(text).replaceFirst("").strip();
    }
```

Then change the two return points in `extractReply` so the returned text is stripped. Currently:

```java
        if (data.isTextual()) {
            return data.asText();
        }
        for (String field : REPLY_FIELDS) {
            if (data.hasNonNull(field) && data.get(field).isTextual()) {
                return data.get(field).asText();
            }
        }
```

becomes:

```java
        if (data.isTextual()) {
            return stripMarkers(data.asText());
        }
        for (String field : REPLY_FIELDS) {
            if (data.hasNonNull(field) && data.get(field).isTextual()) {
                return stripMarkers(data.get(field).asText());
            }
        }
```

(The final `throw new IllegalStateException(...)` line stays unchanged.)

- [ ] **Step 4: Run tests, confirm pass**

Run: `./gradlew test --tests 'com.paf.backend.chat.EnvelopeTest'`
Expected: PASS (all EnvelopeTest tests).

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/paf/backend/chat/Envelope.java src/backend/src/test/java/com/paf/backend/chat/EnvelopeTest.java
git commit -m "feat(backend): strip agent marker blocks from chat replies"
```

---

## Task 2: `/v1/customers` includes no-application customers with a flag

The demo must be able to pick a customer who has no application (to start intake).

**Files:**

- Modify: `src/backend/src/main/java/com/paf/backend/api/Dtos.java`
- Modify: `src/backend/src/main/java/com/paf/backend/domain/CustomerRepository.java`
- Modify: `src/backend/src/main/java/com/paf/backend/login/LoginService.java`
- Modify: `src/backend/src/main/java/com/paf/backend/login/LoginController.java`
- Test: `src/backend/src/test/java/com/paf/backend/login/LoginServiceTest.java`

- [ ] **Step 1: Add the `CustomerSummary` record** to `Dtos.java` (after `LoginResponse`):

```java
    public record CustomerSummary(Long customerId, String name, Long applicationId,
                                  String productType, java.math.BigDecimal amountRequested,
                                  Integer termMonths, boolean hasOpenApplication) {
    }
```

- [ ] **Step 2: Add a failing test** to `LoginServiceTest.java`. First add imports at the top:

```java
import com.paf.backend.api.Dtos.CustomerSummary;
import com.paf.backend.domain.CustomerOption;
import com.paf.backend.domain.CustomerRepository;
import java.util.List;
```

Replace the inline `mock(com.paf.backend.domain.CustomerRepository.class)` in the field initializer with a named field so the test can stub it:

```java
    private final LoanApplicationRepository appRepo = mock(LoanApplicationRepository.class);
    private final SessionService sessionService = mock(SessionService.class);
    private final CustomerRepository customers = mock(CustomerRepository.class);
    private final LoginService service = new LoginService(appRepo, sessionService, customers);
```

Add the test (with a small CustomerOption stub helper):

```java
    @Test
    void listCustomersMarksWhetherAnApplicationIsOpen() {
        when(customers.findCustomerOptions()).thenReturn(List.of(
                option(1L, "Alice", 7L), option(21L, "Liam", null)));

        List<CustomerSummary> result = service.listCustomers();

        assertThat(result).hasSize(2);
        assertThat(result.get(0).hasOpenApplication()).isTrue();
        assertThat(result.get(0).applicationId()).isEqualTo(7L);
        assertThat(result.get(1).name()).isEqualTo("Liam");
        assertThat(result.get(1).hasOpenApplication()).isFalse();
        assertThat(result.get(1).applicationId()).isNull();
    }

    private CustomerOption option(Long custId, String name, Long appId) {
        return new CustomerOption() {
            public Long getCustomerId() { return custId; }
            public String getName() { return name; }
            public Long getApplicationId() { return appId; }
            public String getProductType() { return appId == null ? null : "PERSONAL_LOAN"; }
            public java.math.BigDecimal getAmountRequested() { return appId == null ? null : new java.math.BigDecimal("10000"); }
            public Integer getTermMonths() { return appId == null ? null : 24; }
        };
    }
```

- [ ] **Step 3: Run the test, confirm it fails**

Run: `./gradlew test --tests 'com.paf.backend.login.LoginServiceTest'`
Expected: FAIL — `findCustomerOptions` undefined and `listCustomers` returns `List<CustomerOption>`, not `List<CustomerSummary>`.

- [ ] **Step 4: Change the repository query to a LEFT JOIN** in `CustomerRepository.java` — rename `findOpenApplicationOptions` to `findCustomerOptions` and include customers with no open application:

```java
    @Query(value = """
            SELECT c.customer_id   AS customerId,
                   c.full_name     AS name,
                   la.application_id AS applicationId,
                   pc.product_type AS productType,
                   la.amount_requested AS amountRequested,
                   la.term_months  AS termMonths
              FROM APP.customer c
              LEFT JOIN APP.loan_application la
                     ON la.customer_id = c.customer_id
                    AND la.status IN ('DRAFT','SUBMITTED','IN_REVIEW')
              LEFT JOIN APP.product_catalog pc ON pc.product_id = la.product_id
             ORDER BY c.customer_id, la.application_id
            """, nativeQuery = true)
    List<CustomerOption> findCustomerOptions();
```

- [ ] **Step 5: Map to `CustomerSummary` in `LoginService.listCustomers`** — change the method (and add the import `com.paf.backend.api.Dtos.CustomerSummary`):

```java
    /** All customers for the mock-login dropdown, flagged by whether they have an open application. */
    public List<CustomerSummary> listCustomers() {
        return customers.findCustomerOptions().stream()
                .map(o -> new CustomerSummary(o.getCustomerId(), o.getName(), o.getApplicationId(),
                        o.getProductType(), o.getAmountRequested(), o.getTermMonths(),
                        o.getApplicationId() != null))
                .toList();
    }
```

- [ ] **Step 6: Update the controller** return type in `LoginController.java`:

```java
    @GetMapping("/customers")
    public List<com.paf.backend.api.Dtos.CustomerSummary> customers() {
        return loginService.listCustomers();
    }
```

(Remove the now-unused `CustomerOption` import if present.)

- [ ] **Step 7: Run tests, confirm pass**

Run: `./gradlew test --tests 'com.paf.backend.login.LoginServiceTest'`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/backend/src/main/java/com/paf/backend/api/Dtos.java src/backend/src/main/java/com/paf/backend/domain/CustomerRepository.java src/backend/src/main/java/com/paf/backend/login/LoginService.java src/backend/src/main/java/com/paf/backend/login/LoginController.java src/backend/src/test/java/com/paf/backend/login/LoginServiceTest.java
git commit -m "feat(backend): list no-application customers with hasOpenApplication flag"
```

---

## Task 3: No-application login

Login no longer 404s a customer without an application; it mints a customer-bound session (room keyed by customer; `applicationId` cached if an open one exists, else null).

**Files:**

- Modify: `src/backend/src/main/java/com/paf/backend/login/LoginService.java`
- Test: `src/backend/src/test/java/com/paf/backend/login/LoginServiceTest.java`

- [ ] **Step 1: Replace the two login tests** in `LoginServiceTest.java`. Delete `loginRaises404WhenNoOpenApplication` and replace `loginMintsTokenForOpenApplication`; add the no-app case. (Note the new room format and the `mint` overload taking a nullable applicationId.)

```java
    @Test
    void loginMintsTokenForOpenApplication() {
        when(appRepo.findOpenByCustomer(1L)).thenReturn(Optional.of(stubApp(7L)));
        when(sessionService.mint(1L, 7L)).thenReturn("sess_abc");

        LoginResponse resp = service.login(1L);

        assertThat(resp.sessionToken()).isEqualTo("sess_abc");
        assertThat(resp.applicationId()).isEqualTo(7L);
        assertThat(resp.roomId()).isEqualTo("room-cust-1");
    }

    @Test
    void loginMintsTokenForCustomerWithNoApplication() {
        when(appRepo.findOpenByCustomer(21L)).thenReturn(Optional.empty());
        when(sessionService.mint(21L, null)).thenReturn("sess_xyz");

        LoginResponse resp = service.login(21L);

        assertThat(resp.sessionToken()).isEqualTo("sess_xyz");
        assertThat(resp.applicationId()).isNull();
        assertThat(resp.roomId()).isEqualTo("room-cust-21");
    }
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `./gradlew test --tests 'com.paf.backend.login.LoginServiceTest'`
Expected: FAIL — current `login` throws 404 for the no-app customer and builds `room-app-…`.

- [ ] **Step 3: Rewrite `LoginService.login`**

```java
    /** Mint a session bound to the customer. The open application (if any) is cached on the
     *  session; a customer with none enters intake. Room is keyed by customer so the thread is
     *  stable across the pre-application -> application transition. */
    public LoginResponse login(Long customerId) {
        Long applicationId = applications.findOpenByCustomer(customerId)
                .map(LoanApplication::getApplicationId)
                .orElse(null);
        String token = sessionService.mint(customerId, applicationId);
        String roomId = "room-cust-" + customerId;
        return new LoginResponse(token, customerId, applicationId, roomId);
    }
```

Remove the now-unused imports (`HttpStatus`, `ResponseStatusException`) if they are no longer referenced anywhere in the file.

- [ ] **Step 4: Confirm `SessionService.mint` accepts a null applicationId**

Open `src/backend/src/main/java/com/paf/backend/login/SessionService.java`. `mint(Long customerId, Long applicationId)` already calls `session.setApplicationId(applicationId)`. A null is fine (the column is nullable as of changeset 012). No change needed — just confirm; if `mint` does anything that NPEs on a null applicationId, guard it.

- [ ] **Step 5: Run tests, confirm pass**

Run: `./gradlew test --tests 'com.paf.backend.login.LoginServiceTest'`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backend/src/main/java/com/paf/backend/login/LoginService.java src/backend/src/test/java/com/paf/backend/login/LoginServiceTest.java
git commit -m "feat(backend): allow login for customers with no application"
```

---

## Task 4: Customer-keyed chat room and history

The room is `room-cust-{customerId}` and history is read by customer, so pre-application turns (no `applicationId`) are part of the same thread.

**Files:**

- Modify: `src/backend/src/main/java/com/paf/backend/chat/ChatService.java`
- Modify: `src/backend/src/main/java/com/paf/backend/domain/ChatMessageRepository.java`
- Test: `src/backend/src/test/java/com/paf/backend/chat/ChatServiceTest.java`

- [ ] **Step 1: Add a `findByCustomerId…` method** to `ChatMessageRepository.java` (next to the existing `findByApplicationIdOrderByMessageIdAsc`):

```java
    List<ChatMessage> findByCustomerIdOrderByMessageIdAsc(Long customerId);
```

(Ensure `java.util.List` and the `ChatMessage` type are imported/available — mirror the existing method's imports.)

- [ ] **Step 2: Update the failing assertion** in `ChatServiceTest.java`. In `handleTurnPersistsBothMessagesAndReturnsReply`, change the room expectation:

```java
        assertThat(captor.getAllValues().get(0).getRoomId()).isEqualTo("room-cust-1");
```

If there is a `history` test that stubs `findByApplicationIdOrderByMessageIdAsc`, change it to stub `findByCustomerIdOrderByMessageIdAsc(1L)` instead. (Read the file; update any such stub. The `session()` helper has `customerId=1L`.)

- [ ] **Step 3: Run the test, confirm it fails**

Run: `./gradlew test --tests 'com.paf.backend.chat.ChatServiceTest'`
Expected: FAIL — room is still `room-app-7`.

- [ ] **Step 4: Update `ChatService`** — change `roomId` and `history`:

```java
    private String roomId(AuthSession session) {
        return "room-cust-" + session.getCustomerId();
    }
```

and in `history`:

```java
        return messages.findByCustomerIdOrderByMessageIdAsc(session.getCustomerId()).stream()
                .map(m -> new ChatMessageView(m.getSender(), m.getBody(), m.getCreatedAt()))
                .toList();
```

- [ ] **Step 5: Run the focused test, then the full suite**

Run: `./gradlew test --tests 'com.paf.backend.chat.ChatServiceTest'`
Expected: PASS.
Then run everything to catch any other test that referenced the old room/history (e.g. `ChatControllerTest`):
Run: `./gradlew test`
Expected: BUILD SUCCESSFUL. If a test fails because it asserted `room-app-…` or stubbed `findByApplicationId…`, update that assertion/stub the same way and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/backend/src/main/java/com/paf/backend/chat/ChatService.java src/backend/src/main/java/com/paf/backend/domain/ChatMessageRepository.java src/backend/src/test/java/com/paf/backend/chat/ChatServiceTest.java
git commit -m "feat(backend): key chat room and history by customer"
```

---

## Task 5: Deploy + live smoke

Confirm the no-application customer (`Liam NoApplication`, seeded in Plan 1) can log in and appears in the customer list.

**Files:** none (verification only).

- [ ] **Step 1: Rebuild + redeploy the backend**

Run: `python manage.py local up`
Wait for health: `curl -s http://localhost:8090/actuator/health` → `{"status":"UP"}`.

- [ ] **Step 2: `/v1/customers` includes Liam with `hasOpenApplication=false`**

Run:

```bash
curl -s http://localhost:8090/v1/customers | python -m json.tool | grep -A6 'Liam'
```

Expected: a Liam entry with `"applicationId": null` and `"hasOpenApplication": false`.

- [ ] **Step 3: No-application login succeeds**

Run (look up Liam's id from the customers list, then log in — replace `<ID>`):

```bash
curl -s -X POST http://localhost:8090/v1/login -H 'Content-Type: application/json' -d '{"customerId":<ID>}' | python -m json.tool
```

Expected: `{ "sessionToken": "sess_…", "customerId": <ID>, "applicationId": null, "roomId": "room-cust-<ID>" }` (no 404).

- [ ] **Step 4: Existing app-customer login still works (regression)**

Run:

```bash
curl -s -X POST http://localhost:8090/v1/login -H 'Content-Type: application/json' -d '{"customerId":11}' | python -m json.tool
```

Expected: a token, `applicationId: 10`, `roomId: "room-cust-11"`.

- [ ] **Step 5: Nothing to commit** (verification only). Plan 2 complete.

---

## Done criteria

- `./gradlew test` is green (existing suite + new tests).
- A no-application customer logs in (no 404), gets `applicationId: null` and `room-cust-{id}`; appears in `/v1/customers` with `hasOpenApplication: false`.
- Chat replies have leading `[[MARKER …]]` blocks stripped.
- Chat room/history is keyed by customer.
- Next: **Plan 3 — PAF flow** (Concierge agent, evidence split, recommendation hint).
