# Backlog

The prioritised backlog for the PoC, in execution order: feature work first,
then optional residuals.

**Maintenance convention.** When an item is done and implemented successfully, **remove it from this backlog and delete the related `issues/` file(s)** — keep the repo describing the final state, not the history. If an issue is only **partially** improved (a workaround, not a real fix), **refresh that issue** so it stays accurate instead of deleting it.

## 1. Cloud deployment on OCI — top priority

Branch: `dev/cloud-deployment`. Runbook: [`CLOUD.md`](CLOUD.md).

The stack stands up and `manage.py cloud test` passes 11/11: four computes, ADB on a private endpoint, a public load balancer serving HTTPS with a port-80 redirect, and a private one fronting the four MCP wrappers that run as systemd services on the `backend` tier. `manage.py` owns the whole lifecycle — `setup`, `build`, `tf`, `cloud iam|plan|up|down|test`.

Remaining:

- **A rebuild from an empty compartment** with every fix in place, to confirm the runbook is complete rather than coaxed. Fixes have been applied to live instances and written back into the templates without the templates ever producing a tier from scratch; the rebuild is what proves them. It also exercises `cloud iam`, the least-travelled step in the runbook, whose failure mode reads like a model problem rather than a missing policy.
- **`RESEARCH_WORKFLOW`** — imported and linked the same way as `CHAT_FLOW`. Its database identity, `BACKOFFICE_AGENT_RO`, and its read-only view set already exist.

## 2. Converge a running tier instead of hot-patching it

A tier builds itself once: cloud-init hands the bootstrap script to systemd, the
play runs, and `/var/lib/<project>/bootstrap.ok` makes every later boot a no-op.
Terraform's payload objects key on the object name, not its content, so `cloud up`
uploads a new `ansible_backend.zip` and changes nothing on the instance — the
plan reports four object replacements and no instance change, which reads like a
successful deployment.

Everything that has to reach a built tier therefore arrives over the bastion:
MCP wrapper code copied across and the units restarted, and the integration key
written as a systemd drop-in because `PAF_AGENT_ID` / `PAF_API_KEY` do not exist
until the flow is published, long after the tier is built. The key delivery is at
least no longer a step someone can forget — `paf api-key` performs it — but it is
still a drop-in laid over the shipped unit, so both paths leave the instance's
disk describing something the repository does not.

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

## 3. Verify PAF's certificate at the load balancer

The public listener serves HTTPS on 443 with a self-signed certificate, and port 80 redirects to it, so nothing crosses the internet in the clear. Behind that, the load balancer reaches PAF over HTTPS **without verifying its certificate** (`verify_peer_certificate = false` in `deploy/tf/app/lb.tf` and `lb_internal.tf`): the hop is encrypted, but anything already inside the VCN could impersonate PAF to the load balancer.

It cannot be closed in the same apply. PAF issues its certificate during its install wizard, which runs after `cloud up`, so there is nothing to trust when the listener is created. Closing it means a second apply that uploads PAF's certificate as a trusted CA bundle and flips the backend set to `verify_peer_certificate = true`.

The front certificate is self-signed for the same reason a real one is not used: the deployment has no DNS name, so browsers warn on first visit. Giving it a hostname and issuing against that replaces the certificate and nothing else.

The same certificate is why the end-to-end harness calls PAF with verification off: it cannot tell the real load balancer from an impostor, and the suppressed `InsecureRequestWarning` says so once per turn. Verifying is cheap and does not need a DNS name — Terraform already writes the MCP gateway's certificate to `deploy/tf/app/generated/mcp-ca.pem` through a `local_file`, so the public listener's can be exported the same way, shipped to the bastion alongside `tests/`, and named in the harness's session `verify`. The warning then goes away because it stops being true, and the filter on the `cloud test` command line comes off with it.

## 4. Select AI as the cloud tool transport — on standby

`docs/DESIGN.md §11` describes Select AI Tools reached through the Select AI Bridge node as the cloud-side equivalent of the MCP wrappers. The database is ready for it — `018` grants `PAF_PLATFORM` the four packages PAF checks for, and the resource principal is enabled — but `CHAT_FLOW` does not use it: the flow reads context through `banking-mcp.get_context` and calls `create_hitl_task` through `hitl-mcp`.

Adopting it is a flow redesign rather than a port. It reopens `issues/02` (SQL Query nodes ignore bind variables and fail open), and the deterministic nodes that make the current flow safe would have to be rebuilt and revalidated against a different tool surface.

Treat it call by call rather than as a migration: a tool-shaped call such as `create_hitl_task` maps across directly, while the session-token reads are the ones that carry the bind-variable hazard. The Select AI package grants follow the audience — they go to the client user whose flow owns the profile, never to `PAF_PLATFORM`.

## 5. Let a reviewer claim from the queue

`create_hitl_task` enqueues `HITL_REQUEST` in the same transaction that writes the task row, which is the hard half. Nothing dequeues it. The review portal bypasses the queue and selects `state = 'OPEN'` straight from `hitl_task`, so there is no atomic claim, no `OPEN` → `IN_REVIEW` transition, and two reviewers can open the same case. Messages accumulate unread.

- **Code.** A claim endpoint that dequeues one message and flips that task to `IN_REVIEW` in the same transaction, with the portal calling **Claim next** instead of listing rows. The `role_hint` correlation already in the payload lets a reviewer claim only their own role's tasks, and a pending count for a notification badge falls out of the queue depth.
- **Docs.** `docs/DESIGN.md §8` step 12 already describes the claim; it becomes accurate once this lands.

## 6. Complete the decision record

The `decision` Blockchain row is meant to be the whole record of a bank decision. The insert copies the human's call and the agent packet across and leaves four columns null — `pricing_offer`, `reason_codes`, `computed_dti`, `computed_pti` — and the reviewer's decision-detail view reads all four. Reason codes survive inside the evidence JSON; the two ratios are lost even though the same turn computed them. The table is append-only, so rows written today cannot be backfilled.

- **Code.** Carry `derived.dti` / `derived.pti` from the packet onto the task row and into the decision insert; lift `reason_codes` into its own column so it is queryable; call `lookup_pricing` for `APPROVE` candidates so `pricing_offer` has a value worth storing.

## 7. Tell the customer the outcome

`docs/DESIGN.md §8` steps 11 and 12 promise that a status message and then the reviewer's final outcome are appended to the customer's `chat_message` thread. Neither happens: closing a task writes the blockchain row and appends nothing, and `hitl_status_for_session` reports `DECIDED` as soon as a _task exists_, which is the agent's recommendation being filed rather than a human deciding. There is also no progress message — the customer sees text only in reply to text they sent.

- **Code.** On close, append one `AGENT` message to the thread, phrased under the same disclosure policy the flow already obeys — the factor may be named, the number never. Have `hitl_status_for_session` return the human outcome as its own field, separate from task existence.
- **Decision.** How much a decline may disclose is the open question in `docs/DESIGN.md §12`; it gates the wording, not the mechanism.

## 8. Run the compliance checks that are already served

`opa-mcp` exposes seven typed tools. Two are called — `required_documents` and `evaluate_eligibility`. The tier rule is eligibility plus employer registration and nothing else, so the AML, KYC and fair-lending checks the design leads with (`docs/DESIGN.md §8` step 7) never run, and `lookup_pricing` and `list_policy_versions` have no caller.

- **Code.** Call `evaluate_kyc` and `evaluate_fair_lending_flags` inside `recommend_tier_for_session` and put their output in the evidence packet, so the reviewer sees them before they influence anything. `evaluate_aml` needs a `sanctions_list` table and seed rows first — `opa/packages/aml.rego` reads one and it was never created.
- **Decision.** Which of them may move the tier and which stay as evidence only is a policy choice, made once and recorded in `docs/DESIGN.md §11`.

## 9. One source of truth for the policy thresholds

`BANK_CORE.system_config` holds the thresholds, the seeds and a trigger that writes every change to `policy_parameter_history`. `opa/packages/config.rego` hardcodes the same numbers, and nothing syncs them — so the database copy is documentation and the Rego copy is what decides. No surface edits a parameter, which means the history table stays empty for the life of the deployment and the parameter-history layer in `docs/DESIGN.md §9` is a table that never receives a row.

- **Code.** An admin endpoint and a backoffice screen that write `system_config` — the trigger then fills the history table for free — and push the new values to OPA with `PUT /v1/data/decisioning/config`. Every Rego package already reads `data.decisioning.config.<key>` rather than a literal, so the policy side is a one-place change. This also retires the "restart OPA to apply parameter changes" note in `docs/DESIGN.md §11`.
- **Guide steps.** The bank administrator persona (`docs/DESIGN.md §3`) becomes real at this point; it is the only backoffice role beyond the reviewer.

## 10. Policy retrieval and the citations it would produce

`docs/DESIGN.md §8` step 8 has the agent citing lending policy, and §6.3 registers a File data source for the corpus. `BANK_CORE.policy_corpus` exists and is empty: nothing seeds it, nothing embeds into it, and no server, flow node or backend class reads it.

Three pieces, in order: a policy document chunked and loaded with real `source_doc` and `section_ref` values; an embedding pass filling the vector column; and a retrieval tool that returns the text with its source and section so the citation is checkable. The vector index comes fourth, once there are enough rows for it to earn its keep.

PAF's own knowledge-search capability may cover the second and third pieces — worth evaluating before building a retrieval tool by hand. The corpus still has to be chunked and loaded either way.

## 11. Collect and check the required documents

The required document set is computed correctly from product, employment type, residency and amount band, and it reaches the evidence packet. Nothing compares it against what the applicant actually filed: `loan_application_document` holds seed rows only, there is no upload endpoint, and the customer chat has no file control. A case can reach `REVIEW` with its document set never looked at, which leaves `docs/DESIGN.md §8` steps 3 and 4 and §6.1's "document upload to Object Storage" unimplemented.

- **Code.** An upload endpoint that stores the file against the application and writes a `loan_application_document` row, then the completeness comparison — required minus filed equals missing — feeding both the manager's "still collecting" decision and the evidence packet.

## 12. Narrow the customer read path's session lookup

`CUSTOMER_AGENT_RO` holds `SELECT` on `BANK_CORE.auth_session` because the session-scoped tools resolve an opaque token to a customer, and on `BANK_CORE.hitl_task` because the decision gate asks whether a task exists. Both are table grants, so that identity can in principle read every live session token rather than only resolve the one it was given.

- **Code.** Replace the two lookups with definer's-rights functions in `BANK_TOOLS` and grant `EXECUTE` instead of `SELECT`. It changes `banking-mcp`'s SQL on every path that resolves a token, so it wants its own change with its own test run.

## 13. Similar-case lookup for the reviewer

`case_history` holds seeded cases with their real structured fields — amount, term, DTI, PTI, credit score, outcome and reason. No code queries the table, so the anchor cases the README story promises a reviewer have data behind them and no way to reach them.

Match on structure rather than vectors: same outcome, comparable reason codes, and similar amount, DTI and score bands. That answers "how did we handle cases like this" with plain SQL and no embedding pass; `case_embedding` stays unused.

It lands as a read-only tool on `RESEARCH_WORKFLOW`, so it follows §1.

## 14. Fair-lending review producer

`BANK_CORE.fair_lending_review` was created with the config schema and is never written or read, and the per-decision fair-lending flag is uncalled (§8), so neither the pre-flight check nor the periodic review runs.

- **Code.** A job — `DBMS_SCHEDULER`, or a query run on demand for the demo — that groups closed decisions from the blockchain table by the protected attributes in `customer_protected_attrs`, computes approval rates and the four-fifths ratio, and writes one row per review period. Then a backoffice page that reads it, which is what makes the control visible rather than theoretical.

## 15. Residual follow-ups

Optional or alternative — none are blocking.

### 15.1 Deterministic `upsert` via marker — only if needed

The deterministic **read** path is shipped; `upsert_application` is **agentic on purpose** — its token corruption is fail-closed and idempotent. Only if write-path corruption appears in testing: the intake worker emits an `[[UPSERT …]]` marker → RegexExtractor + Type Convert build the JSON → a Deterministic MCP node calls `upsert_application` with the token wired. Cost: reopens the fail-open string-interpolation hazard (`issues/02`), a write-or-skip Condition (`issues/05`), and structured marker emission (`issues/09`).

### 15.2 PL/SQL Executor node — safe in-DB calls (alternative for `issues/02`)

The **Oracle PL/SQL Executor node** runs only routines visible in the connected schema metadata, with bound named/positional args, overloads, `OUT`/`IN OUT`, and an optional auto-commit toggle — a first-class, fail-secure DB path. It does not fix the unsafe SQL Query node (`issues/02` stays open as a platform caveat), but the flow can stop depending on MCP shims for DB access.

- **Code.** Spike: call `BANK_TOOLS.PKG_AGENT_TOOLS.*` (the `EXECUTE` grant is in Liquibase `020`) directly from a PL/SQL Executor node and evaluate retiring the `banking-mcp` / `application-mcp` wrappers (fewer moving parts). Keep MCP if the node can't resolve the token-keyed read/write cleanly — decide from the spike, don't rip out MCP blind.
- **Docs.** If adopted: trim the `banking-mcp` / `application-mcp` registrations from the `paf bootstrap` sheet, update the tool-channel description in `docs/DESIGN.md`, and note in `issues/02` that the flow does not touch the SQL Query node.
- **Guide steps.** Register a Database datasource for the node as the audience's client user, select the approved routines, map the bound arguments; document the auto-commit setting for the `upsert` write.

### 15.3 Agent observability / OTel tracing — mitigates `issues/04` and `issues/08`

PAF's OTel tracing (Arize Phoenix / Comet Opik / Langfuse) captures spans for flow steps, LLM calls, and tool executions, plus a Collect-Diagnostics ZIP. This is the missing diagnostic surface for the `max_iterations=5` cliff and the ID-only validator errors — neither root cause is fixed in code.

- **Code.** Optional: a trace-collector service (e.g. Phoenix or Langfuse) on the `ops` tier; otherwise no code.
- **Docs.** Add an "enable tracing" recipe to `docs/TROUBLESHOOT.md` and an optional step in `CLOUD.md`. Note in `issues/04` / `issues/08` that tracing makes the conditions observable even though the messages/cap are unchanged.
- **Guide steps.** PAF Settings → tracing provider → point at the collector, enable masking; show where a `CHAT_FLOW` run's per-tool spans land.

### 15.4 Make the decision gate run on every turn — workaround for `issues/15`

G3 — `hitl_status_for_session` and the Condition reading it — sits after the Agent node, and PAF only executes nodes downstream of an agent on the turns where the manager's LLM answers and calls a tool in the same step: measured at one turn in five. So the property it encodes, _never tell a customer their application is progressing unless the HITL task exists_, holds intermittently, and nothing distinguishes "the gate passed" from "the gate never ran".

The decisioning is untouched by this — tier, reason codes, evidence and the `hitl_task` row are computed and committed server-side before any reply text exists. What is missing is the guard on the delivery path.

A second, sharper reason to move it: the assert-wrap Prompt builds the gate's input by interpolating the worker's reply into a JSON string with no escaping, so a `"` or a line break anywhere in that reply yields `{"value": …}`, the MCP call fails argument validation, and the customer reads the apology on a perfectly good application. Enforcing the property outside the flow retires that hazard too, because the gate stops needing the reply text.

- **Code.** Enforce it in `ChatService.runTurn`, which every reply passes through: when the reply carries a `[[DECISION …]]` marker, confirm a `hitl_task` row exists for the customer's application before showing it, and fall back to the apology otherwise. `HitlRepository` already reads that table. No flow change, no model involvement removed — the worker still writes the sentence.
- **Docs.** Describe the check in `docs/DESIGN.md` next to the fail-secure error path, and note in `paf/flows/CHAT_FLOW.md` that G3 stays on the canvas as the flow-level statement of the same property.
- **Guide steps.** None — invisible to the operator.
