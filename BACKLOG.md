# Backlog

The prioritised backlog for the PoC, in execution order: feature work first,
then the items waiting on a decision or a spike, then optional residuals.

**Maintenance convention.** When an item is done and implemented successfully, **remove it from this backlog and delete the related `issues/` file(s)** — keep the repo describing the final state, not the history. If an issue is only **partially** improved (a workaround, not a real fix), **refresh that issue** so it stays accurate instead of deleting it.

## 1. Four conversation findings still open

`tests/conversation/` drives the product the way a customer does — `POST
/v1/login`, then `POST /v1/chat` and poll `GET /v1/chat/history` — so a case
crosses the whole path and asserts the database row at the end of it.
Forty-three cases across four suites, run by `python manage.py cloud bench` in
twenty to twenty-five minutes. Every case, persona and quality signal is in
[`docs/TEST-BENCH.md`](docs/TEST-BENCH.md).

It has already paid for itself: nine of the twelve findings it produced are
fixed, and two of those — the sentinel that beat the server's own envelope, and
a debt-to-income ratio answered as a bare number — were reachable by a customer
typing one sentence. Asking it to cover the compliance work then turned up a
tenth: screening vocabulary was not on the disclosure filter's banned list, so
nothing but a prompt stood between a sanctions finding and the customer.

Three remain, each behind an `xfail(strict=False)` with the assertion at full
strength, so the day one starts holding the run says `XPASS`:

- **A customer can still infer a value the policy protects.** Walking the amount
  down across four turns reads the cap off how encouraging the replies get,
  without a digit in any of them. `Disclosure` filters a reply; it cannot filter
  a sequence. Closing it means the worker not varying its tone with the amount at
  all, which costs the conversation something real.
- **The agent stops reading the turn and pushes toward submission.** Three cases
  watch for it and at least two catch it on every run. Prompt work on the Intake
  worker, and the least certain kind of fix here.
- **An instruction-shaped purpose is dropped rather than stored** — on three
  runs of four. Nothing in the product decides which happens. The half that
  matters holds every time: the instruction is not obeyed and nothing leaks.

All three are intermittent, so a fix wants its case run several times before
it is called done — one green run verifies nothing here.

- **Decision.** Which are defects to fix and which are accepted PoC behaviour.
  The bisection leak is the one most likely to be accepted.

## 2. Wire the fair-lending pre-flight

`opa/packages/` holds seven Rego policies. Six run through `banking-mcp`: eligibility and required
documents drive the flow, the rate card prices every application it can, and
`recommend_tier_for_session` evaluates KYC and AML into the evidence packet
alongside the policy modules that produced it. The reviewer reads all of them on
the task screen, and a compliance `deny` forces `DECLINE` — a sanctions match or
a failed identity check is a legal bar rather than a signal to weigh.

`decisioning.fair_lending` is the one left, and it is not simply uncalled:

- **It has no patterns to match against.** The policy only flags when a
  `monitored_patterns` entry matches both a protected attribute and the drafted
  tier, and nothing supplies that list. Called today it returns
  `flag = false` every time — evidence that proves nothing. The patterns need a
  home, which is §5.
- **It wants protected attributes on the customer-facing read path.**
  `customer_protected_attrs` holds age band and gender; `CUSTOMER_AGENT_RO`
  reads through the `BANK_VIEWS.chat_v_*` views and has no grant on it,
  deliberately. Widening that puts protected attributes where a prompt injection
  can reach, so it is a privilege-follows-audience decision rather than
  plumbing.

- **Decision.** Where monitored patterns live, and whether the per-decision
  flag belongs on the customer read path at all — the periodic sampler of §9
  reads the same attributes from the backoffice side, where the audience is
  already right.

## 3. Stand up `RESEARCH_WORKFLOW`, the backoffice research agent

The database layer is ready: seven `research_v_*` views (`006`, `008`), the
`BACKOFFICE_AGENT_RO` identity holding `SELECT` on them and `EXECUTE` nowhere
(`020`), and its password carried through Terraform. Nothing above that layer
exists — no flow, no backend surface, no reviewer panel — so `research_audit` is
a table with no writer and the `/research/*` endpoints of `docs/DESIGN.md §5`
are unimplemented.

`docs/DESIGN.md §6.3` shapes the flow as a Select AI Bridge over a
`research_profile` profile plus RAG over `policy_corpus`. Both are backlog items
in their own right — §6 and §11 — and the profile itself has never been created,
so the flow as designed cannot be built before them. A read-only MCP wrapper
over the `research_v_*` views — a third server, shaped like `banking-mcp` and
logging in as `BACKOFFICE_AGENT_RO` — carries the same read scope without
either. Which of the two the flow uses gates everything else here.

- **Decision.** Select AI Bridge, which waits on §6 and §11, or a read-only MCP
  wrapper over the view set. Record the choice in `docs/DESIGN.md §11`.
- **Code.** The flow itself — Chat Input → Prompt → Agent → Chat Output, no
  side-effect node — exported to `paf/flows/RESEARCH_WORKFLOW.paf` with its
  blueprint beside it. A second flow in `manage.py`, which resolves one agent id
  and mints one integration key (`_discover_chat_flow_id`, `paf
  link-flow|api-key|push-key`, the `info` readiness check, the `paf bootstrap`
  sheet). `/research/*` on the Application Service, writing `research_audit`.
  The Case Research panel on the reviewer's task detail screen
  (`docs/DESIGN.md §8` step 12).
- **Guide steps.** A counterpart to `CLOUD.md §9` that imports, links and
  publishes the second flow.

## 4. Narrow the customer read path's session lookup

`CUSTOMER_AGENT_RO` holds `SELECT` on `BANK_CORE.auth_session` because the session-scoped tools resolve an opaque token to a customer, and on `BANK_CORE.hitl_task` because the decision gate asks whether a task exists. Both are table grants, so that identity can in principle read every live session token rather than only resolve the one it was given.

- **Code.** Replace the two lookups with definer's-rights functions in `BANK_TOOLS` and grant `EXECUTE` instead of `SELECT`. It changes `banking-mcp`'s SQL on every path that resolves a token, so it wants its own change with its own test run.

## 5. One source of truth for the policy thresholds

`BANK_CORE.system_config` holds the thresholds, the seeds and a trigger that writes every change to `policy_parameter_history`. `opa/packages/config.rego` hardcodes the same numbers, and nothing syncs them — so the database copy is documentation and the Rego copy is what decides. No surface edits a parameter, which means the history table stays empty for the life of the deployment and the parameter-history layer in `docs/DESIGN.md §9` is a table that never receives a row.

- **Code.** An admin endpoint and a backoffice screen that write `system_config` — the trigger then fills the history table for free — and push the new values to OPA with `PUT /v1/data/decisioning/config`. Every Rego package already reads `data.decisioning.config.<key>` rather than a literal, so the policy side is a one-place change. This also retires the "restart OPA to apply parameter changes" note in `docs/DESIGN.md §11`.
- **Guide steps.** The bank administrator persona (`docs/DESIGN.md §3`) becomes real at this point; it is the only backoffice role beyond the reviewer.

## 6. Policy retrieval and the citations it would produce

`docs/DESIGN.md §8` step 8 has the agent citing lending policy, and §6.3 registers a File data source for the corpus. `BANK_CORE.policy_corpus` exists and is empty: nothing seeds it, nothing embeds into it, and no server, flow node or backend class reads it.

Three pieces, in order: a policy document chunked and loaded with real `source_doc` and `section_ref` values; an embedding pass filling the vector column; and a retrieval tool that returns the text with its source and section so the citation is checkable. The vector index comes fourth, once there are enough rows for it to earn its keep.

PAF's own knowledge-search capability may cover the second and third pieces — worth evaluating before building a retrieval tool by hand. The corpus still has to be chunked and loaded either way.

## 7. Collect and check the required documents

The required document set is computed correctly from product, employment type, residency and amount band, and it reaches the evidence packet. Nothing compares it against what the applicant actually filed: `loan_application_document` holds seed rows only, there is no upload endpoint, and the customer chat has no file control. A case can reach `REVIEW` with its document set never looked at, which leaves `docs/DESIGN.md §8` steps 3 and 4 and §6.1's "document upload to Object Storage" unimplemented.

- **Code.** An upload endpoint that stores the file against the application and writes a `loan_application_document` row, then the completeness comparison — required minus filed equals missing — feeding both the manager's "still collecting" decision and the evidence packet.

## 8. Similar-case lookup for the reviewer

`case_history` holds seeded cases with their real structured fields — amount, term, DTI, PTI, credit score, outcome and reason. No code queries the table, so the anchor cases the README story promises a reviewer have data behind them and no way to reach them.

Match on structure rather than vectors: same outcome, comparable reason codes, and similar amount, DTI and score bands. That answers "how did we handle cases like this" with plain SQL and no embedding pass; `case_embedding` stays unused.

It lands as a read-only tool on `RESEARCH_WORKFLOW`, so it follows §3.

## 9. Fair-lending review producer

`BANK_CORE.fair_lending_review` was created with the config schema and is never written or read, and the per-decision fair-lending flag is uncalled (§2), so neither the pre-flight check nor the periodic review runs.

- **Code.** A job — `DBMS_SCHEDULER`, or a query run on demand for the demo — that groups closed decisions from the blockchain table by the protected attributes in `customer_protected_attrs`, computes approval rates and the four-fifths ratio, and writes one row per review period. Then a backoffice page that reads it, which is what makes the control visible rather than theoretical.

## 10. Verify the load balancer's hop to PAF

`verify_peer_certificate = false` on the `paf` backend set in
`deploy/tf/app/lb.tf`: the hop is encrypted, but anything already inside the VCN
could impersonate PAF to the load balancer. It is the last unverified TLS hop —
the backend, `manage.py` and the end-to-end harness all check the certificate
they are given.

It cannot be closed in the same apply, because PAF issues its certificate during
its install wizard, which runs after `cloud up`. Closing it means a second apply
that uploads that certificate as a `ca_certificate` bundle and flips the backend
set to `verify_peer_certificate = true`.

That apply wants a spike first. PAF's certificate names `paf.private.<vcn>` and
carries no IP SAN, while an `oci_load_balancer_backend` addresses its backend by
IP — so whether the switch works at all depends on OCI validating the chain only
or the hostname too, which the provider schema does not settle. The spike is
reversible and touches one backend set: upload, flip, `curl /agentFactory`,
revert if the set goes unhealthy.

**What it does not buy.** `paf` is the only backend set that speaks TLS. The
frontend and backend sets are plain HTTP, and the internal load balancer
terminates PAF's TLS and forwards to the MCP wrappers in the clear — they serve
`streamable-http` with no certificate of their own. The VCN is mostly plaintext
by design, so this hop is encrypted-but-unauthenticated rather than the one weak
link.

The front certificate is self-signed because the deployment has no DNS name, so
browsers warn on first visit. Giving it a hostname and issuing against that
replaces the certificate and nothing else.

## 11. Select AI as the cloud tool transport — on standby

`docs/DESIGN.md §11` describes Select AI Tools reached through the Select AI Bridge node as the cloud-side equivalent of the MCP wrappers. The database is ready for it — `018` grants `PAF_PLATFORM` the four packages PAF checks for, and the resource principal is enabled — but `CHAT_FLOW` does not use it: the flow reads context through `banking-mcp.get_context` and calls `create_hitl_task` through `application-mcp`.

Adopting it is a flow redesign rather than a port. It reopens `issues/02` (SQL Query nodes ignore bind variables and fail open), and the deterministic nodes that make the current flow safe would have to be rebuilt and revalidated against a different tool surface.

Treat it call by call rather than as a migration: a tool-shaped call such as `create_hitl_task` maps across directly, while the session-token reads are the ones that carry the bind-variable hazard. The Select AI package grants follow the audience — they go to the client user whose flow owns the profile, never to `PAF_PLATFORM`.

## 12. Residual follow-ups

Optional or alternative — none are blocking.

### 12.1 Deterministic `upsert` via marker — only if needed

The deterministic **read** path is shipped; `upsert_application` is **agentic on purpose** — its token corruption is fail-closed and idempotent. Only if write-path corruption appears in testing: the intake worker emits an `[[UPSERT …]]` marker → RegexExtractor + Type Convert build the JSON → a Deterministic MCP node calls `upsert_application` with the token wired. Cost: reopens the fail-open string-interpolation hazard (`issues/02`), a write-or-skip Condition (`issues/05`), and structured marker emission (`issues/09`).

### 12.2 PL/SQL Executor node — safe in-DB calls (alternative for `issues/02`)

The **Oracle PL/SQL Executor node** runs only routines visible in the connected schema metadata, with bound named/positional args, overloads, `OUT`/`IN OUT`, and an optional auto-commit toggle — a first-class, fail-secure DB path. It does not fix the unsafe SQL Query node (`issues/02` stays open as a platform caveat), but the flow can stop depending on MCP shims for DB access.

- **Code.** Spike: call `BANK_TOOLS.PKG_AGENT_TOOLS.*` (the `EXECUTE` grant is in Liquibase `020`) directly from a PL/SQL Executor node and evaluate retiring the `banking-mcp` / `application-mcp` wrappers (fewer moving parts). Keep MCP if the node can't resolve the token-keyed read/write cleanly — decide from the spike, don't rip out MCP blind.
- **Docs.** If adopted: trim the `banking-mcp` / `application-mcp` registrations from the `paf bootstrap` sheet, update the tool-channel description in `docs/DESIGN.md`, and note in `issues/02` that the flow does not touch the SQL Query node.
- **Guide steps.** Register a Database datasource for the node as the audience's client user, select the approved routines, map the bound arguments; document the auto-commit setting for the `upsert` write.

### 12.3 Agent observability / OTel tracing — mitigates `issues/04` and `issues/08`

PAF's OTel tracing (Arize Phoenix / Comet Opik / Langfuse) captures spans for flow steps, LLM calls, and tool executions, plus a Collect-Diagnostics ZIP. This is the missing diagnostic surface for the `max_iterations=5` cliff and the ID-only validator errors — neither root cause is fixed in code.

- **Code.** Optional: a trace-collector service (e.g. Phoenix or Langfuse) on the `ops` tier; otherwise no code.
- **Docs.** Add an "enable tracing" recipe to `docs/TROUBLESHOOT.md` and an optional step in `CLOUD.md`. Note in `issues/04` / `issues/08` that tracing makes the conditions observable even though the messages/cap are unchanged.
- **Guide steps.** PAF Settings → tracing provider → point at the collector, enable masking; show where a `CHAT_FLOW` run's per-tool spans land.
