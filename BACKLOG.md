# Backlog

The prioritised backlog for the PoC, in execution order: feature work first,
then optional residuals.

**Maintenance convention.** When an item is done and implemented successfully, **remove it from this backlog and delete the related `issues/` file(s)** — keep the repo describing the final state, not the history. If an issue is only **partially** improved (a workaround, not a real fix), **refresh that issue** so it stays accurate instead of deleting it.

## 1. Cloud deployment on OCI — top priority

Branch: `dev/cloud-deployment`. Runbook: [`CLOUD.md`](CLOUD.md).

The stack stands up and `manage.py cloud test` passes 11/11: four computes, ADB on a private endpoint, a public load balancer serving HTTPS with a port-80 redirect, and a private one fronting the four MCP wrappers that run as systemd services on the `backend` tier. `manage.py` owns the whole lifecycle — `setup`, `build`, `tf`, `cloud iam|plan|up|down|test`.

Remaining:

- **A rebuild from an empty compartment** with every fix in place, to confirm the runbook is complete rather than coaxed. The backend's database user and the generation model were both corrected on the live instance after its first bootstrap; the templates carry the fixes, the rebuild proves them.
- **`RESEARCH_WORKFLOW`** — imported and linked the same way as `CHAT_FLOW`.

## 2. Verify PAF's certificate at the load balancer

The public listener serves HTTPS on 443 with a self-signed certificate, and port 80 redirects to it, so nothing crosses the internet in the clear. Behind that, the load balancer reaches PAF over HTTPS **without verifying its certificate** (`verify_peer_certificate = false` in `deploy/tf/app/lb.tf`): the hop is encrypted, but anything already inside the VCN could impersonate PAF to the load balancer.

It cannot be closed in the same apply. PAF issues its certificate during its install wizard, which runs after `cloud up`, so there is nothing to trust when the listener is created. Closing it means a second apply that uploads PAF's certificate as a trusted CA bundle and flips the backend set to `verify_peer_certificate = true`.

The front certificate is self-signed for the same reason a real one is not used: the deployment has no DNS name, so browsers warn on first visit. Giving it a hostname and issuing against that replaces the certificate and nothing else.

## 3. Converge a running tier instead of hot-patching it

A tier builds itself once: cloud-init hands the bootstrap script to systemd, the
play runs, and `/var/lib/<project>/bootstrap.ok` makes every later boot a no-op.
Terraform's payload objects key on the object name, not its content, so `cloud up`
uploads a new `ansible_backend.zip` and changes nothing on the instance — the
plan reports four object replacements and no instance change, which reads like a
successful deployment.

Everything that has to reach a built tier therefore arrives by hand: MCP wrapper
code copied over the bastion and the units restarted, and the integration key
written as a systemd drop-in by `paf push-key` because `PAF_AGENT_ID` /
`PAF_API_KEY` do not exist until the flow is published, long after the tier is
built. Both work, and both leave the instance's disk describing something the
repository does not.

The fix is one command that re-converges a tier: re-fetch its payload through the
PAR and re-run its playbook, ignoring the sentinel. The play is already idempotent
— that is what the sentinel was protecting against, not a real constraint.

- **Code.** `manage.py cloud redeploy <tier>`: over the bastion, download the
  tier's artifact, unpack it, run `ansible-playbook server.yaml` locally on the
  instance, and report the result. It supersedes the manual copy-and-restart, and
  `push-key` becomes a templated value in the unit rather than a drop-in.
- **Docs.** Replace the hot-patch instructions in `docs/TROUBLESHOOT.md` with the
  command, and note in `docs/DEPLOYMENT.md` that a payload change reaches a live
  tier through `redeploy`, not through `cloud up`.
- **Guide steps.** None — it is an operator command.

## 4. Select AI as the cloud tool transport — on standby

`docs/DESIGN.md §11` describes Select AI Tools reached through the Select AI Bridge node as the cloud-side equivalent of the MCP wrappers. The database is ready for it — `018` grants `AGENT_FACTORY` the four packages PAF checks for, and the resource principal is enabled — but `CHAT_FLOW` does not use it: the flow reads context through `banking-mcp.get_context` and calls `create_hitl_task` through `hitl-mcp`.

Adopting it is a flow redesign rather than a port. It reopens `issues/02` (SQL Query nodes ignore bind variables and fail open), and the deterministic nodes that make the current flow safe would have to be rebuilt and revalidated against a different tool surface. Worth doing for a more ADB-native demo.

## 5. XGBoost credit-scoring tool

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

## 6. Proactive product recommendation as a second workflow

Clone the `CHAT_FLOW` pattern into a second PAF Agent Builder flow over the same `REPORTING.*` view set, with a different agent prompt + tool surface + signal weights, writing to a recommendation queue rather than `hitl_task`. Reuses the existing backbone (HITL, audit, OPA grounding, RAG citations, configurable signal weights) for a recommendation surface alongside the decisioning surface. Consumes the §5 credit-score tool as one of its signals.

## 7. TOON feasibility spike

Independent of §1–§6 — can happen in parallel.

TOON ("Token-Oriented Object Notation") is a compact JSON-alternative serialization that uses 30–50% fewer tokens for structured payloads sent to an LLM. Worth applying once the §5 evidence (score + top features) lands in the prompt alongside RAG chunks and OPA outputs.

Open questions the spike must answer:

- Can a PAF **Function node** import a `toon` Python library and transform tool output before it reaches the next node?
- Can a **Prompt template** invoke a custom serializer, or is it plain string interpolation?
- What packages ship with the PAF container runtime, and can we add more?

Outcome: TOON encoding happens either inside the PAF flow (clean, one place to look) or in the prompt-builder code outside PAF (still works, less tidy). Document the recipe (or the constraint).

## 8. Residual follow-ups

Optional or alternative — none are blocking.

### 8.1 Flow export/import

Flow export/import is a **UI operation** (Agent Builder → My Custom Flows) — intentionally **not** scripted in `manage.py`. The round-trip works and is documented (`CLOUD.md §9`). The residuals are operational: deps re-link by hand on import, imports arrive unpublished, and `.paf` is binary so not git-diffable.

### 8.2 Deterministic `upsert` via marker — only if needed

The deterministic **read** path is shipped; `upsert_application` is **agentic on purpose** — its token corruption is fail-closed and idempotent. Only if write-path corruption appears in testing: the intake worker emits an `[[UPSERT …]]` marker → RegexExtractor + Type Convert build the JSON → a Deterministic MCP node calls `upsert_application` with the token wired. Cost: reopens the fail-open string-interpolation hazard (`issues/02`), a write-or-skip Condition (`issues/05`), and structured marker emission (`issues/09`).

### 8.3 PL/SQL Executor node — safe in-DB calls (alternative for `issues/02`)

The **Oracle PL/SQL Executor node** runs only routines visible in the connected schema metadata, with bound named/positional args, overloads, `OUT`/`IN OUT`, and an optional auto-commit toggle — a first-class, fail-secure DB path. It does not fix the unsafe SQL Query node (`issues/02` stays open as a platform caveat), but the flow can stop depending on MCP shims for DB access.

- **Code.** Spike: call `AGENT_TOOLS.PKG_AGENT_TOOLS.*` (grants in Liquibase 011/012) directly from a PL/SQL Executor node and evaluate retiring the `banking-mcp` / `application-mcp` wrappers (fewer moving parts). Keep MCP if the node can't resolve the token-keyed read/write cleanly — decide from the spike, don't rip out MCP blind.
- **Docs.** If adopted: trim the `banking-mcp` / `application-mcp` registrations from the `paf bootstrap` sheet, update the tool-channel description in `docs/DESIGN.md`, and note in `issues/02` that the flow does not touch the SQL Query node.
- **Guide steps.** Register a Database datasource for the node, select the approved routines, map the bound arguments; document the auto-commit setting for the `upsert` write.

### 8.4 Agent observability / OTel tracing — mitigates `issues/04` and `issues/08`

PAF's OTel tracing (Arize Phoenix / Comet Opik / Langfuse) captures spans for flow steps, LLM calls, and tool executions, plus a Collect-Diagnostics ZIP. This is the missing diagnostic surface for the `max_iterations=5` cliff and the ID-only validator errors — neither root cause is fixed in code.

- **Code.** Optional: a trace-collector service (e.g. Phoenix or Langfuse) on the `ops` tier; otherwise no code.
- **Docs.** Add an "enable tracing" recipe to `docs/TROUBLESHOOT.md` and an optional step in `CLOUD.md`. Note in `issues/04` / `issues/08` that tracing makes the conditions observable even though the messages/cap are unchanged.
- **Guide steps.** PAF Settings → tracing provider → point at the collector, enable masking; show where a `CHAT_FLOW` run's per-tool spans land.

### 8.5 Make the decision gate run on every turn — workaround for `issues/15`

G3 — `hitl_status_for_session` and the Condition reading it — sits after the Agent node, and PAF only executes nodes downstream of an agent on the turns where the manager's LLM answers and calls a tool in the same step: measured at one turn in five. So the property it encodes, _never tell a customer their application is progressing unless the HITL task exists_, holds intermittently, and nothing distinguishes "the gate passed" from "the gate never ran".

The decisioning is untouched by this — tier, reason codes, evidence and the `hitl_task` row are computed and committed server-side before any reply text exists. What is missing is the guard on the delivery path.

A second, sharper reason to move it: the assert-wrap Prompt builds the gate's input by interpolating the worker's reply into a JSON string with no escaping, so a `"` or a line break anywhere in that reply yields `{"value": …}`, the MCP call fails argument validation, and the customer reads the apology on a perfectly good application. Enforcing the property outside the flow retires that hazard too, because the gate stops needing the reply text.

- **Code.** Enforce it in `ChatService.runTurn`, which every reply passes through: when the reply carries a `[[DECISION …]]` marker, confirm a `hitl_task` row exists for the customer's application before showing it, and fall back to the apology otherwise. `HitlRepository` already reads that table. No flow change, no model involvement removed — the worker still writes the sentence.
- **Docs.** Describe the check in `docs/DESIGN.md` next to the fail-secure error path, and note in `paf/flows/CHAT_FLOW.md` that G3 stays on the canvas as the flow-level statement of the same property.
- **Guide steps.** None — invisible to the operator.
