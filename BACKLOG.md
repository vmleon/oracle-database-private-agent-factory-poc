# Backlog

The prioritised backlog for the PoC: near-term backoffice work, broader-plan
features, and platform hardening.

**Maintenance convention.** When an item is done and implemented successfully, **remove it from this backlog and delete the related `issues/` file(s)** — keep the repo describing the final state, not the history. If an issue is only **partially** improved (a workaround, not a real fix), **refresh that issue** so it stays accurate instead of deleting it.

## 0. PAF 26.4 — residual follow-ups

**Shipped (26.4 fully adopted this session):** kit on 26.4 (`PAF_TARBALL`); **TCPS** DB connection + client wallet; the **`mcp-proxy` HTTPS gateway** for the MCP servers + PAF cert-trust (`SSL_CERT_FILE` + certifi injection); **`AAI_RO_AGENT_FACTORY`** pre-creation; **`paf allow-internal-mcp`**; the **deterministic `get_context`** entry (read path — closes the streamed-token corruption; built, validated end-to-end, the former `issues/09` deleted; spec: `docs/superpowers/specs/2026-06-04-deterministic-get-context-design.md`); the rewritten 23-step `CHAT_WORKFLOW` blueprint; and the flow **`.paf` export/import** round-trip (`LOCAL.md §5`, committed `paf/flows/chat_flow.paf`). What remains is optional or an alternative — **none are blocking**.

### 0.1 Script flow export/import in `manage.py` + doc cleanup (optional)

The UI export/import round-trip works and is documented (`LOCAL.md §5`). Nice-to-haves:

- Thin `manage.py paf flow export` / `flow import` wrappers around `/v1/agentBuilder/customFlows/exportAll` (password from a new `.env` `PAF_FLOW_EXPORT_PASS`) so a clean redeploy skips the manual UI steps.
- **Refresh `issues/05`** — 26.4's native export/import works now; keep only the residuals (deps re-link by hand on import, imports arrive unpublished, `.paf` is binary so not git-diffable).
- Update `paf/flows/CHAT_WORKFLOW.md §Export` — it still describes the old "no Export button / Network-tab scrape" path.

### 0.2 Deterministic `upsert` via marker — only if needed

The deterministic **read** path is shipped; `upsert_application` is left **agentic on purpose** (its token corruption is fail-closed + idempotent, and it wasn't the repro). Only if write-path corruption ever appears in testing: Concierge emits an `[[UPSERT …]]` marker → RegexExtractor + Type Convert build the JSON → a Deterministic MCP node calls `upsert_application` with the token wired. Cost: reopens the fail-open string-interpolation hazard (`issues/01`), a write-or-skip Condition (`issues/08`), and structured marker emission (`issues/07`). Parked.

### 0.3 PL/SQL Executor node — safe in-DB calls (alternative for `issues/01`)

The new **Oracle PL/SQL Executor node** runs only routines visible in the connected schema metadata, with bound named/positional args, overloads, `OUT`/`IN OUT`, and an optional auto-commit toggle — a first-class, fail-secure DB path. It does not fix the unsafe SQL Query node (`issues/01` stays open as a platform caveat), but our flow can stop depending on MCP shims for DB access.

- **Code.** Spike: call `AGENT_TOOLS.PKG_AGENT_TOOLS.*` (grants already in Liquibase 011/012) directly from a PL/SQL Executor node and evaluate retiring the `banking-mcp` / `application-mcp` wrapper containers (fewer moving parts). Keep MCP if the node can't resolve the token-keyed read/write cleanly — decide from the spike, don't rip out MCP blind.
- **Docs.** If adopted: trim the `banking-mcp` / `application-mcp` registrations from `LOCAL.md §4`, update the tool-channel description in `docs/DESIGN.md`, and note in `issues/01` that the flow no longer touches the SQL Query node.
- **Guide steps.** Register a Database datasource for the node, select the approved routines, map the bound arguments; document the auto-commit setting for the `upsert` write.

### 0.4 Agent observability / OTel tracing — mitigates `issues/03` and `issues/06`

26.4 adds OTel tracing (Arize Phoenix / Comet Opik / Langfuse) capturing spans for flow steps, LLM calls, and tool executions, plus a Collect-Diagnostics ZIP. This is the missing diagnostic surface for the `max_iterations=5` cliff and the ID-only validator errors (neither root cause is fixed in code).

- **Code.** Optional: add a local trace-collector service (e.g. Phoenix or Langfuse) to `deploy/podman/compose.local.yml` if we want traces without a cloud account; otherwise no code.
- **Docs.** Add an "enable tracing" recipe to `docs/TROUBLESHOOT.md` and an optional step in `LOCAL.md`. Note in `issues/03` / `issues/06` that 26.4 makes the conditions observable even though the messages/cap are unchanged.
- **Guide steps.** PAF Settings → tracing provider → point at the collector, enable masking; show where a `CHAT_WORKFLOW` run's per-tool spans land.

## 1. Proactive product recommendation as a second workflow

Clone the `CHAT_WORKFLOW` pattern into a second PAF Agent Builder flow over the same `REPORTING.*` view set, with a different agent prompt + tool surface + signal weights, writing to a recommendation queue rather than `hitl_task`. Reuses the existing backbone (HITL, audit, OPA grounding, RAG citations, configurable signal weights) for a recommendation surface alongside the decisioning surface.

## 3. XGBoost credit-scoring tool

A separate Python component that trains an **XGBoost** model in **OML4Py** (Oracle Machine Learning for Python, runs in-database) on the existing synthetic data, registers it in the OML model registry, and exposes it as an additional tool the agent calls during evidence gathering:

`predict_credit_score(customer_id)` → `{score, top_features}`

The agent appends this to the evidence packet alongside OPA outputs, OCR quality, and employer verification. The backoffice reviewer then sees in the recommendation panel something like: _"Customer 12345 has a credit-risk score of 0.42, driven by (1) low transaction velocity in the last 90 days, (2) recent salary increase, (3) no late payments in the last 12 months."_

Shape of the new component:

```
src/ml/credit-score/
├── train.py        # OML4Py — reads REPORTING.cust_360, fits XGBoost, registers model
├── deploy.py       # creates AGENT_TOOLS.predict_credit_score PL/SQL wrapper
├── Containerfile   # one-shot container; run via manage.py
└── README.md
```

Wired into the PoC via:

- New Liquibase changeset for the `AGENT_TOOLS.predict_credit_score` PL/SQL function and any model-registry references.
- New `manage.py ml train` / `manage.py ml deploy` commands.
- The `Recommendation` agent's prompt (and the `Eligibility` agent's evidence) updated to ingest the new score field; a weight added to `system_config` so it contributes to the tier composition.
- Exposed to PAF following the existing `create_hitl_task` pattern — **Select AI Tool** on cloud / ADB, thin **MCP wrapper** on local / Free 26ai. Same PL/SQL function on both sides; only the transport differs.

End-to-end coverage: **training** (OML4Py + XGBoost) → **deployment** (model registry + PL/SQL wrapper) → **inference** (in-DB scoring via `PREDICTION()`) → **explainability** (top features surfaced in evidence). The feedback loop already exists — the `decision` Blockchain row captures human outcomes, ready for future retraining cycles.

## 4. TOON feasibility spike

TOON ("Token-Oriented Object Notation") is a compact JSON-alternative serialization that uses 30–50% fewer tokens for structured payloads sent to an LLM. Worth applying once the §3 evidence (score + top features) starts landing in the prompt alongside RAG chunks and OPA outputs.

Open questions the spike must answer:

- Can a PAF **Function node** import a `toon` Python library and transform tool output before it reaches the next node?
- Can a **Prompt template** invoke a custom serializer, or is it plain string interpolation?
- What packages ship with the PAF container runtime, and can we add more?

Outcome: TOON encoding happens either inside the PAF flow (clean, one place to look) or in the prompt-builder code outside PAF (still works, less tidy). Document the recipe (or the constraint).

---

## Execution order

1. **End-to-end test the built `CHAT_WORKFLOW`** across the seeded scenarios (the deterministic flow is built, published, and exported; the `get_context` entry is validated). Run `tests/test_chat_workflow.py` + the tier table in `paf/flows/CHAT_WORKFLOW.md §Test prompts`.
2. Finish the loan-decisioning end-to-end: real OCR pipeline, the remaining Application Service bits, the two Angular UIs, Blockchain `decision` write at HITL close.
3. §3 — XGBoost credit-scoring tool (reads the shipped `REPORTING.cust_360`).
4. §1 — product-recommendation workflow. Consumes the credit-score tool from §3 as one of its signals.
5. §4 — TOON spike. Independent of the steps above, can happen in parallel.
6. §0 residuals — all optional/alternative (0.1 export-import scripting + doc cleanup, 0.3 PL/SQL-node spike, 0.4 tracing); 0.2 only if write-path corruption appears.
