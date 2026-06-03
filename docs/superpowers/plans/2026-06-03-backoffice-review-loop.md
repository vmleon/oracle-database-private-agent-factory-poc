# Backoffice Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a reviewer open the HITL queue, inspect an application's agent recommendation packet, and record a final APPROVE/REJECT decision with a note — written atomically to `APP.hitl_task` (CLOSED) and the `APP.decision` blockchain table.

**Architecture:** New `com.bank.appbackend.hitl` Spring package (Controller → Service → Repository) exposing 3 `/v1/hitl` endpoints, mirroring the existing `chat/` and `login/` slices. The close is one `@Transactional` method: a conditional UPDATE (the concurrency guard) plus an `INSERT … SELECT` that copies the agent packet DB-side into the blockchain row. Frontend adds a `/backoffice` path-split (no router dependency) inside the existing Vite app, reusing `api.ts`, `button`, and Tailwind. No schema changes — changeset `003` already has every column.

**Tech Stack:** Spring Boot + Spring Data JPA (native queries + interface projections, Lombok), Oracle Free 26ai (JSON columns, `BLOCKCHAIN TABLE`), React + TypeScript + Vite + Tailwind, JUnit 5 + Mockito + AssertJ, Vitest, podman compose.

**Reference spec:** `docs/superpowers/specs/2026-06-03-backoffice-review-loop-design.md`

---

## File structure

Backend (`src/backend/src/main/java/com/bank/appbackend/`):

- `api/Dtos.java` — **modify**: add `HitlQueueItem`, `HitlTaskView`, `DecisionRequest`, `DecisionResponse` records.
- `domain/HitlTask.java` — **create**: minimal JPA entity (handle for the repository).
- `domain/HitlQueueRow.java` — **create**: projection for the queue list.
- `domain/HitlTaskRow.java` — **create**: projection for the detail (JSON columns serialized to text).
- `domain/HitlRepository.java` — **create**: queue, detail, conditional close, blockchain insert.
- `hitl/HitlService.java` — **create**: list/detail/decide with 400/404/409 + reviewer default.
- `hitl/HitlController.java` — **create**: 3 REST endpoints.
- `src/test/java/com/bank/appbackend/hitl/HitlServiceTest.java` — **create**: unit tests (mocked repo).

Frontend (`src/frontend/src/`):

- `api.ts` — **modify**: add types + `listHitlTasks` / `getHitlTask` / `decideHitlTask`.
- `lib/route.ts` — **create**: `isBackofficePath()` helper.
- `lib/route.test.ts` — **create**: Vitest test for the helper.
- `components/backoffice/Backoffice.tsx` — **create**: queue/detail switcher.
- `components/backoffice/Queue.tsx` — **create**: OPEN-task list.
- `components/backoffice/TaskDetail.tsx` — **create**: packet view + decide form.
- `App.tsx` — **modify**: early-return `<Backoffice/>` on `/backoffice`, move customer flow into `CustomerApp`.

---

## Task 1: Backend DTO records

**Files:**

- Modify: `src/backend/src/main/java/com/bank/appbackend/api/Dtos.java`

- [ ] **Step 1: Add the four records**

Insert these records inside the `Dtos` class (before the closing brace), after `ChatMessageView`:

```java
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
```

- [ ] **Step 2: Compile**

Run: `cd src/backend && ./gradlew compileJava`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/api/Dtos.java
git commit -m "feat(hitl): add backoffice DTO records"
```

---

## Task 2: HitlTask entity + projections

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/domain/HitlTask.java`
- Create: `src/backend/src/main/java/com/bank/appbackend/domain/HitlQueueRow.java`
- Create: `src/backend/src/main/java/com/bank/appbackend/domain/HitlTaskRow.java`

- [ ] **Step 1: Create the entity** (`HitlTask.java`)

Only the scalar columns the repository type needs are mapped; JSON columns are read via the projection in Task 3, not the entity.

```java
package com.bank.appbackend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "HITL_TASK")
@Getter
@NoArgsConstructor
public class HitlTask {

    @Id
    @Column(name = "TASK_ID")
    private Long taskId;

    @Column(name = "APPLICATION_ID")
    private Long applicationId;

    @Column(name = "STATE")
    private String state;

    @Column(name = "AGENT_RECOMMENDATION")
    private String agentRecommendation;

    @Column(name = "AGENT_RUN_ID")
    private String agentRunId;
}
```

- [ ] **Step 2: Create the queue projection** (`HitlQueueRow.java`)

```java
package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for the OPEN-task queue list. */
public interface HitlQueueRow {
    Long getTaskId();
    Long getApplicationId();
    String getCustomerName();
    String getAgentRecommendation();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    Instant getCreatedAt();
}
```

- [ ] **Step 3: Create the detail projection** (`HitlTaskRow.java`)

The two JSON columns are serialized to text in the query (Task 3), so they are plain `String` here.

```java
package com.bank.appbackend.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Spring Data projection for a single HITL task detail (JSON columns as text). */
public interface HitlTaskRow {
    Long getTaskId();
    Long getApplicationId();
    String getCustomerName();
    BigDecimal getAmountRequested();
    Integer getTermMonths();
    String getPurpose();
    String getState();
    String getAgentRecommendation();
    String getAgentReasoning();
    String getAgentExploreHints();
    String getAgentEvidence();
    String getAgentRunId();
    String getHumanOutcome();
    Instant getCreatedAt();
    Instant getClosedAt();
}
```

- [ ] **Step 4: Compile**

Run: `cd src/backend && ./gradlew compileJava`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/domain/HitlTask.java \
        src/backend/src/main/java/com/bank/appbackend/domain/HitlQueueRow.java \
        src/backend/src/main/java/com/bank/appbackend/domain/HitlTaskRow.java
git commit -m "feat(hitl): add HitlTask entity and queue/detail projections"
```

---

## Task 3: HitlRepository

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/domain/HitlRepository.java`

- [ ] **Step 1: Create the repository**

`closeTask` is the concurrency guard: `state <> 'CLOSED'` means a second close updates 0 rows. `insertDecision` copies the agent packet (including the JSON columns) DB-side, so Java never deserializes JSON; the human fields come from bind params. `computed_dti`/`computed_pti`/`pricing_offer`/`reason_codes` are intentionally left to their NULL default for the PoC (the evidence-packet shape is not standardized — deferred per the spec).

```java
package com.bank.appbackend.domain;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface HitlRepository extends JpaRepository<HitlTask, Long> {

    @Query(value = """
            SELECT t.task_id            AS taskId,
                   t.application_id      AS applicationId,
                   c.full_name           AS customerName,
                   t.agent_recommendation AS agentRecommendation,
                   la.amount_requested   AS amountRequested,
                   la.term_months        AS termMonths,
                   t.created_at          AS createdAt
              FROM APP.hitl_task t
              JOIN APP.loan_application la ON la.application_id = t.application_id
              JOIN APP.customer c          ON c.customer_id = la.customer_id
             WHERE t.state = :state
             ORDER BY t.created_at
            """, nativeQuery = true)
    List<HitlQueueRow> findQueue(@Param("state") String state);

    @Query(value = """
            SELECT t.task_id            AS taskId,
                   t.application_id      AS applicationId,
                   c.full_name           AS customerName,
                   la.amount_requested   AS amountRequested,
                   la.term_months        AS termMonths,
                   la.purpose            AS purpose,
                   t.state               AS state,
                   t.agent_recommendation AS agentRecommendation,
                   t.agent_reasoning     AS agentReasoning,
                   JSON_SERIALIZE(t.agent_explore_hints RETURNING VARCHAR2) AS agentExploreHints,
                   JSON_SERIALIZE(t.agent_evidence RETURNING VARCHAR2)      AS agentEvidence,
                   t.agent_run_id        AS agentRunId,
                   t.human_outcome       AS humanOutcome,
                   t.created_at          AS createdAt,
                   t.closed_at           AS closedAt
              FROM APP.hitl_task t
              JOIN APP.loan_application la ON la.application_id = t.application_id
              JOIN APP.customer c          ON c.customer_id = la.customer_id
             WHERE t.task_id = :taskId
            """, nativeQuery = true)
    Optional<HitlTaskRow> findDetail(@Param("taskId") Long taskId);

    @Modifying
    @Query(value = """
            UPDATE APP.hitl_task
               SET state        = 'CLOSED',
                   human_outcome = :outcome,
                   human_note    = :note,
                   human_user    = :reviewer,
                   closed_at     = SYSTIMESTAMP
             WHERE task_id = :taskId
               AND state <> 'CLOSED'
            """, nativeQuery = true)
    int closeTask(@Param("taskId") Long taskId, @Param("outcome") String outcome,
                  @Param("note") String note, @Param("reviewer") String reviewer);

    @Modifying
    @Query(value = """
            INSERT INTO APP.decision
                (application_id, human_outcome, human_user, human_note,
                 agent_recommendation, agent_reasoning, agent_explore_hints,
                 agent_evidence, agent_run_id)
            SELECT application_id, :outcome, :reviewer, :note,
                   agent_recommendation, agent_reasoning, agent_explore_hints,
                   agent_evidence, agent_run_id
              FROM APP.hitl_task
             WHERE task_id = :taskId
            """, nativeQuery = true)
    void insertDecision(@Param("taskId") Long taskId, @Param("outcome") String outcome,
                        @Param("note") String note, @Param("reviewer") String reviewer);
}
```

- [ ] **Step 2: Compile**

Run: `cd src/backend && ./gradlew compileJava`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/domain/HitlRepository.java
git commit -m "feat(hitl): add HitlRepository (queue, detail, close, blockchain insert)"
```

---

## Task 4: HitlService (TDD)

**Files:**

- Test: `src/backend/src/test/java/com/bank/appbackend/hitl/HitlServiceTest.java`
- Create: `src/backend/src/main/java/com/bank/appbackend/hitl/HitlService.java`

- [ ] **Step 1: Write the failing test** (`HitlServiceTest.java`)

```java
package com.bank.appbackend.hitl;

import com.bank.appbackend.api.Dtos.DecisionRequest;
import com.bank.appbackend.api.Dtos.DecisionResponse;
import com.bank.appbackend.domain.HitlRepository;
import com.bank.appbackend.domain.HitlTaskRow;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class HitlServiceTest {

    private final HitlRepository repo = mock(HitlRepository.class);
    private final HitlService service = new HitlService(repo);

    @Test
    void decideClosesTaskAndWritesDecisionRow() {
        when(repo.findDetail(5L)).thenReturn(Optional.of(row(5L, "OPEN")));
        when(repo.closeTask(5L, "REJECT", "DTI over cap", "Backoffice Reviewer")).thenReturn(1);

        DecisionResponse resp = service.decide(5L, new DecisionRequest("REJECT", "DTI over cap", null));

        assertThat(resp.state()).isEqualTo("CLOSED");
        assertThat(resp.humanOutcome()).isEqualTo("REJECT");
        assertThat(resp.humanUser()).isEqualTo("Backoffice Reviewer");
        verify(repo).insertDecision(5L, "REJECT", "DTI over cap", "Backoffice Reviewer");
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
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.hitl.HitlServiceTest'`
Expected: FAIL — compilation error, `HitlService` does not exist.

- [ ] **Step 3: Write the implementation** (`HitlService.java`)

```java
package com.bank.appbackend.hitl;

import com.bank.appbackend.api.Dtos.DecisionRequest;
import com.bank.appbackend.api.Dtos.DecisionResponse;
import com.bank.appbackend.api.Dtos.HitlQueueItem;
import com.bank.appbackend.api.Dtos.HitlTaskView;
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

    public HitlService(HitlRepository repo) {
        this.repo = repo;
    }

    /** OPEN tasks for the review queue. */
    public List<HitlQueueItem> listOpen() {
        return repo.findQueue("OPEN").stream()
                .map(r -> new HitlQueueItem(r.getTaskId(), r.getApplicationId(), r.getCustomerName(),
                        r.getAgentRecommendation(), r.getAmountRequested(), r.getTermMonths(),
                        r.getCreatedAt()))
                .toList();
    }

    /** Full recommendation packet for one task. 404 if unknown. */
    public HitlTaskView getDetail(Long taskId) {
        return toView(repo.findDetail(taskId).orElseThrow(this::notFound));
    }

    /**
     * Close a task with the human decision: update hitl_task and write the blockchain
     * decision row, atomically. 400 on a bad outcome, 404 if the task is unknown,
     * 409 if it was already closed.
     */
    @Transactional
    public DecisionResponse decide(Long taskId, DecisionRequest req) {
        String outcome = req.outcome();
        if (!"APPROVE".equals(outcome) && !"REJECT".equals(outcome)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "outcome must be APPROVE or REJECT");
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

    private HitlTaskView toView(HitlTaskRow r) {
        return new HitlTaskView(r.getTaskId(), r.getApplicationId(), r.getCustomerName(),
                r.getAmountRequested(), r.getTermMonths(), r.getPurpose(), r.getState(),
                r.getAgentRecommendation(), r.getAgentReasoning(), r.getAgentExploreHints(),
                r.getAgentEvidence(), r.getAgentRunId(), r.getHumanOutcome(),
                r.getCreatedAt(), r.getClosedAt());
    }

    private ResponseStatusException notFound() {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found");
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd src/backend && ./gradlew test --tests 'com.bank.appbackend.hitl.HitlServiceTest'`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/hitl/HitlService.java \
        src/backend/src/test/java/com/bank/appbackend/hitl/HitlServiceTest.java
git commit -m "feat(hitl): add HitlService close transaction with 404/409 guards"
```

---

## Task 5: HitlController

**Files:**

- Create: `src/backend/src/main/java/com/bank/appbackend/hitl/HitlController.java`

- [ ] **Step 1: Create the controller**

The `state` query param is accepted for forward-compatibility but the PoC only serves OPEN.

```java
package com.bank.appbackend.hitl;

import com.bank.appbackend.api.Dtos.DecisionRequest;
import com.bank.appbackend.api.Dtos.DecisionResponse;
import com.bank.appbackend.api.Dtos.HitlQueueItem;
import com.bank.appbackend.api.Dtos.HitlTaskView;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/v1/hitl")
public class HitlController {

    private final HitlService service;

    public HitlController(HitlService service) {
        this.service = service;
    }

    @GetMapping("/tasks")
    public List<HitlQueueItem> tasks(@RequestParam(defaultValue = "OPEN") String state) {
        return service.listOpen();
    }

    @GetMapping("/tasks/{taskId}")
    public HitlTaskView task(@PathVariable Long taskId) {
        return service.getDetail(taskId);
    }

    @PostMapping("/tasks/{taskId}/decision")
    public DecisionResponse decide(@PathVariable Long taskId, @RequestBody DecisionRequest request) {
        return service.decide(taskId, request);
    }
}
```

- [ ] **Step 2: Run the full backend test suite + compile**

Run: `cd src/backend && ./gradlew test`
Expected: `BUILD SUCCESSFUL`, all tests pass (existing + the 5 new ones).

- [ ] **Step 3: Commit**

```bash
git add src/backend/src/main/java/com/bank/appbackend/hitl/HitlController.java
git commit -m "feat(hitl): add HitlController (/v1/hitl tasks + decision)"
```

---

## Task 6: Frontend API client

**Files:**

- Modify: `src/frontend/src/api.ts`

- [ ] **Step 1: Add types and functions**

Append to the end of `src/frontend/src/api.ts`:

```ts
export interface HitlQueueItem {
  taskId: number;
  applicationId: number;
  customerName: string;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  amountRequested: number | null;
  termMonths: number | null;
  createdAt: string | null;
}

export interface HitlTaskView {
  taskId: number;
  applicationId: number;
  customerName: string;
  amountRequested: number | null;
  termMonths: number | null;
  purpose: string | null;
  state: string;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  agentReasoning: string | null;
  agentExploreHints: string | null; // raw JSON text
  agentEvidence: string | null; // raw JSON text
  agentRunId: string;
  humanOutcome: string | null;
  createdAt: string | null;
  closedAt: string | null;
}

export interface DecisionResponse {
  taskId: number;
  state: string;
  humanOutcome: string;
  humanUser: string;
}

export function listHitlTasks(): Promise<HitlQueueItem[]> {
  return fetch("/v1/hitl/tasks?state=OPEN").then((r) =>
    json<HitlQueueItem[]>(r),
  );
}

export function getHitlTask(taskId: number): Promise<HitlTaskView> {
  return fetch(`/v1/hitl/tasks/${taskId}`).then((r) => json<HitlTaskView>(r));
}

export function decideHitlTask(
  taskId: number,
  body: { outcome: "APPROVE" | "REJECT"; note: string; reviewer: string },
): Promise<DecisionResponse> {
  return fetch(`/v1/hitl/tasks/${taskId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<DecisionResponse>(r));
}
```

- [ ] **Step 2: Typecheck**

Run: `cd src/frontend && npx tsc -b`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/frontend/src/api.ts
git commit -m "feat(ui): add backoffice HITL api client functions"
```

---

## Task 7: Route helper (TDD)

**Files:**

- Test: `src/frontend/src/lib/route.test.ts`
- Create: `src/frontend/src/lib/route.ts`

- [ ] **Step 1: Write the failing test** (`route.test.ts`)

```ts
import { describe, it, expect } from "vitest";
import { isBackofficePath } from "./route";

describe("isBackofficePath", () => {
  it("matches the backoffice root and subpaths", () => {
    expect(isBackofficePath("/backoffice")).toBe(true);
    expect(isBackofficePath("/backoffice/")).toBe(true);
    expect(isBackofficePath("/backoffice/tasks/5")).toBe(true);
  });

  it("does not match the customer app", () => {
    expect(isBackofficePath("/")).toBe(false);
    expect(isBackofficePath("/chat")).toBe(false);
    expect(isBackofficePath("/backofficex")).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/frontend && npx vitest run src/lib/route.test.ts`
Expected: FAIL — cannot resolve `./route`.

- [ ] **Step 3: Write the implementation** (`route.ts`)

```ts
/** True when the current path is the backoffice reviewer app (vs. the customer app). */
export function isBackofficePath(pathname: string): boolean {
  return pathname === "/backoffice" || pathname.startsWith("/backoffice/");
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd src/frontend && npx vitest run src/lib/route.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src/lib/route.ts src/frontend/src/lib/route.test.ts
git commit -m "feat(ui): add isBackofficePath route helper"
```

---

## Task 8: Backoffice components

**Files:**

- Create: `src/frontend/src/components/backoffice/Queue.tsx`
- Create: `src/frontend/src/components/backoffice/TaskDetail.tsx`
- Create: `src/frontend/src/components/backoffice/Backoffice.tsx`

- [ ] **Step 1: Create `Queue.tsx`**

```tsx
import { useEffect, useState } from "react";
import { listHitlTasks, type HitlQueueItem } from "@/api";

export function Queue({ onOpen }: { onOpen: (taskId: number) => void }) {
  const [tasks, setTasks] = useState<HitlQueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listHitlTasks()
      .then(setTasks)
      .catch(() =>
        setError("Could not load the queue. Is the backend running?"),
      );
  }, []);

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="mb-1 text-2xl font-semibold">Review queue</h1>
      <p className="mb-6 text-sm text-slate-500">
        Open HITL tasks awaiting a decision.
      </p>
      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      {tasks.length === 0 && !error && (
        <p className="text-sm text-slate-500">No open tasks.</p>
      )}
      <ul className="space-y-2">
        {tasks.map((t) => (
          <li key={t.taskId}>
            <button
              onClick={() => onOpen(t.taskId)}
              className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-left hover:border-slate-400"
            >
              <span>
                <span className="font-medium">{t.customerName}</span>
                <span className="ml-2 text-xs text-slate-500">
                  {t.agentRecommendation} · {t.amountRequested ?? "—"} ·{" "}
                  {t.termMonths ?? "—"}m
                </span>
              </span>
              <span className="text-sm text-slate-400">→</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Create `TaskDetail.tsx`**

```tsx
import { useEffect, useState } from "react";
import { decideHitlTask, getHitlTask, type HitlTaskView } from "@/api";
import { Button } from "@/components/ui/button";

export function TaskDetail({
  taskId,
  onBack,
}: {
  taskId: number;
  onBack: () => void;
}) {
  const [task, setTask] = useState<HitlTaskView | null>(null);
  const [outcome, setOutcome] = useState<"APPROVE" | "REJECT">("APPROVE");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("Backoffice Reviewer");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getHitlTask(taskId)
      .then(setTask)
      .catch(() => setError("Could not load the task."));
  }, [taskId]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await decideHitlTask(taskId, { outcome, note, reviewer });
      onBack();
    } catch (e) {
      setError(
        e instanceof Error && e.message.includes("409")
          ? "This task was already decided."
          : "Could not submit the decision.",
      );
      setBusy(false);
    }
  };

  if (!task) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        {error ? (
          <p className="text-sm text-red-700">{error}</p>
        ) : (
          <p className="text-sm text-slate-500">Loading…</p>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-8">
      <button
        onClick={onBack}
        className="mb-4 text-sm text-slate-500 hover:underline"
      >
        ← Back to queue
      </button>
      <h1 className="text-2xl font-semibold">{task.customerName}</h1>
      <p className="mb-4 text-sm text-slate-500">
        Application {task.applicationId} · {task.purpose ?? "—"} ·{" "}
        {task.amountRequested ?? "—"} over {task.termMonths ?? "—"} months
      </p>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <p className="text-sm">
          <span className="font-medium">Agent recommendation:</span>{" "}
          {task.agentRecommendation}
        </p>
        <p className="mt-2 text-sm text-slate-700">{task.agentReasoning}</p>
        {task.agentExploreHints && (
          <pre className="mt-3 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
            {task.agentExploreHints}
          </pre>
        )}
        {task.agentEvidence && (
          <pre className="mt-3 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
            {task.agentEvidence}
          </pre>
        )}
      </div>

      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="space-y-3">
        <div className="flex gap-2">
          <Button
            variant={outcome === "APPROVE" ? "primary" : "ghost"}
            onClick={() => setOutcome("APPROVE")}
          >
            Approve
          </Button>
          <Button
            variant={outcome === "REJECT" ? "primary" : "ghost"}
            onClick={() => setOutcome("REJECT")}
          >
            Reject
          </Button>
        </div>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Reviewer note"
          rows={3}
          className="w-full rounded-md border border-slate-200 p-2 text-sm"
        />
        <input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          className="w-full rounded-md border border-slate-200 p-2 text-sm"
        />
        <Button onClick={submit} disabled={busy}>
          {busy ? "Submitting…" : "Submit decision"}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `Backoffice.tsx`**

```tsx
import { useState } from "react";
import { Queue } from "./Queue";
import { TaskDetail } from "./TaskDetail";

export function Backoffice() {
  const [selected, setSelected] = useState<number | null>(null);

  return selected === null ? (
    <Queue onOpen={setSelected} />
  ) : (
    <TaskDetail taskId={selected} onBack={() => setSelected(null)} />
  );
}
```

- [ ] **Step 4: Typecheck**

Run: `cd src/frontend && npx tsc -b`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src/components/backoffice/
git commit -m "feat(ui): add backoffice queue and task-detail components"
```

---

## Task 9: Wire the path split into App.tsx

**Files:**

- Modify: `src/frontend/src/App.tsx`

- [ ] **Step 1: Replace `App.tsx`**

Move the existing customer flow into `CustomerApp` and early-return the backoffice on `/backoffice`. `window.location.pathname` is read once and never changes during the app's life (no client-side routing), so the hook order stays stable.

```tsx
import { useState } from "react";
import { Login } from "@/components/Login";
import { Chat } from "@/components/Chat";
import { Backoffice } from "@/components/backoffice/Backoffice";
import { isBackofficePath } from "@/lib/route";
import type { Session } from "@/useChat";

interface StoredSession extends Session {
  name: string;
}

function load(): StoredSession | null {
  const raw = sessionStorage.getItem("session");
  return raw ? (JSON.parse(raw) as StoredSession) : null;
}

function CustomerApp() {
  const [session, setSession] = useState<StoredSession | null>(load);

  if (!session) {
    return (
      <Login
        onLoggedIn={(r) => {
          // The customer name isn't in the login response; fetch-free: we only have ids here,
          // so store a friendly fallback. (Name is shown on the picker; header uses room id label.)
          const s: StoredSession = {
            token: r.sessionToken,
            customerId: r.customerId,
            roomId: r.roomId,
            name: `Customer ${r.customerId}`,
          };
          sessionStorage.setItem("session", JSON.stringify(s));
          setSession(s);
        }}
      />
    );
  }

  return (
    <Chat
      session={session}
      name={session.name}
      onLoggedOut={() => setSession(null)}
    />
  );
}

export default function App() {
  if (isBackofficePath(window.location.pathname)) {
    return <Backoffice />;
  }
  return <CustomerApp />;
}
```

- [ ] **Step 2: Typecheck + build**

Run: `cd src/frontend && npm run build`
Expected: `tsc -b` clean, `vite build` succeeds.

- [ ] **Step 3: Run the frontend test suite**

Run: `cd src/frontend && npm test`
Expected: all tests pass (existing `chatState` + new `route`).

- [ ] **Step 4: Commit**

```bash
git add src/frontend/src/App.tsx
git commit -m "feat(ui): route /backoffice to the reviewer app"
```

---

## Task 10: Deploy, smoke-test the blockchain write, and verify end-to-end

This task uses the running podman stack. The compose file is `deploy/podman/compose.local.yml`; the services are `application-backend` and `application-ui`.

- [ ] **Step 1: Confirm the blockchain table exists and accepts an INSERT**

The spec flagged this risk. Verify `APP.decision` is a real blockchain table on the running DB:

Run:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
SELECT table_name FROM dba_blockchain_tables WHERE owner='APP' AND table_name='DECISION';
SQL
```

Expected: one row, `DECISION`. If empty, stop — changeset `003` did not apply the blockchain table on this DB and the close path will fail; re-run provisioning before continuing.

- [ ] **Step 2: Rebuild the backend image (no cache) and the UI image**

`--no-cache` on the backend avoids the known stale-jar trap (cached layers serving an old jar).

Run:

```bash
podman compose -f deploy/podman/compose.local.yml build --no-cache application-backend
podman compose -f deploy/podman/compose.local.yml build application-ui
podman compose -f deploy/podman/compose.local.yml up -d application-backend application-ui
```

Expected: both containers recreated, no errors.

- [ ] **Step 3: Restart the UI so nginx re-resolves the backend IP**

The UI nginx caches the backend IP at startup; a recreated backend gets a new IP. Restart the UI last (the known 502 fix).

Run: `podman restart application-ui`
Expected: container restarts.

- [ ] **Step 4: Confirm the backend is healthy and the new endpoint is live**

Run:

```bash
curl -s -o /dev/null -w "health %{http_code}\n" http://localhost:8090/actuator/health
curl -s -o /dev/null -w "queue %{http_code}\n" http://localhost:5173/v1/hitl/tasks
```

Expected: `health 200` and `queue 200` (200 even if the queue is empty — an empty JSON array).

- [ ] **Step 5: Create a HITL task to review (manual chat run)**

Drive case 3 (David HighDti → DECLINE) through the customer chat at `http://localhost:5173/` so the agent ends the turn with a `create_hitl_task` call. Confirm a row landed:

Run:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
SELECT task_id, application_id, agent_recommendation, state
  FROM APP.hitl_task ORDER BY task_id DESC FETCH FIRST 3 ROWS ONLY;
SQL
```

Expected: at least one `OPEN` task with `agent_recommendation = DECLINE`.

- [ ] **Step 6: Review and decide in the backoffice**

Open `http://localhost:5173/backoffice`, confirm the task appears in the queue, open it, confirm the agent reasoning/evidence render, choose **Reject**, type a note, and submit. The UI returns to the queue and the task drops off the OPEN list.

- [ ] **Step 7: Verify the close wrote both rows**

Run:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
SELECT task_id, state, human_outcome, human_user FROM APP.hitl_task
 WHERE state='CLOSED' ORDER BY task_id DESC FETCH FIRST 3 ROWS ONLY;
SELECT decision_id, application_id, human_outcome, human_user, agent_recommendation
  FROM APP.decision ORDER BY decision_id DESC FETCH FIRST 3 ROWS ONLY;
SQL
```

Expected: the task is `CLOSED` with your outcome/name, **and** a matching `APP.decision` blockchain row exists carrying the same `human_outcome`/`human_user` plus the copied `agent_recommendation`.

- [ ] **Step 8: Verify idempotency (already-closed guard)**

Re-submit a decision on the now-closed task directly:

Run:

```bash
curl -s -o /dev/null -w "reclose %{http_code}\n" -X POST \
  http://localhost:5173/v1/hitl/tasks/<TASK_ID>/decision \
  -H 'Content-Type: application/json' \
  -d '{"outcome":"APPROVE","note":"retry","reviewer":"Tester"}'
```

(substitute the closed `<TASK_ID>`)
Expected: `reclose 409`, and the `APP.decision` count for that application is unchanged (no second row).

- [ ] **Step 9: Final commit (if any tracked changes remain)**

No code changes in this task; nothing to commit unless a fix was needed during verification.

---

## Notes for the implementer

- **No Liquibase changes.** Every column already exists (changeset `003`). If a query fails on a missing column, re-read `database/liquibase/oracle/003-decisioning-audit-hitl.yaml` rather than altering the schema.
- **Reviewer identity is attribution, not auth** (PoC). The `/backoffice` route is unauthenticated by design; production is assumed to add a separate authenticated portal.
- **JSON columns** (`agent_explore_hints`, `agent_evidence`) are read as text via `JSON_SERIALIZE(... RETURNING VARCHAR2)` and copied DB-side in the decision INSERT — never deserialized in Java.
- **`computed_dti`/`computed_pti`/`pricing_offer`/`reason_codes`** are left NULL in the decision row for this iteration (deferred; the evidence-packet shape is not standardized).
