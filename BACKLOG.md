# Backlog

The prioritised backlog for the PoC, in execution order: feature work first,
then optional residuals.

**Maintenance convention.** When an item is done and implemented successfully, **remove it from this backlog and delete the related `issues/` file(s)** — keep the repo describing the final state, not the history. If an issue is only **partially** improved (a workaround, not a real fix), **refresh that issue** so it stays accurate instead of deleting it.

## 1. Cloud deployment on OCI — top priority

Branch: `dev/cloud-deployment`. Runbook: [`CLOUD.md`](CLOUD.md).

The stack stands up: four computes, ADB on a private endpoint, a public load balancer serving HTTPS with a port-80 redirect, and a private one fronting the four MCP wrappers that run as systemd services on the `backend` tier. `manage.py` owns the whole lifecycle — `setup cloud`, `build`, `tf`, `cloud iam|plan|up|down|test`.

Remaining:

- **A clean end-to-end pass of `manage.py cloud test`.** The harness runs from the bastion and drives real agent turns; nothing has yet asserted a full happy-path tier on the cloud target.
- **`RESEARCH_WORKFLOW` on cloud** — imported and linked the same way as `CHAT_FLOW`, once the chat flow passes.
- **A rebuild from an empty compartment** with every fix in place, to confirm the runbook is complete rather than coaxed.

## 2. Verify PAF's certificate at the load balancer

The public listener serves HTTPS on 443 with a self-signed certificate, and port 80 redirects to it, so nothing crosses the internet in the clear. Behind that, the load balancer reaches PAF over HTTPS **without verifying its certificate** (`verify_peer_certificate = false` in `deploy/tf/app/lb.tf`): the hop is encrypted, but anything already inside the VCN could impersonate PAF to the load balancer.

It cannot be closed in the same apply. PAF issues its certificate during its install wizard, which runs after `cloud up`, so there is nothing to trust when the listener is created. Closing it means a second apply that uploads PAF's certificate as a trusted CA bundle and flips the backend set to `verify_peer_certificate = true`.

The front certificate is self-signed for the same reason a real one is not used: the deployment has no DNS name, so browsers warn on first visit. Giving it a hostname and issuing against that replaces the certificate and nothing else.

## 3. Select AI as the cloud tool transport — on standby

`docs/DESIGN.md §11` describes Select AI Tools reached through the Select AI Bridge node as the cloud-side equivalent of the MCP wrappers. The database is ready for it — `018` grants `AGENT_FACTORY` the four packages PAF checks for, and the resource principal is enabled — but `CHAT_FLOW` does not use it: the flow reads context through `banking-mcp.get_context` and calls `create_hitl_task` through `hitl-mcp`, on both targets.

Adopting it is a flow redesign rather than a port. It reopens `issues/02` (SQL Query nodes ignore bind variables and fail open), and the deterministic nodes that make the current flow safe would have to be rebuilt and revalidated against a different tool surface. Worth doing for a more ADB-native demo, once the cloud deployment runs what the flow does today.

## 4. XGBoost credit-scoring tool

Depends on §1. `ALGO_XGBOOST` is not available on Oracle Database Free — `DBMS_DATA_MINING.CREATE_MODEL2` raises **ORA-40216: feature not supported** — so this runs against ADB. The rest of OML4SQL does work on Free, so the algorithm is the only cloud-gated piece.

Train in-database with **OML4SQL native XGBoost** and expose the result as a tool the agent calls during evidence gathering:

`predict_credit_score(customer_id)` → `{score, top_features}`

Everything is SQL and PL/SQL — `DBMS_DATA_MINING.CREATE_MODEL2` with `ALGO_XGBOOST` to train, `PREDICTION_PROBABILITY()` to score, `PREDICTION_DETAILS()` for the per-feature attributions behind `top_features`. No Python component and no separate model-serving container.

Wired into the PoC via:

- A Liquibase changeset seeding `APP.credit_training_data`: ~5,000 synthetic rows carrying the same feature columns as `REPORTING.cust_360` plus an `outcome` label. Matching column names make inference a direct `PREDICTION()` over the view.
- A Liquibase changeset that trains the model and adds `AGENT_TOOLS.PKG_AGENT_TOOLS.predict_credit_score`, reading the customer's live feature row from `REPORTING.cust_360`.
- Registration as a **Select AI Tool**, following the `create_hitl_task` pattern.
- The `Recommendation` agent's prompt (and the `Eligibility` agent's evidence) updated to ingest the score; a weight added to `system_config` so it contributes to the tier composition.

The backoffice reviewer then sees in the recommendation panel something like: _"Customer 12345 has a credit-risk score of 0.42, driven by (1) low transaction velocity in the last 90 days, (2) recent salary increase, (3) no late payments in the last 12 months."_

Fair lending holds by construction: `REPORTING.cust_360` deliberately omits `APP.customer_protected_attrs`, so protected attributes cannot reach the feature vector. The feedback loop exists — the `decision` Blockchain row captures human outcomes, ready for future retraining cycles.

## 5. Proactive product recommendation as a second workflow

Clone the `CHAT_FLOW` pattern into a second PAF Agent Builder flow over the same `REPORTING.*` view set, with a different agent prompt + tool surface + signal weights, writing to a recommendation queue rather than `hitl_task`. Reuses the existing backbone (HITL, audit, OPA grounding, RAG citations, configurable signal weights) for a recommendation surface alongside the decisioning surface. Consumes the §4 credit-score tool as one of its signals.

## 6. TOON feasibility spike

Independent of §1–§5 — can happen in parallel.

TOON ("Token-Oriented Object Notation") is a compact JSON-alternative serialization that uses 30–50% fewer tokens for structured payloads sent to an LLM. Worth applying once the §4 evidence (score + top features) lands in the prompt alongside RAG chunks and OPA outputs.

Open questions the spike must answer:

- Can a PAF **Function node** import a `toon` Python library and transform tool output before it reaches the next node?
- Can a **Prompt template** invoke a custom serializer, or is it plain string interpolation?
- What packages ship with the PAF container runtime, and can we add more?

Outcome: TOON encoding happens either inside the PAF flow (clean, one place to look) or in the prompt-builder code outside PAF (still works, less tidy). Document the recipe (or the constraint).

## 7. Residual follow-ups

Optional or alternative — none are blocking.

### 7.1 Flow export/import

Flow export/import is a **UI operation** (Agent Builder → My Custom Flows) — intentionally **not** scripted in `manage.py`. The round-trip works and is documented (`LOCAL.md §5`). The residuals are operational: deps re-link by hand on import, imports arrive unpublished, and `.paf` is binary so not git-diffable.

### 7.2 Deterministic `upsert` via marker — only if needed

The deterministic **read** path is shipped; `upsert_application` is **agentic on purpose** — its token corruption is fail-closed and idempotent. Only if write-path corruption appears in testing: the intake worker emits an `[[UPSERT …]]` marker → RegexExtractor + Type Convert build the JSON → a Deterministic MCP node calls `upsert_application` with the token wired. Cost: reopens the fail-open string-interpolation hazard (`issues/02`), a write-or-skip Condition (`issues/05`), and structured marker emission (`issues/09`).

### 7.3 PL/SQL Executor node — safe in-DB calls (alternative for `issues/02`)

The **Oracle PL/SQL Executor node** runs only routines visible in the connected schema metadata, with bound named/positional args, overloads, `OUT`/`IN OUT`, and an optional auto-commit toggle — a first-class, fail-secure DB path. It does not fix the unsafe SQL Query node (`issues/02` stays open as a platform caveat), but the flow can stop depending on MCP shims for DB access.

- **Code.** Spike: call `AGENT_TOOLS.PKG_AGENT_TOOLS.*` (grants in Liquibase 011/012) directly from a PL/SQL Executor node and evaluate retiring the `banking-mcp` / `application-mcp` wrapper containers (fewer moving parts). Keep MCP if the node can't resolve the token-keyed read/write cleanly — decide from the spike, don't rip out MCP blind.
- **Docs.** If adopted: trim the `banking-mcp` / `application-mcp` registrations from `LOCAL.md §4`, update the tool-channel description in `docs/DESIGN.md`, and note in `issues/02` that the flow does not touch the SQL Query node.
- **Guide steps.** Register a Database datasource for the node, select the approved routines, map the bound arguments; document the auto-commit setting for the `upsert` write.

### 7.4 Agent observability / OTel tracing — mitigates `issues/04` and `issues/08`

PAF's OTel tracing (Arize Phoenix / Comet Opik / Langfuse) captures spans for flow steps, LLM calls, and tool executions, plus a Collect-Diagnostics ZIP. This is the missing diagnostic surface for the `max_iterations=5` cliff and the ID-only validator errors — neither root cause is fixed in code.

- **Code.** Optional: add a local trace-collector service (e.g. Phoenix or Langfuse) to `deploy/podman/compose.local.yml` if traces are wanted without a cloud account; otherwise no code.
- **Docs.** Add an "enable tracing" recipe to `docs/TROUBLESHOOT.md` and an optional step in `LOCAL.md`. Note in `issues/04` / `issues/08` that tracing makes the conditions observable even though the messages/cap are unchanged.
- **Guide steps.** PAF Settings → tracing provider → point at the collector, enable masking; show where a `CHAT_FLOW` run's per-tool spans land.
