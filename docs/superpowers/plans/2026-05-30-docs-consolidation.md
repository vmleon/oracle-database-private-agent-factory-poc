# Documentation Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut duplication and a stale contradiction across the docs so a newcomer can learn the **use-case**, the **technology**, and **how to test it** without reading the same material three times — by giving each topic a single source of truth (SSOT) and making the other docs link to it.

**Architecture:** Documentation-only. No code changes. Each topic gets one owner; every other doc that touches it shrinks to a one-line pointer. `paf/flows/CHAT_WORKFLOW.md` is the canonical flow-build doc — `LOCAL.md`, `docs/DEPLOYMENT.md`, and `docs/DECISIONING-ENGINE-USE-CASE.md` stop re-describing the flow and link to it. The biggest single fix is syncing `docs/DESIGN.md` (still says **two-agent**) to the shipped **four-agent** design.

**Tech Stack:** Markdown. Mermaid for diagrams (repo preference). No build/test suite applies — verification is grep + read-through.

---

## Target doc set & ownership (the SSOT map)

| Doc                                   | Owns (single source of truth for…)                                                                    | Stops covering (links instead)                                                                         |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `README.md`                           | Story, **Current state**, quickstart links, **newcomer reading path**                                 | next-steps detail → `ENHANCEMENTS.md`                                                                  |
| `docs/GLOSSARY.md`                    | Banking/credit/compliance **terms**                                                                   | — (stays standalone; everyone links here)                                                              |
| `docs/DECISIONING-ENGINE-USE-CASE.md` | **Use-case**: why it exists, demo scenario, decision contract (tiers/reason-codes/HITL), test bench   | flow build → `CHAT_WORKFLOW.md`; architecture/personas/data-model → `DESIGN.md`; terms → `GLOSSARY.md` |
| `docs/DESIGN.md`                      | **Architecture**: personas, components, data flow, security boundary, locked decisions, source layout | flow build → `CHAT_WORKFLOW.md`; PAF platform mechanics → `PAF.md`                                     |
| `paf/flows/CHAT_WORKFLOW.md`          | **The flow build** (canonical)                                                                        | — (already the SSOT)                                                                                   |
| `LOCAL.md`                            | **Local runbook** (click-by-click)                                                                    | stack/architecture → `DESIGN.md`; flow build → `CHAT_WORKFLOW.md`; current state → `README.md`         |
| `docs/DEPLOYMENT.md`                  | **Deployment strategy**: options, `manage.py`, Liquibase, env, ops notes                              | current state → `README.md`; flow build → `CHAT_WORKFLOW.md`                                           |
| `docs/PAF.md`                         | **Generic PAF product reference** (study guide)                                                       | project specifics → the project docs (cross-link only)                                                 |
| `docs/TROUBLESHOOT.md`                | Validated **workarounds**                                                                             | —                                                                                                      |
| `ENHANCEMENTS.md`                     | **Future-feature** detail                                                                             | — (README links here)                                                                                  |
| `CLOUD.md`                            | Cloud runbook (empty)                                                                                 | becomes a one-line "not yet implemented → see DEPLOYMENT §4" stub                                      |

## Decisions baked in (override before execution if you disagree)

1. **`GLOSSARY.md` stays standalone**, not merged into the use-case doc — it's a small, linkable reference; burying it inside a 1000-line doc makes it less useful. The "consolidation" of GLOSSARY+USE-CASE is realized by making the use-case doc **link** to the glossary for every term and stop re-explaining them. _(If you'd rather physically merge them, say so and Task 5 changes.)_
2. **`DECISIONING-ENGINE-USE-CASE.md` is trimmed in place, not archived** — it remains the use-case SSOT, just shorter (its stale flow section and architecture/persona duplication are removed). _(If you'd rather archive it, Task 5 becomes a delete + a short use-case section folded into README.)_
3. **`docs/PAF.md` stays as the generic reference** — it's a legitimately separate "learn PAF the product" guide. We only remove places where the _project_ docs restate it (and vice-versa) and add cross-links. We do not rewrite PAF.md's content. Its §25 glossary (PAF-product terms) is distinct from `GLOSSARY.md` (banking terms) and stays.

**Verification convention (every task):** after editing, (a) re-read each changed section for coherence, (b) `grep` to confirm no stale term was reintroduced and that links resolve, (c) commit. There is no automated test for prose — these checks are the gate.

---

## Task 1: Sync `docs/DESIGN.md` to the four-agent flow (the critical contradiction)

`DESIGN.md` still describes a two-agent `CHAT_WORKFLOW`; the shipped/blueprinted design is four agents. This is the #1 newcomer-confuser.

**Files:**

- Modify: `docs/DESIGN.md` (§5 "PAF runtime mode" ~83–110; §11 "Locked decisions" ~278–296; any other `two-agent`/`EvaluationAgent`/`RecommendationAgent` mention)

- [ ] **Step 1: Find every stale reference**

Run: `grep -nE 'two-agent|EvaluationAgent|RecommendationAgent|SQL Query node' docs/DESIGN.md`
Expected: hits in §5 and §11 (and possibly the data-flow section).

- [ ] **Step 2: Rewrite the flow description to four agents**

Replace the two-agent description (wherever it appears) with the canonical shape, and add the rationale. Use this text (adapt to the surrounding sentence):

> `CHAT_WORKFLOW` is a **four-agent origination pipeline** — `Concierge` (conversational intake: `get_context` + `upsert_application`) → `Docs & Employer` → `Eligibility` → `Recommendation` (writes the HITL task). The split exists because PAF hard-caps an Agent node at `max_iterations = 5`; keeping each agent to **≤3 planned tool calls** leaves headroom for retries. Every agent re-reads state from the database via `banking-mcp.get_context` ("the database is the memory"). The canonical build blueprint — node graph, custom instructions, wiring, test prompts — is **[`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md)**; this section only states the architectural rationale.

- [ ] **Step 3: Fix the "SQL Query node / Select AI locally" wording**

Find the §11 sentence that says the local flow "uses a generic SQL Query node with LLM-generated SQL." Replace with:

> Locally, `CHAT_WORKFLOW` reads through **MCP tools that use bind variables** (`banking-mcp.get_context`), **not** a PAF SQL Query node — the SQL Query node ignores `:name` binds and fails open ([`issues/01`](../issues/01-sql-query-no-bind-variables.md)). Select AI profiles remain ADB-only (see [`DEPLOYMENT.md §7`](DEPLOYMENT.md)); the local flow calls vLLM directly via PAF's LLM Management, no Select AI in the loop.

- [ ] **Step 4: Verify**

Run: `grep -nE 'two-agent|EvaluationAgent|RecommendationAgent' docs/DESIGN.md`
Expected: no hits (or only an explicit "(formerly two-agent)" history note if you chose to keep one). Re-read §5 and §11.

- [ ] **Step 5: Commit**

```bash
git add docs/DESIGN.md
git commit -m "docs(design): sync CHAT_WORKFLOW to the four-agent design"
```

---

## Task 2: One "Current state" (README owns it; DEPLOYMENT links)

`README.md` "Current state" and `docs/DEPLOYMENT.md §9` "Current state" are near-duplicates.

**Files:**

- Modify: `docs/DEPLOYMENT.md` (§9 "Current state", ~281–312)
- Modify: `README.md` (only if §Current state is inaccurate after Task 1)

- [ ] **Step 1: Confirm README's Current state is the keeper and accurate**

Read `README.md` "Current state" (~117–132). It already says four-agent. Leave it as the SSOT. Fix any remaining staleness (it was updated in the origination work; spot-check the changelog range `001-012` and the four-agent line are present).

- [ ] **Step 2: Replace DEPLOYMENT §9 body with a pointer + the deployment-specific remainder**

In `docs/DEPLOYMENT.md`, delete the bullet list under "## 9. Current state" that restates schema changesets / tools / flow status, and replace the section body with:

> The live status of the stack (schema, tools, the flow) is tracked in one place — see **[`README.md` § Current state](../README.md#current-state)**. This section keeps only the _deployment-milestone_ view below.

Keep (or move here) only the deployment-flavoured "Next deliverables" ordering that is genuinely about deploy milestones; if it duplicates README's "What's next," cut it and link to README instead.

- [ ] **Step 3: Verify the two lists no longer duplicate**

Run: `grep -nE 'Liquibase changelog 001|create_hitl_task verified|four-agent' docs/DEPLOYMENT.md`
Expected: no current-state bullet list remains in DEPLOYMENT (only the pointer). Re-read §9.

- [ ] **Step 4: Commit**

```bash
git add docs/DEPLOYMENT.md README.md
git commit -m "docs(deployment): make README the single source for current state"
```

---

## Task 3: `DEPLOYMENT.md` defers flow build + fixes the Select-AI wording

**Files:**

- Modify: `docs/DEPLOYMENT.md` (§2 `paf bootstrap` row ~43; §7 Select-AI note ~268–272)

- [ ] **Step 1: Fix the `paf bootstrap` row's stale flow description**

The `manage.py paf bootstrap` row says the flows to import are "`CHAT_WORKFLOW` (two-agent: `EvaluationAgent` → `RecommendationAgent`)". Replace the parenthetical with: "`CHAT_WORKFLOW` (four-agent origination pipeline — see [`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md))".

- [ ] **Step 2: Fix the §7 "local uses SQL Query node" sentence**

Find the §7 sentence ending "…the local `CHAT_WORKFLOW` in PAF uses a generic **SQL Query node** with LLM-generated SQL against the same `REPORTING.chat_v_*` views." Replace with:

> …the local `CHAT_WORKFLOW` reads through `banking-mcp.get_context` (bind variables, fail-secure) rather than a SQL Query node; PAF's LLM Management calls vLLM directly — no Select AI in the loop. Same demo behaviour, different mechanism.

- [ ] **Step 3: Verify**

Run: `grep -nE 'two-agent|EvaluationAgent|SQL Query node' docs/DEPLOYMENT.md`
Expected: the only `SQL Query node` hits are ones explaining _why it's not used_; no `two-agent`/`EvaluationAgent`.

- [ ] **Step 4: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs(deployment): defer flow build to CHAT_WORKFLOW.md, fix Select-AI wording"
```

---

## Task 4: `LOCAL.md` defers flow build + stops re-explaining the stack

**Files:**

- Modify: `LOCAL.md` (§5 "Build CHAT_WORKFLOW" ~223–248; §1 intro "When you're done you have" ~13–28 only if it re-explains architecture)

- [ ] **Step 1: Rewrite §5 to a thin pointer**

The §5 bullets describe a stale flow ("SQL Query for application context", "two MCP server nodes — opa-mcp and hitl-mcp", "4-step recipe"). Replace the bullet list (the part that enumerates the node graph / SQL / custom-instructions) with:

> The full build blueprint — node graph, the four agents' custom instructions, the wiring table, test prompts, and operating constraints — is **[`paf/flows/CHAT_WORKFLOW.md`](paf/flows/CHAT_WORKFLOW.md)**. Build it there; this runbook only gets you to the point of opening Agent Builder with the tools (§4) and LLM (§3) registered.

Keep the §5 verification SQL and the "capture the JSON / no Export button" note (those are runbook-level), but make them reference `CHAT_WORKFLOW.md §Export` rather than re-explaining.

- [ ] **Step 2: Keep §1's container inventory, drop architecture re-explanation**

§1's "When you're done you have" bullets are a useful _deliverable checklist_ — keep them. Only remove any sentence that explains _why_ the architecture is shaped this way (that's `DESIGN.md`). Add one line at the top of §1: "Architecture and the four-agent rationale live in [`docs/DESIGN.md`](docs/DESIGN.md); this file is the click-by-click runbook." (The file already says something like this in its first paragraph — make it explicit.)

- [ ] **Step 3: Verify**

Run: `grep -nE 'SQL Query for application context|two MCP server nodes|4-step recipe|two-agent' LOCAL.md`
Expected: no hits. Re-read §5.

- [ ] **Step 4: Commit**

```bash
git add LOCAL.md
git commit -m "docs(local): defer the flow build to CHAT_WORKFLOW.md, drop stale flow description"
```

---

## Task 5: Consolidate `DECISIONING-ENGINE-USE-CASE.md` (+ glossary linking)

Trim the use-case doc to its unique job and make it link out for everything else. This is the GLOSSARY+USE-CASE consolidation (Decision 1: GLOSSARY stays standalone; the use-case doc links to it).

**Files:**

- Modify: `docs/DECISIONING-ENGINE-USE-CASE.md` (the `## CHAT_WORKFLOW …` section ~546–704; the component-map/personas table ~97–114; the data-model section ~118–410)
- Modify: `docs/GLOSSARY.md` (only if a term used in the use-case doc is missing — add it so the link is complete)

- [ ] **Step 1: Replace the stale `## CHAT_WORKFLOW` section with a pointer**

The `## CHAT_WORKFLOW — customer-facing Private Agent Factory flow` section (~546) re-describes the flow (now stale — pre-origination). Delete its body and replace with:

> ### `CHAT_WORKFLOW` (the customer-facing flow)
>
> The decision contract below (three tiers + reason codes + mandatory HITL) is realised by the `CHAT_WORKFLOW` Agent Builder flow. Its build — agents, custom instructions, gates, wiring, test prompts — is canonical in **[`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md)**. This document owns the _contract_ (what the tiers mean, what the reviewer gets); the blueprint owns _how it's built_.

Keep the parts of this doc that are genuinely use-case contract (tier semantics, reason codes, HITL packet, what the reviewer sees) — those are the use-case SSOT.

- [ ] **Step 2: Collapse the architecture/persona/data-model duplication to pointers**

The component-map/personas table (~97–114) and the long data-model section duplicate `DESIGN.md`. Replace each with a 2–3 line summary + a pointer: "Personas and the component breakdown are in [`DESIGN.md §3`](DESIGN.md#3-audience-and-personas); the schema/data model is [`DESIGN.md §6`](DESIGN.md#6-component-breakdown). This section keeps only the use-case-relevant entities." Keep only the entities a use-case reader needs to follow the scenario (customer, application, decision, hitl_task) — as a short list, not the full DDL-level table.

- [ ] **Step 3: Ensure every banking term links to the glossary**

The doc already opens with a glossary link. Confirm it, and where a term is first used in body prose (DTI, PTI, KYC, AML, fair lending, reason code, HITL), it relies on `GLOSSARY.md` rather than re-defining inline. Remove any inline re-definition that duplicates a glossary entry. If the use-case doc uses a term not in `GLOSSARY.md`, add that term to `GLOSSARY.md` (so the glossary stays the complete SSOT).

- [ ] **Step 4: Verify**

Run: `grep -nE 'EvaluationAgent|RecommendationAgent|two-agent' docs/DECISIONING-ENGINE-USE-CASE.md`
Expected: no hits. Run `wc -l docs/DECISIONING-ENGINE-USE-CASE.md` — expect a meaningful reduction from 1054. Re-read the trimmed sections for flow.

- [ ] **Step 5: Commit**

```bash
git add docs/DECISIONING-ENGINE-USE-CASE.md docs/GLOSSARY.md
git commit -m "docs(use-case): trim to the use-case contract, link out for flow/architecture/terms"
```

---

## Task 6: De-duplicate `docs/PAF.md` against the project docs

Keep PAF.md as the generic reference; remove only the project-specific restatements and add cross-links (Decision 3).

**Files:**

- Modify: `docs/PAF.md` (§5 install ~136; §11 sample patterns ~608; §15 publishing/cookies ~964)

- [ ] **Step 1: Add a scope banner at the top of PAF.md**

Under the title, add: "> **Scope:** this is a _generic_ Private Agent Factory study guide (product mechanics, any use case). For how _this_ project uses PAF, see [`DESIGN.md §5`](DESIGN.md) (runtime mapping), [`LOCAL.md`](../LOCAL.md) (install/register), and [`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md) (the flow)."

- [ ] **Step 2: Trim project-specific drift, keep generic mechanics**

In §11 (sample patterns) and §15 (publishing/cookies), where the text describes _this project's_ `CHAT_WORKFLOW` specifically (rather than a generic pattern), cut it to a generic statement + a pointer to `CHAT_WORKFLOW.md`. Do **not** rewrite the generic PAF explanations — only the bits that restate the project flow. If a section is already purely generic, leave it.

- [ ] **Step 3: Cross-link the two glossaries**

At the top of `docs/PAF.md §25` (its glossary of PAF-product terms), add: "For banking/credit/compliance terms, see [`GLOSSARY.md`](GLOSSARY.md); this glossary covers PAF-product terms only." (Keeps them distinct, no overlap.)

- [ ] **Step 4: Verify**

Run: `grep -nE 'EvaluationAgent|RecommendationAgent|two-agent' docs/PAF.md`
Expected: no hits (or, if a §11 example genuinely needs a flow, it points at `CHAT_WORKFLOW.md`). Re-read the edited sections.

- [ ] **Step 5: Commit**

```bash
git add docs/PAF.md
git commit -m "docs(paf): scope as generic reference, cross-link project docs and the banking glossary"
```

---

## Task 7: Newcomer reading path + cross-link banners + CLOUD stub

Make the intended path explicit and add lightweight "see X for Y" banners so each doc declares what it owns.

**Files:**

- Modify: `README.md` (add a "Start here" reading path; link `ENHANCEMENTS.md` from "What's next")
- Modify: `docs/DESIGN.md`, `LOCAL.md`, `paf/flows/CHAT_WORKFLOW.md` (one-line cross-reference banner at top)
- Modify: `CLOUD.md` (stub)

- [ ] **Step 1: Add a "Start here" reading path to README**

Add a short section near the top of `README.md`:

```markdown
## Start here

New to the project? Read in this order:

1. This README — the story + current state.
2. [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — if banking terms (DTI, KYC, AML…) are new.
3. [`docs/DECISIONING-ENGINE-USE-CASE.md`](docs/DECISIONING-ENGINE-USE-CASE.md) — what the system does and why.
4. [`docs/DESIGN.md`](docs/DESIGN.md) — the architecture and locked decisions.
5. [`paf/flows/CHAT_WORKFLOW.md`](paf/flows/CHAT_WORKFLOW.md) — the agent flow, in detail.
6. [`LOCAL.md`](LOCAL.md) — stand it up and test it.
   Reference as needed: [`docs/PAF.md`](docs/PAF.md) (PAF product), [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) (deploy strategy), [`docs/TROUBLESHOOT.md`](docs/TROUBLESHOOT.md).
```

- [ ] **Step 2: Link ENHANCEMENTS from README "What's next"**

In README's "What's next," ensure the future-feature items (Customer 360, XGBoost, product-rec, TOON) point to [`ENHANCEMENTS.md`](ENHANCEMENTS.md) rather than re-describing them.

- [ ] **Step 3: Add a one-line ownership banner to the top of each pillar doc**

- `docs/DESIGN.md`: "> Architecture SSOT. The flow build is in [`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md); the runbook is [`LOCAL.md`](../LOCAL.md)."
- `LOCAL.md`: (already has a runbook framing — ensure it points to `DESIGN.md` for architecture and `CHAT_WORKFLOW.md` for the flow).
- `paf/flows/CHAT_WORKFLOW.md`: "> Flow-build SSOT. Architectural rationale is in [`docs/DESIGN.md`](../../docs/DESIGN.md); deploy/runbook in [`LOCAL.md`](../../LOCAL.md)."

- [ ] **Step 4: Stub `CLOUD.md`**

`CLOUD.md` is empty. Make it a one-screen stub:

```markdown
# Cloud deployment (OCI)

Not yet implemented. The cloud topology, Terraform layout, and Ansible roles are
designed in [`docs/DEPLOYMENT.md §4`](docs/DEPLOYMENT.md). Infrastructure-as-code
lands under `deploy/tf/` and `deploy/ansible/` when this is built.
```

- [ ] **Step 5: Verify links resolve**

Run: `grep -rnoE '\]\(([^)]+\.md[^)]*)\)' README.md CLOUD.md docs/DESIGN.md LOCAL.md paf/flows/CHAT_WORKFLOW.md | head -40` and spot-check a handful of the targeted paths exist (`ls` them).
Expected: every linked `.md` path resolves.

- [ ] **Step 6: Commit**

```bash
git add README.md CLOUD.md docs/DESIGN.md LOCAL.md paf/flows/CHAT_WORKFLOW.md
git commit -m "docs: add newcomer reading path and ownership cross-links"
```

---

## Task 8: Final consistency sweep + newcomer read-through

**Files:** none (verification + any small fixes the sweep surfaces).

- [ ] **Step 1: Repo-wide stale-term sweep**

Run:

```bash
grep -rnE 'two-agent|EvaluationAgent|RecommendationAgent' README.md LOCAL.md CLOUD.md ENHANCEMENTS.md docs paf/flows/CHAT_WORKFLOW.md
```

Expected: hits ONLY in deliberate historical callbacks (e.g. `CHAT_WORKFLOW.md`'s "the earlier two-agent flow"). Fix any non-historical hit in place.

- [ ] **Step 2: Duplicate "Current state" check**

Run: `grep -rn '## .*[Cc]urrent state' README.md docs/DEPLOYMENT.md`
Expected: README owns the content; DEPLOYMENT only points to it.

- [ ] **Step 3: Newcomer read-through**

Follow the README "Start here" path end-to-end as if new: README → GLOSSARY → USE-CASE → DESIGN → CHAT_WORKFLOW → LOCAL. Confirm there's no contradiction (especially agent count and the SQL-Query/get_context story) and each doc declares what it owns. Fix anything that still reads as repetitive or contradictory.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "docs: final consolidation consistency sweep"
```

---

## Self-review (run after writing; fix inline)

- **Coverage vs the user's asks:** GLOSSARY+USE-CASE consolidation → Task 5 (+ Decision 1). LOCAL & DEPLOYMENT rely on CHAT_WORKFLOW.md for flow creation → Tasks 3 & 4. PAF.md repetition → Task 6. Newcomer can learn use-case/tech/test without repetition → Tasks 1–7 + the reading path in Task 7. ✓
- **No placeholders:** every task names exact files, the specific sections (with line ranges from the audit), and the replacement text or precise cut. ✓
- **Consistency:** "four-agent", `get_context`, "MCP tools not SQL Query node", and "README owns Current state" are stated identically across Tasks 1–6. ✓

## Done criteria

- `docs/DESIGN.md`, `README.md`, `LOCAL.md`, `DEPLOYMENT.md`, `DECISIONING-ENGINE-USE-CASE.md`, `PAF.md` all agree: **four-agent flow, MCP-tools-not-SQL-Query**, and each links to `paf/flows/CHAT_WORKFLOW.md` for the build instead of re-describing it.
- Exactly one "Current state" (README); exactly two glossaries with distinct scopes, cross-linked.
- A "Start here" path exists; `CLOUD.md` is a clear stub.
- Repo-wide grep shows no stale `two-agent`/`EvaluationAgent` outside deliberate history notes.
