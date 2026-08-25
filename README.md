# Oracle Database Private Agent Factory — Banking Decisioning Engine PoC

A banking proof of concept showing **Oracle AI Database 26ai + Private Agent Factory** running an end-to-end retail loan decisioning flow with full observability (per-tool audit, Blockchain Tables, parameter history).

## Why this PoC exists — the story

**Lina, a credit risk analyst,** keeps hearing the same complaint from origination: loan officers and underwriters want a fast, governed first look at every incoming personal-loan application, with reasoning they can defend in front of an auditor. Today that work is ad-hoc, undocumented, and impossible to replay.

In **Private Agent Factory**, Lina builds the **Personal-Loan Chat Agent**. It talks to the customer, asks for the right documents per `(employment_type, residency_status, amount_band)`, pulls customer / bureau / facilities via Select AI over read-only views, cites lending policy via **RAG** (retrieval-augmented generation), runs **OPA** (Open Policy Agent) for eligibility / **AML** (anti-money laundering) / **KYC** (Know Your Customer) / fair-lending, and writes a **recommendation packet** to the **HITL** (human-in-the-loop) queue — with one of three tiers (**APPROVE**, **REVIEW**, **DECLINE**) plus the reasoning that justifies it. **Every** application creates a HITL task: mandatory human review is the compliance posture by design, so the business stays in control of every credit decision the bank stands behind.

This is the **factory moment**. One chat agent today; tomorrow Lina clones the pattern for credit cards, secured loans, SMB lending, mortgage triage, KYC refresh — same **MCP** (Model Context Protocol) toolkit, same Oracle AI Database, different prompt and product config.

**The customer** chats, uploads documents, and gets the agent's responses back through the same chat — follow-up questions while documents are being collected, status updates while the reviewer is working (_"we're reviewing your application"_), and the final outcome once the human has decided. The conversation is persisted server-side, threaded by `roomId`, so the customer can close the browser tab, come back hours later, and pick up where they left off — no surprise machine-rejection, no opaque approval.

**Diego, an enterprise application developer,** productises the platform: an **OPA** wrapper as an MCP server, in-DB writers in the `AGENT_TOOLS` package, a **TxEventQ** (Transactional Event Queue) queue for HITL claim, the customer chat UI, the backoffice queue, and the production APIs. He also ships a **second, backoffice-only agent** — the **Case Research Agent** — that lives behind the HITL detail screen and has access to broader data than the customer-safe chat agent: full transaction history, `decision_audit`, `policy_parameter_history`, deeper similarity over `case_history`. It cannot decide; it can read, analyse, and explain.

**Sam, a HITL reviewer,** opens the queue. He sees a **REVIEW** recommendation: _"$25,000 personal loan, self-employed expat, **DTI** (debt-to-income) of 0.41, employer registered but dormant"_. The reasoning enumerates exactly which signals tipped it — `dti_in_soft_band`, `employer_dormant`, `expat_self_employed_doc_set_complete` — plus a short list of **explore-hints** the agent suggests Sam look at. Sam asks the **Case Research Agent**: _"show me how we decided similar cases in the last 12 months"_. It answers from `case_history` with three anchor cases and citations into `decision_audit`. Sam decides DECLINE and types his note. The decision lands in the **Blockchain Table** — one row per bank decision — carrying the human's call, the agent's original recommendation, the override reason, and the full evidence packet, retained seven years and tamper-evident.

**The point of the PoC:** Private Agent Factory lets a domain expert wire a governed chat agent over Oracle AI Database — one for personal loans today, dozens for adjacent products tomorrow. The single, immutable record of the bank's decision is the **human's call**, not the AI's. Oracle AI Database 26ai carries the data, the rule-engine inputs, the vector retrieval, the queues, and the tamper-proof audit — all in one engine.

## What it looks like

![Left — the customer's Loan Assistant chat; right — the bank's Loan Review Portal with the agent recommendation, evidence and tool trace](images/UI-chat-backoffice.png)

The two ends of the same case. **Left:** the customer's chat — pick a customer, then apply and follow up in natural language. **Right:** the reviewer's portal — the agent's tier and reason codes, the evidence the agents gathered (employer verification, required documents), the per-tool audit trail with timings, and the Approve / Decline action with a mandatory comment.

## Interactions at a glance

The narrative above tells the story; the diagrams below are abstract visual anchors — one per actor, plus the chat flow's agents and data sources.

### Lina — authors the agents in PAF

```mermaid
flowchart LR
    lina(["Lina"])
    pafui["PAF Builder UI"]
    chat[["CHAT_FLOW"]]
    research[["RESEARCH_WORKFLOW"]]
    lina --> pafui
    pafui -->|"author + publish"| chat
    pafui -->|"author + publish"| research
```

### The customer — applies through chat

```mermaid
sequenceDiagram
    actor Customer
    participant Chat as Chat UI
    participant Agent as CHAT_FLOW
    participant HITL as HITL queue
    Customer->>Chat: chats, uploads docs
    Chat->>Agent: each turn
    Agent-->>Chat: questions or "under review"
    Agent->>HITL: recommendation packet when complete
    Note right of HITL: Sam decides<br/>(next diagram)
    HITL-->>Chat: final outcome appended to thread
    Chat-->>Customer: sees outcome on next chat load
```

### The chat flow — agents and their data

Same flow, one level deeper: agent by agent, and what each one reads or writes.

```mermaid
flowchart TD
    cust(["Customer"]) --> be["Chat backend"]
    be --> entry["Session context<br/><i>deterministic — no LLM</i>"]
    entry --> ctx[("Customer + application context<br/>Oracle AI Database · MCP")]
    entry --> elig{{"Eligibility decision<br/>OPA policy engine · MCP"}}

    entry --> reqd{{"Required documents<br/>OPA policy engine · MCP"}}
    entry --> reg[/"Employer verification<br/>Company Registry · REST API"/]

    entry -->|facts| mgr["Manager<br/>picks the stage, holds no tools"]

    mgr -->|"still collecting"| intake["Intake<br/>conversational collection"]
    intake --> draft[("Loan application draft<br/>Oracle AI Database · MCP")]

    mgr -->|"ready to decide"| rec["Recommendation<br/>tier + reason codes"]
    rec --> task[("Review task + queue<br/>Oracle AI Database · MCP")]

    mgr --> chk["Decision recorded?<br/><i>deterministic — no LLM</i>"]
    task -.->|"read back"| chk

    task --> sam(["Sam · reviews and decides"])
    chk -->|"customer-safe reply"| be
```

The manager gets every fact as **data** from the deterministic nodes — no agent resolves an identity, evaluates a policy, or verifies an employer itself. Only two edges write: `Intake`'s draft application and `Recommendation`'s review task, and the reply reaches the customer only once the database confirms the turn is consistent.

### Diego — builds the platform

```mermaid
flowchart LR
    diego(["Diego"])
    platform["MCP tools • App Service • UIs • DB schema • deploy"]
    diego --> platform
    platform -.-> lina_u[/"Lina (authors agents)"/]
    platform -.-> cust_u[/"Customer (chat)"/]
    platform -.-> sam_u[/"Sam (backoffice + research)"/]
```

### Sam — reviews and decides

```mermaid
sequenceDiagram
    actor Sam
    participant BO as Backoffice
    participant Research as RESEARCH_WORKFLOW
    participant Decision as Blockchain decision
    Sam->>BO: claim HITL task
    BO-->>Sam: recommendation + evidence
    opt REVIEW tier
        Sam->>Research: research chat
        Research-->>Sam: cited answer
    end
    Sam->>BO: submit APPROVE / DECLINE
    BO->>Decision: one row per bank decision
```

## Deployment

Two deployment options, same source tree:

- **Local** — rootless podman on a laptop or LAN. See [`LOCAL.md`](LOCAL.md).
- **Cloud** — Oracle Cloud Infrastructure (OCI) Terraform + Ansible (5 computes + **ADB** (Autonomous Database) + **LB** (load balancer)). See [`CLOUD.md`](CLOUD.md) _(not yet implemented)_.

## Documentation — start here

New to the project? Read in this order:

1. **This README** — the story, the current state, the quickstart.
2. [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — plain-English banking terms (DTI, PTI, KYC, AML, fair lending), if they're new to you.
3. [`docs/DECISIONING-ENGINE-USE-CASE.md`](docs/DECISIONING-ENGINE-USE-CASE.md) — the credit-decisioning use case: what the system does and why.
4. [`docs/DESIGN.md`](docs/DESIGN.md) — the architecture, PAF Hybrid runtime mapping, source layout, and locked decisions.
5. [`paf/flows/CHAT_FLOW.md`](paf/flows/CHAT_FLOW.md) — the customer-facing agent flow, in build detail.
6. [`LOCAL.md`](LOCAL.md) — stand the stack up and test it.

Reference as needed: [`docs/PAF.md`](docs/PAF.md) (generic PAF product guide) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) (deploy strategy + `manage.py`) · [`docs/TROUBLESHOOT.md`](docs/TROUBLESHOOT.md) (workarounds) · [`BACKLOG.md`](BACKLOG.md) (future features: Customer 360, XGBoost scoring, product-rec, TOON) · [`presentation/deck.md`](presentation/deck.md) (conference talk deck).

## Quickstart (local)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py setup local
python manage.py paf prepare ~/Downloads/oracle_agent_factory_<version>.tar.gz
python manage.py local up
python manage.py paf bootstrap   # prints UI installer + LLM cheatsheet
python manage.py info
```

Detailed prerequisites, day-2 commands, and troubleshooting in [`LOCAL.md`](LOCAL.md).

## Current state

What works today on the local stack:

- Oracle Database Free 26ai with `max_string_size=EXTENDED`, four schema users (`APP`, `REPORTING`, `AGENT_TOOLS`, `AGENT_FACTORY`), and PAF-specific grants on `AGENT_FACTORY`.
- Liquibase changelog `001-012`: users + grants, banking core (incl. employment / transactions / bureau / facilities), decisioning + HITL + chat persistence, `system_config` + parameter history, REPORTING view sets, `AGENT_TOOLS` PL/SQL package (`create_hitl_task`, `upsert_draft_application`), vector RAG tables (`policy_corpus`, `case_history`), the `HITL_REQUEST` TxEventQ queue, and scenario seed customers + `case_history` rows for the test bench. Changeset 011 adds the opaque-session table + seed tokens; 012 makes draft fields nullable and seeds a no-application customer for intake.
- `create_hitl_task` in `AGENT_TOOLS` verified end-to-end on Free 26ai: writes the recommendation packet to `APP.hitl_task` and enqueues `HITL_REQUEST` (JSON payload) in the same transaction.
- `DBMS_CLOUD` + `DBMS_CLOUD_AI` installed via `manage.py`. Select AI is **not** wired locally (`ORA-20401` on custom endpoints — cloud/ADB only), so the earlier Caddy TLS proxy + Oracle SSL wallet have been removed; PAF reaches the LLM directly. See [`LOCAL.md`](LOCAL.md) and [`docs/DEPLOYMENT.md §7`](docs/DEPLOYMENT.md).
- Private Agent Factory container built from the vendor kit, installed under `AGENT_FACTORY` and reachable at `https://localhost:8080/`.
- **LLM** (large language model) Configuration in PAF registered against the **vLLM** endpoint on the GPU host (generation on `:8000`, embeddings on `:8001`; both expose OpenAI-compatible APIs). `.local` mDNS hostnames are resolved on the laptop and injected into the PAF container via `extra_hosts`. Setup details: [`LOCAL.md §Setting up vLLM on a GPU host`](LOCAL.md#setting-up-vllm-on-a-gpu-host-eg-nvidia-dgx-spark).
- OPA + OPA MCP wrapper: `opa` container loads every `.rego` under `opa/packages/`; `opa-mcp` exposes seven typed tools at `http://opa-mcp:8500/mcp/` (`required_documents`, `evaluate_eligibility`, `evaluate_aml`, `evaluate_kyc`, `evaluate_fair_lending_flags`, `lookup_pricing`, `list_policy_versions`).
- `hitl-mcp` at `http://hitl-mcp:8502/mcp/` — thin Python wrapper over `oracledb.callfunc` that exposes the in-DB `AGENT_TOOLS.PKG_AGENT_TOOLS.create_hitl_task` PL/SQL function as an MCP tool (PAF's only path to in-DB side-effects locally; in cloud the same function is exposed as a Select AI Tool — see [`docs/DESIGN.md §11`](docs/DESIGN.md)).
- `registry-api` at `http://registry-api:8600/` — synthetic Company Registry FastAPI with one `verify_employer(name)` route. OpenAPI 3.1 spec, registered with PAF as an HTTP datasource. Records align with the 010 seed employers (e.g. `Phoenix Holdings Ltd` → dormant, `Atlantis Innovations Ltd` → not registered).
- Spring Boot Application Service on `localhost:8090` (mints the opaque session token at login, lists customers, brokers each chat turn, serves the HITL queue + task detail, and writes the Blockchain `decision` row when a reviewer closes a task) plus the two React/Vite SPAs — customer chat and reviewer portal — behind the Caddy proxy on `localhost:5173`.
- `CHAT_FLOW` is **one manager agent with two sub-agent workers**, fed by **five deterministic `banking-mcp` nodes**, on a self-hosted vLLM endpoint (validated on `Qwen/Qwen2.5-72B-Instruct-AWQ`; see [`LOCAL.md`](LOCAL.md) for recommended models). Four deterministic nodes run before the manager off one wired token chain — `get_context`, `evaluate_eligibility_for_session` (OPA on the DB-derived DTI/PTI), `required_documents_for_session` and `verify_employer_for_session` (Company Registry) — so every fact the decision rests on is computed server-side, with no LLM in the loop. The manager holds no tools: it reads those facts and delegates to `Intake` (conversational collection of `amount` / `term_months` / `purpose`, writing the `DRAFT` via `application-mcp.upsert_application`) or to `Recommendation` (`APPROVE` / `REVIEW` / `DECLINE` plus structured reason codes via `hitl-mcp.create_hitl_task`, the only side-effect tool, returning a compliance-safe customer sentence). A fifth deterministic node, `hitl_status_for_session`, then reads the database and the final gate passes any reply on a valid session, rejecting only an invalid one. Build blueprint with full custom-instructions blocks: [`paf/flows/CHAT_FLOW.md`](paf/flows/CHAT_FLOW.md).

  The deterministic entry in PAF Agent Builder — the session token is wired into the `banking-mcp` nodes and never transcribed by an LLM on any read path:

  ![Deterministic token entry → get_context (JSON-wrap → Type Convert → Deterministic MCP → G0)](images/chat_flow_0_token.png)

What's next, in order:

1. **End-to-end test `CHAT_FLOW` across the seeded scenarios.** `customer_id` / `application_id` are never taken from the chat message — they're resolved server-side from an opaque session token via `banking-mcp.get_context` (cx_Oracle bind variables, fail-secure), which is why a PAF SQL Query node wasn't viable (see [`issues/02-sql-query-no-bind-variables.md`](issues/02-sql-query-no-bind-variables.md)). A pytest harness covers the six happy-path tiers plus the fail-secure and prompt-injection cases: [`tests/test_chat_workflow.py`](tests/test_chat_workflow.py). Scenario table + seeded tokens in [`paf/flows/CHAT_FLOW.md §Test prompts`](paf/flows/CHAT_FLOW.md#test-prompts).
2. **`RESEARCH_WORKFLOW` flow** — backoffice-only, broader read-only scope (full transactions, `decision_audit`, `policy_parameter_history`, RAG over `policy_corpus`). No side-effect tools. Reuses the build pattern proven by `CHAT_FLOW`.
3. **Document uploads + Case Research panel** — a chat upload endpoint that stores the uploaded file against the application, and the Case Research Agent panel in the reviewer portal once `RESEARCH_WORKFLOW` (item 2) exists.
4. **Customer 360 view** — finish `REPORTING.cust_360` joining demographics, balances, products held, recent transactions, bureau snapshot, employer-verification. Feature source for item 5. See [`BACKLOG.md §2`](BACKLOG.md#2-customer-360-curated-view).
5. **XGBoost credit-scoring tool** — new `src/ml/credit-score/` Python component trains an XGBoost model in OML4Py on `REPORTING.cust_360`, registers it in OML, and exposes `AGENT_TOOLS.predict_credit_score` to the agent (Select AI Tool on cloud / MCP wrapper on local). Wires into the `Recommendation` agent's evidence + `system_config` tier weights. See [`BACKLOG.md §3`](BACKLOG.md#3-xgboost-credit-scoring-tool).
6. **Product-recommendation workflow** — second PAF Agent Builder flow over `REPORTING.cust_360`, mirroring the `CHAT_FLOW` pattern; consumes the credit-score tool from item 5 as one of its signals. See [`BACKLOG.md §1`](BACKLOG.md#1-proactive-product-recommendation-as-a-second-workflow).
7. **TOON feasibility spike** — confirm whether a PAF Function node can run a `toon` library to transform tool output, or whether encoding has to happen in the prompt-builder outside PAF. Independent — can happen in parallel. See [`BACKLOG.md §4`](BACKLOG.md#4-toon-feasibility-spike).
8. **Cloud deployment** (OCI Terraform + Ansible, ADB + LB).

Schema-side follow-ups deferred until a consumer needs them: vector index on `policy_corpus` / `case_history` (waits for the embedding pipeline that populates the `VECTOR(1024, FLOAT32)` columns via bge-m3) and the `policy_corpus` / sanctions seed data.

Two known constraints not in the "next" list because they're decided:

- **Select AI profiles are ADB-only.** Oracle Free 26ai (23.26.x) rejects custom `provider_endpoint` values in `DBMS_CLOUD_AI` pre-flight. The local `CHAT_FLOW` flow uses MCP tools + LLM; full Select AI Bridge is the cloud path. See [`docs/DEPLOYMENT.md §7`](docs/DEPLOYMENT.md).
- **Auth is out of scope.** Both UIs use a mock login (customer dropdown / role dropdown). The audience system is assumed to provide SSO in production.
