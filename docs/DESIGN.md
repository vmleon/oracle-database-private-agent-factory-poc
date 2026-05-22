# Decisioning Engine PoC — Design

This document is the **architectural plan** for the PoC. It does not prescribe code. The use case it supports is fully described in [DECISIONING-ENGINE-USE-CASE.md](DECISIONING-ENGINE-USE-CASE.md); the platform it runs on is summarised in [PAF.md](PAF.md). Deployment specifics live in [DEPLOYMENT.md](DEPLOYMENT.md).

The PoC is intentionally a _scaffolding_ — the repository layout, deployment topology, and component boundaries are fixed early so subsequent work can fill each component without re-arguing the seams.

---

## 1. Goals

- Demonstrate that **Oracle AI Database 26ai + Private Agent Factory (PAF)** can run an end-to-end agentic banking flow (credit application decisioning).
- Prove **end-to-end observability**: every decision is reproducible from an append-only audit trail (Blockchain Table + per-tool audit + parameter history).
- Demonstrate the **PAF Hybrid runtime mode**: an Agent Builder flow in the PAF container that delegates SQL and **RAG** (retrieval-augmented generation) to in-database Select AI tools and external behaviour to **MCP** (Model Context Protocol) / REST tools.
- Provide **two deployment options** with the same source tree: a fully-local podman stack on a laptop or LAN, and a cloud stack provisioned on Oracle Cloud Infrastructure (OCI) with Terraform + Ansible.
- Keep the audience-facing posture **on-premises private by default** (vLLM on a self-hosted GPU host — NVIDIA-supported, OpenAI-compatible API surface), with a documented migration path to OCI Generative AI when sanctioned.
- Stay **bank-agnostic**: every threshold, weight, scale, policy parameter, and protected-attribute set lives in database configuration, not in code.

## 2. Non-goals

- Production-grade credit modelling (the dataset is synthetic and engineered to exercise paths, not to validate a model).
- Performance benchmarking (the test bench is for functionality and observability).
- Region-specific compliance attestation (the PoC is region-agnostic by design; the framework is operational, not legal).
- Counter-offer logic, real bureau integration, core-banking write-back, or production-grade Application Service hardening.

## 3. Audience and personas

| Persona                                              | Surface                             | What they do                                                                                                                                                                                                          |
| ---------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Loan applicant (customer)                            | Customer mobile chat                | Drives the chat, uploads documents, gets a status ("under review"); the customer is the primary user of the `CHAT_WORKFLOW`                                                                                           |
| Credit risk analyst (agent author)                   | **PAF Builder UI**                  | Wires the `CHAT_WORKFLOW` and `RESEARCH_WORKFLOW` flows in PAF: tools, Select AI profile, RAG, system prompts; owns the recommendation tiers and explore-hints                                                        |
| Application developer (platform)                     | IDE, repo, deploy tooling           | Builds and operates the MCP tools (**OCR** (optical character recognition), **OPA** (Open Policy Agent), in-DB writers), the chat UI, the backoffice, the `AGENT_TOOLS` package, the queues, the deployment scripting |
| **HITL** (human-in-the-loop) reviewer / loan officer | Backoffice UI + Case Research Agent | Picks up tasks from the queue, reads the recommendation + reasoning + evidence, talks to the Case Research Agent for context, decides                                                                                 |
| Bank administrator                                   | Backoffice UI                       | Edits `system_config`, manages users, views audit                                                                                                                                                                     |
| Fair-lending reviewer                                | Backoffice UI                       | Reviews disparate-impact samples, records conclusions                                                                                                                                                                 |
| Risk analyst                                         | Backoffice UI                       | Drives Risk Management Dashboard, stress scenarios, drift alerts                                                                                                                                                      |

## 4. High-level architecture

The deployment is one logical system with several cooperating components. Their boundaries follow the PAF [MCP security pattern](PAF.md): agents call MCP/REST tools, never application tables directly.

```mermaid
flowchart TB
    mobile["Customer Mobile UI<br/>(Angular)"]
    backoffice["Backoffice UI<br/>(Angular)"]
    appsvc["Application Service<br/>(Java / Spring Boot)<br/>UCP, wallet, drivers"]
    ai["AI Services (Python)<br/>- PAF caller<br/>- OPA MCP<br/>- OCR MCP"]
    registry["Company Registry API<br/>(FastAPI, OpenAPI 3.1)<br/>employer verification"]
    paf["Private Agent Factory (container)<br/>CHAT_WORKFLOW (customer)<br/>RESEARCH_WORKFLOW (backoffice)"]
    opa["OPA<br/>(Rego packages)"]
    vllm["vLLM (gen + embed)<br/>(self-hosted GPU host)"]
    db[("Oracle AI Database 26ai<br/>schemas + vector + TxEventQ")]

    mobile -- chat --> appsvc
    backoffice -- "CRUD / HITL" --> appsvc
    backoffice -- "research chat" --> appsvc
    appsvc --> ai
    ai --> paf
    ai --> opa
    paf --> vllm
    paf --> db
    paf -- "HTTP datasource<br/>(OpenAPI)" --> registry
    opa --> db
    appsvc --> db
```

Components communicate as follows:

- **Customer Mobile UI** → Application Service over REST. Auth is out of scope for the PoC; a mock login screen offers a dropdown of demo customers, selecting one fixes the `customer_id` used for every subsequent request. Logout returns to the picker. Chat turns (both customer messages and agent replies) are persisted server-side keyed by `roomId` + `customer_id`, so the UI is stateless — on refresh, login, or device switch, the UI replays the conversation history from the Application Service. The customer can close the browser, return hours later, and continue from the last agent reply (a status update, a follow-up question, or the final outcome).
- **Backoffice UI** → Application Service over REST. Auth is out of scope for the PoC; a mock login screen offers a dropdown of roles (HITL reviewer, admin, fair-lending reviewer, risk analyst), selecting one drives which sections are visible. Logout returns to the picker.
- Production deployments are expected to sit behind the host core-banking system's auth, so no SSO/OAuth/JWT/API Gateway wiring is built into the PoC.
- **Application Service** persists applications, owns document upload, runs cheap OPA pre-checks, and invokes the agents. It exposes two distinct PAF surfaces: `/chat/*` for the customer `CHAT_WORKFLOW` and `/research/*` for the backoffice `RESEARCH_WORKFLOW`.
- **Application Service** invokes each **PAF published Agent Builder endpoint** going through the AI Services tier to handle session-cookie acquisition and chunked response parsing (per PAF [APEX integration pattern](PAF.md#16-apex-integration-pattern) — the same bridge concern applies to any non-PAF caller).
- **PAF (`CHAT_WORKFLOW`, customer-facing)** runs in the PAF container and calls:
  - **Select AI in-DB tools** over the customer-safe `REPORTING.*` view set (own profile, transactions, bureau snapshot, existing facilities).
  - **OPA MCP** for eligibility, AML, KYC, escalation, fair-lending, pricing band — inputs to the recommendation, not the decision.
  - **OCR MCP** for document field extraction and quality tiering.
  - **Company Registry HTTP datasource** — typed OpenAPI 3.1 endpoint exposed by a FastAPI service. The agent calls it once per application to verify the customer's declared employer (or their own company, for self-employed). Light usage; this is the demo surface for PAF's HTTP datasource capability.
  - **vLLM** as the configured **LLM** (large language model) and embedding endpoint (LLM Management). Two vLLM containers run on the GPU host — one for generation (`Qwen/Qwen2.5-32B-Instruct-AWQ` on `:8000`), one for embeddings (`BAAI/bge-m3` on `:8001`) — both exposing OpenAI-compatible APIs that PAF reaches via its built-in **vLLM** provider.
  - In-DB tool `create_hitl_task` to write a recommendation packet to the HITL queue.
- **PAF (`RESEARCH_WORKFLOW`, backoffice-only)** runs in the same PAF container with a **broader, read-only tool scope** — full transaction history, `decision_audit`, `policy_parameter_history`, deeper similarity over `case_history`, RAG over `policy_corpus`. The agent is read-only by design: it reads, analyses, and explains; it cannot mutate state. Invocation is gated by the backoffice (the customer chat path cannot reach it).
- **Final decision** is written to `decision` (Blockchain Table) by the Application Service when the HITL reviewer closes the task. The agent's recommendation packet is captured as columns on the same row, so each Blockchain row is exactly one bank decision.

## 5. PAF runtime mode: Hybrid

The PoC runs in PAF's **Hybrid** mode (see [PAF.md §4.3](PAF.md#43-hybrid-agentworkflow)) and configures **two distinct agents** in the same PAF container, with different tool scopes and different security envelopes:

- **`CHAT_WORKFLOW`** — customer-facing. Reads only the customer-safe `REPORTING.*` view set, runs OCR + OPA, writes a recommendation packet to `hitl_task` via the `create_hitl_task` in-DB tool. Cannot write to `decision`.
- **`RESEARCH_WORKFLOW`** — backoffice-only. Reads a **broader, read-only** scope (full transaction history, `decision_audit`, `policy_parameter_history`, deeper `case_history` similarity, RAG over `policy_corpus`). Has **no side-effect tools** — it cannot create HITL tasks, cannot record decisions, cannot mutate state of any kind.

Heavy data work — SQL over banking views, vector search over `policy_corpus` and `case_history` — runs **in-database** via Select AI profiles, tasks, tools, and teams. Policy and side-effect work — OPA evaluation, OCR extraction, HITL task creation — runs in **near-DB MCP/REST services** and is wired to `CHAT_WORKFLOW` only.

Mapping the use case to PAF's component types:

| Capability                                                  | PAF construct                                                  | Wired to            | Where it runs                |
| ----------------------------------------------------------- | -------------------------------------------------------------- | ------------------- | ---------------------------- |
| Chat orchestration (customer)                               | Agent Builder flow, Agent node                                 | `CHAT_WORKFLOW`     | Near-DB, PAF container       |
| Research orchestration (backoffice)                         | Agent Builder flow, Agent node                                 | `RESEARCH_WORKFLOW` | Near-DB, PAF container       |
| LLM rationale + research composition                        | LLM node, configured vLLM endpoint                             | Both                | Self-hosted GPU host         |
| Per-tool audit envelope                                     | Agent run → `decision_audit` writer                            | `CHAT_WORKFLOW`     | Tool wrapper inside PAF flow |
| Customer profile / transactions / bureau queries            | Select AI profile + tasks over curated views                   | `CHAT_WORKFLOW`     | In-DB                        |
| Broader read scope (audit, parameter history, deeper cases) | Select AI profile + tasks over backoffice view set             | `RESEARCH_WORKFLOW` | In-DB                        |
| Policy citations, similar cases                             | Select AI RAG tool over Oracle AI Vector Search                | Both                | In-DB                        |
| OPA eligibility/AML/KYC/escalation/fair-lending/pricing     | MCP Server node → OPA MCP (Python FastMCP)                     | `CHAT_WORKFLOW`     | Near-DB                      |
| Document extraction + quality tiering                       | MCP Server node → OCR MCP (Python)                             | `CHAT_WORKFLOW`     | GPU node                     |
| Employer / company registry lookup                          | HTTP datasource (OpenAPI 3.1 over FastAPI)                     | `CHAT_WORKFLOW`     | Near-DB (`app` compute)      |
| HITL task creation (recommendation packet)                  | In-DB SQL tool in `AGENT_TOOLS` package                        | `CHAT_WORKFLOW`     | In-DB                        |
| Final decision write (Blockchain)                           | Application Service on HITL close                              | Application Service | In-DB (Blockchain Table)     |
| Customer chat surface                                       | Published Agent Builder run URL via Application Service bridge | `CHAT_WORKFLOW`     | Near-DB + external           |
| Backoffice research surface                                 | Published Agent Builder run URL via Application Service bridge | `RESEARCH_WORKFLOW` | Near-DB + external           |

## 6. Component breakdown

### 6.1 Custom application code (`src/`)

| Component                  | Tech                  | Responsibility                                                                                                                                                                                                                                                            |
| -------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/backend/`             | Java 21 / Spring Boot | Application Service. Application CRUD, document upload to Object Storage, OPA pre-check fast-path, agent invocation, sanitised decision read-back. Uses **UCP** (Universal Connection Pool) for pooling and Oracle Wallet for **ADB** (Autonomous Database).              |
| `src/ai/`                  | Python                | Three sub-services: (a) PAF caller (acquires session cookie, calls Agent Builder run URL, handles `roomId` continuity); (b) OPA MCP server (FastMCP, wraps OPA REST); (c) OCR MCP server (FastMCP, wraps YOLO + PaddleOCR/Tesseract). All exposed under `/mcp` or `/api`. |
| `src/api/registry/`        | Python / FastAPI      | Synthetic Company Registry API. One service, one endpoint group; auto-generated OpenAPI 3.1 spec served at `/openapi.json`. Data is a JSON file shipped with the service — no real bureau integration. Registered with PAF as an HTTP datasource for `CHAT_WORKFLOW`.     |
| `src/frontend-backoffice/` | Angular               | HITL queue, decision browser, parameter management (`system_config` editor with reason capture), rule view (read-only Rego browser), risk dashboard, fair-lending review, customer search.                                                                                |
| `src/frontend-mobile/`     | Angular               | Simulated mobile chat for the loan applicant: conversation, document upload widget with quality-tier status, decision delivery, "why was I declined" follow-up.                                                                                                           |

### 6.2 Database (`database/`)

Liquibase changelogs in two parallel directories:

- `database/liquibase/oracle/` — local Oracle Free 26ai.
- `database/liquibase/adb/` — cloud Autonomous Database 26ai.

Both load the same banking + decisioning schema; differences confined to ADB-specific bootstrap (DBMS_CLOUD grants, wallet-aware connection, Select AI profile templates) and local-only conveniences (test users, sample data seed toggles).

Schema layers, following PAF's [recommended Oracle Database design pattern](PAF.md#193-recommended-oracle-database-design-pattern):

| Schema / User   | Contents                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Used by                                                                                                                                           |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `APP`           | Banking tables: `customer`, `account*`, `loan_application*`, `decision` (Blockchain Table — written by the Application Service when a HITL task closes), `decision_audit`, `hitl_task` (carries the agent's recommendation packet), `chat_message` (persisted customer ↔ `CHAT_WORKFLOW` conversation, keyed by `roomId` + `customer_id` + `application_id`, so the chat UI can refresh and replay history), `system_config`, `policy_parameter_history`, `fair_lending_review`. Also owns the **TxEventQ** (Transactional Event Queue) queues (`HITL_REQUEST`, `OCR_REQUEST`, `OCR_EXCEPTION_Q`). | Application Service + agent enqueue/dequeue via scoped `dbms_aqadm.grant_queue_privilege` grants; agents never write the banking tables directly. |
| `REPORTING`     | Two curated view sets over `APP` for **NL2SQL** (natural-language-to-SQL): a **customer-safe** set for `CHAT_WORKFLOW` (own profile, transactions summary, bureau snapshot, existing facilities) and a **backoffice-broader** set for `RESEARCH_WORKFLOW` (full transaction history, `decision_audit`, `policy_parameter_history`, deeper `case_history`).                                                                                                                                                                                                                                         | Two Select AI NL2SQL object lists — one per agent; read-only on both sides.                                                                       |
| `AGENT_TOOLS`   | PL/SQL packages exposed as Select AI tools / MCP tools: `create_hitl_task` (writes the recommendation packet), `lookup_pricing`, `extract_features`. The Blockchain `decision` row is written by the Application Service when the human closes a HITL task.                                                                                                                                                                                                                                                                                                                                        | `CHAT_WORKFLOW` only; tightly scoped grants. `RESEARCH_WORKFLOW` has no execute grant here.                                                       |
| `AGENT_FACTORY` | PAF platform metadata only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | PAF; no production data                                                                                                                           |
| Vector          | `policy_corpus`, `case_history` with `VECTOR(<dim>, FLOAT32)`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Select AI RAG profiles — both agents read; neither writes.                                                                                        |

Embedding dimension is set once at deploy time and tied to the chosen vLLM embedding model (`BAAI/bge-m3` → 1024 dims by default). Changing embedding model later requires re-ingestion — flagged in deployment notes (see [PAF §6.6](PAF.md#66-embedding-models)).

### 6.3 Private Agent Factory artefacts

Stored under `paf/` and bootstrapped by `manage.py` after PAF is up:

- **LLM Management** configurations: `vllm-gen-qwen2.5-32B`, `vllm-embed-bge-m3` pointing at the configured vLLM endpoints (provider: `vLLM`, separate Host + Port fields).
- **Data sources**:
  - Two **Database** data sources over `REPORTING` (one customer-safe, one backoffice-broader).
  - One **File** data source for the seed `policy_corpus` PDFs/text.
  - One **HTTP** data source — the Company Registry API. Registered to PAF by pointing at its OpenAPI 3.1 spec (`/openapi.json`); PAF infers the endpoint shape, request schema, and response schema from the spec. This demonstrates PAF's third data-source type alongside Database and File.
- **Select AI profiles**:
  - `chat_profile` — NL2SQL object list scoped to the customer-safe `REPORTING.*` views, RAG vector index over `policy_corpus`.
  - `research_profile` — NL2SQL object list scoped to the broader backoffice `REPORTING.*` views (full transactions, `decision_audit`, `policy_parameter_history`, `case_history`), RAG over both `policy_corpus` and `case_history`.
- **MCP Server nodes**: `opa-mcp` and `ocr-mcp` — registered, but wired only to `CHAT_WORKFLOW`.
- **Agent Builder flows** (two):
  - `CHAT_WORKFLOW`: a two-agent pipeline — Chat Input + SQL Query (application context) → Prompt (Evaluation) → **EvaluationAgent** (tools: OPA MCP `required_documents` + `evaluate_eligibility`, Company Registry REST `verify_employer`; emits a structured evidence block) → Prompt (Recommendation) → **RecommendationAgent** (tools: HITL MCP `create_hitl_task` only) → Chat Output. `create_hitl_task` is the workflow's only side-effect tool, and it's reachable only from `RecommendationAgent`. Full build blueprint: [`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md).
  - `RESEARCH_WORKFLOW`: Chat Input → Prompt (read-only research system rules) → Agent (tools = Select AI Bridge over `research_profile`, RAG, no MCP tools, no HTTP datasources, no In-DB write tools) → Chat Output. The flow is intentionally simple — its value is the broader read scope and the conversational interface, not orchestration.
- **Published agent URLs** captured in `.env` (`PAF_CHAT_RUN_URL`, `PAF_RESEARCH_RUN_URL`) and surfaced by `manage.py info`.

Both flows follow PAF's [authoring-to-execution pipeline](PAF.md#105-authoring-to-execution-pipeline): explicit inputs, explicit tool boundaries, explicit Condition/Parser gating before any side-effect node.

### 6.4 Configuration boundary

Two stores; nothing belongs in code:

- **`.env`** (rendered by `manage.py setup`): infrastructure pointers — OCI profile, region, compartment, ADB/Local-DB connection, vLLM host + gen/embed ports + gen/embed model handles, OCR host:port, PAF host:port, SSH key, OCI GenAI region (future), wallet path, embedding dimension.
- **`APP.system_config`** (edited from Backoffice UI): policy parameters — `min_age`, `dti_hard_cap`, `pti_hard_cap`, `score_floor`, `score_caution_band_upper`, OCR confidence thresholds, fair-lending bucketing, the **recommendation-tier weight set** (drives `APPROVE` / `REVIEW` / `DECLINE` from the composite signal), and the **`document_requirements_matrix`** (JSON: required `doc_type` set keyed by `(product_type, employment_type, residency_status, amount_band)`).

Every write to `system_config` produces a row in `policy_parameter_history` (who, when, old value, new value, reason).

## 7. Source layout

```
oracle-database-private-agent-factory-poc/
├── manage.py                 # Click-based CLI
├── requirements.txt
├── .env                      # rendered by `manage.py setup`; not committed
├── LOCAL.md                  # user-facing local-deployment playbook
├── CLOUD.md                  # user-facing cloud-deployment playbook
├── README.md
├── docs/
│   ├── DESIGN.md
│   ├── DEPLOYMENT.md
│   ├── PAF.md
│   └── DECISIONING-ENGINE-USE-CASE.md
├── src/
│   ├── backend/              # Spring Boot Application Service
│   ├── ai/                   # Python services: PAF caller, OPA MCP, OCR MCP
│   ├── api/
│   │   └── registry/         # FastAPI Company Registry — PAF HTTP datasource
│   ├── frontend-backoffice/  # Angular
│   └── frontend-mobile/      # Angular
├── database/
│   └── liquibase/
│       ├── oracle/           # local Oracle Free 26ai changelog
│       └── adb/              # cloud ADB 26ai changelog
├── paf/
│   ├── llm-management/       # JSON/Yaml templates for vLLM gen/embed configs
│   ├── data-sources/         # data source manifests (DB + file)
│   ├── select-ai/            # profile + NL2SQL object list + vector index
│   ├── mcp-servers/          # OPA + OCR registration payloads
│   └── flows/                # Agent Builder flow exports: CHAT_WORKFLOW, RESEARCH_WORKFLOW
├── opa/
│   └── packages/             # eligibility, aml, kyc, escalation, fair_lending, pricing, product (.rego)
├── ocr/
│   └── models/               # YOLO weights + OCR config; not committed
├── deploy/
│   ├── podman/               # compose / quadlet files, .env templates
│   ├── tf/
│   │   ├── app/              # root module; renders tfvars from .env
│   │   └── modules/
│   │       ├── paf/
│   │       ├── model/        # vLLM (gen + embed) + OCR on a GPU shape
│   │       ├── app/          # Spring Boot + Python services + OPA
│   │       ├── front/        # both Angular frontends behind LB paths
│   │       ├── ops/          # bastion + utilities
│   │       └── adbs/         # Autonomous Database 26ai
│   └── ansible/
│       ├── paf/
│       ├── model/
│       ├── app/
│       ├── front/
│       └── ops/
└── venv/                     # local virtualenv; not committed
```

A future `images/` directory will hold architecture diagrams once the implementation is stable.

## 8. Data flow — every application produces a recommendation packet

The customer interacts via a chat-driven flow; every turn is a `CHAT_WORKFLOW` invocation threaded by `roomId`. The agent drives document collection — it asks for what _this_ applicant needs, not a fixed bundle — and only emits its recommendation once everything is in place. Every application that completes document collection produces exactly one HITL task carrying the agent's recommendation, and the human reviewer makes the final decision.

Each turn — customer message and agent reply — is persisted as a `chat_message` row by the Application Service, keyed by `roomId` + `customer_id` + `application_id`. The chat UI is stateless: on refresh, login, or device switch it loads the message history from the Application Service and renders the conversation as the customer left it. The same persistence carries status updates ("we're reviewing your application") and the final outcome back into the chat after the reviewer closes the HITL task — so the customer always finds the latest response in the same conversation, hours or days later.

1. Customer opens mobile chat, says what they want (product, amount, purpose, term). Agent asks structured follow-ups (employment type, residency status, salary band, existing facilities) to build a partial applicant profile. Every turn is appended to `chat_message`.
2. Agent calls **OPA `required_documents(applicant_so_far, product)`** → returns the required doc set keyed by `(product_type, employment_type, residency_status, amount_band)`. The matrix lives in `system_config.document_requirements_matrix`; Select AI RAG can retrieve policy snippets to explain _why_ each document is needed.
3. Agent presents the list in chat and requests uploads. Each upload → Application Service writes a `loan_application_document` row, uploads the file to Object Storage, enqueues `OCR_REQUEST` (TxEventQ).
4. OCR worker dequeues, **classifies** the document (`doc_type` ∈ `ID` / `PAYSLIP` / `STATEMENT` / `TAX_RETURN` / `ADDRESS_PROOF` / `OTHER`) and extracts per-field values; writes back `doc_type`, `ocr_payload`, `ocr_confidence`, `quality_tier`. Failures retry up to `max_retries`; poison messages land in `OCR_EXCEPTION_Q`.
5. Agent verifies completeness via `check_document_completeness`: every required `doc_type` has at least one USABLE document with required fields extracted. Missing / MARGINAL / UNUSABLE / mismatched (e.g., a statement uploaded when an ID was requested — the classifier catches it) → agent re-asks (back to step 3). Persistent UNUSABLE after a re-upload feeds into the recommendation as a `DECLINE` signal; persistent MARGINAL feeds in as a `REVIEW` signal; the agent does not silently terminate the application.
6. Agent reads `system_config` thresholds and tier weights via In-DB Tool, then runs Select AI tools over `chat_profile` to pull profile, transactions, bureau snapshot.
7. Agent calls the **Company Registry HTTP datasource** (`verify_employer`) once with the customer's declared employer name (or, for self-employed applicants, their company name). The response — `{registered, trading_status, sector, registered_address, last_filed_year}` — joins the evidence packet. `not_registered` or `dormant` is a `REVIEW` signal with an explicit explore-hint for Sam; a confirmed `active` employer is a small positive contribution to the tiering score.
8. OPA MCP evaluates eligibility, AML, KYC, fair-lending pre-flight, escalation. Each tool output (allow / deny / warn) is captured as evidence for the recommendation; **deny does not short-circuit to REJECT** — it becomes a strong signal toward the `DECLINE` tier on the recommendation packet.
9. Select AI RAG retrieves policy citations relevant to the signals observed; for `APPROVE` candidates, OPA `lookup_pricing` returns an indicative rate band as part of the evidence packet.
10. Agent composes the **recommendation packet**: `tier ∈ {APPROVE, REVIEW, DECLINE}` (derived from OPA outputs + OCR tiers + employer-verification result + signal weights in `system_config`), `reasoning` (LLM-composed, grounded in OPA outputs and cited policy chunks), `explore_hints` (populated for `REVIEW` only — short list of areas a reviewer should examine or follow-up data to request from the customer), and `evidence` (RAG citations, OPA outputs, OCR summary, employer-verification response, computed DTI/PTI/score, indicative pricing).
11. In-DB Tool `create_hitl_task` writes one row to `hitl_task` carrying the recommendation packet **and** enqueues `HITL_REQUEST` (TxEventQ) in the same transaction. `decision_audit` captures every tool call. The agent does **not** write to `decision`.
12. PAF returns NDJSON; AI Services parses and the Application Service appends a customer-facing status message ("we're reviewing your application") to the same `chat_message` thread. The customer never sees the recommendation tier.
13. A backoffice reviewer claims the task with `DEQONE` (atomic with `hitl_task` OPEN → IN_REVIEW), reads the recommendation + reasoning + evidence, may invoke `RESEARCH_WORKFLOW` from the task detail screen to dig deeper, then submits a final decision. The Application Service writes the **`decision` Blockchain Table row** at task close — one row per bank decision, carrying both the human's final outcome and the original recommendation packet — and appends the customer-facing outcome (APPROVE with priced offer, or REJECT with reason codes) to the customer's `chat_message` thread. The next time the customer opens the chat, the outcome is waiting at the top of the conversation.

See [DECISIONING-ENGINE-USE-CASE.md §Test Bench](DECISIONING-ENGINE-USE-CASE.md) and [§Async messaging](DECISIONING-ENGINE-USE-CASE.md#async-messaging--txeventq-queues) for the queue inventory and the per-tier scenario matrix.

## 9. Observability model

Four layers, all inspectable from the Backoffice UI:

1. **Per-tool audit** (`decision_audit`) — every `CHAT_WORKFLOW` tool call's input, output, duration, status, ordered by `agent_run_id` + `step_no`. `RESEARCH_WORKFLOW` runs are audited separately so research conversations don't pollute the decisioning trail (`research_audit`).
2. **Append-only decision history** (`decision`) — Oracle Blockchain Table with `NO DROP UNTIL 7 YEARS IDLE`, `NO DELETE LOCKED`, `SHA2_512` hashing. One row per bank decision, written by the Application Service when the reviewer closes the HITL task; carries both the human's final outcome and the original agent recommendation packet. Surface a "tamper attempt rejected by DB" demo path.
3. **Parameter history** (`policy_parameter_history`) — versioned `system_config` edits with reason. Pair with the audit view to interpret a past decision against its then-current parameters.
4. **Replay** — Backoffice can re-run `CHAT_WORKFLOW` against a stored audit input and diff outputs (recommendation packets); reviewers can also replay a research conversation against the same point-in-time snapshot.

## 10. Security boundary

| Concern                                | Mechanism                                                                                                                                                                                                                                          |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Identity at the edge                   | Out of scope for the PoC. UIs ship a mock login picker (customer dropdown on mobile, role dropdown on backoffice) and a logout to swap session; production assumes the host core-banking system provides auth in front of the Application Service. |
| Identity inside the agents             | `AGENT_FACTORY` user owns PAF metadata only; tool execution maps to least-privilege schemas, per agent.                                                                                                                                            |
| NL2SQL guardrail (`CHAT_WORKFLOW`)     | `chat_profile` object list pinned to the customer-safe `REPORTING.*` view set; no access to `decision_audit`, `policy_parameter_history`, or `customer_protected_attrs`.                                                                           |
| NL2SQL guardrail (`RESEARCH_WORKFLOW`) | `research_profile` object list scoped to the broader backoffice `REPORTING.*` view set (full transactions, `decision_audit`, `policy_parameter_history`, deeper `case_history`). Still read-only; no base tables.                                  |
| Side-effects                           | `CHAT_WORKFLOW`'s only side-effect tool is `create_hitl_task`, plus OPA/OCR MCP calls. `RESEARCH_WORKFLOW` is read-only — no write tools, no enqueue. Enforced by `AGENT_TOOLS` grants and by which MCP servers are wired to which flow.           |
| HTTP datasource (Company Registry)     | Read-only by contract — the FastAPI service exposes only `GET` lookups in its OpenAPI spec. Wired to `CHAT_WORKFLOW` only. The service is internal to the VCN; the customer chat UI cannot reach it directly.                                      |
| Decision write                         | Only the Application Service writes the `decision` Blockchain row, on HITL close. Neither agent has `INSERT` on `decision`.                                                                                                                        |
| Agent reachability                     | `CHAT_WORKFLOW` published URL is consumed by the mobile UI only; `RESEARCH_WORKFLOW` published URL is consumed by the backoffice UI only. The Application Service enforces routing — the customer chat path cannot invoke the research agent.      |
| Sensitive attributes                   | `customer_protected_attrs` kept separate; access logged; not passed to either LLM unless explicitly needed (and never to `CHAT_WORKFLOW`).                                                                                                         |
| Audit                                  | Blockchain Table for the decision; standard tables for `decision_audit` and `research_audit` with archive-to-blockchain option.                                                                                                                    |
| Wallet / connection                    | Oracle Wallet for ADB; UCP pool sizing pinned per service.                                                                                                                                                                                         |

## 11. Locked decisions

- **Inference engine**: **vLLM** in a container on a self-hosted GPU host (NVIDIA DGX Spark / GB10 in the PoC), using NVIDIA's Spark-tuned image (`nvcr.io/nvidia/vllm:26.02-py3`). vLLM exposes an **OpenAI-compatible** API on `/v1`; PAF's LLM Management has a first-class **vLLM** provider (separate Host + Port fields).
- **Generative model**: **`Qwen/Qwen2.5-32B-Instruct-AWQ`** served by vLLM. AWQ 4-bit quant (~17 GB resident), native tool-call support via `--tool-call-parser=hermes`, reliable for the 4-tool `CHAT_WORKFLOW` pipeline. Step up to `RedHatAI/Qwen2.5-32B-Instruct-FP8-dynamic` (~32 GB) for higher quality when GPU memory allows. Swap by editing `VLLM_GEN_MODEL` in `.env` and `docker compose down && up -d` on the vLLM stack — no code change needed.
- **Embedding model**: **`BAAI/bge-m3`** at **1024 dimensions** served by vLLM (the pooling task is auto-detected from the HF config). Multilingual (fits the bank-agnostic story); strong retrieval scores on MTEB; usable as the embedding model in Select AI RAG profiles and Oracle AI Vector Search. Locked at deploy time; any change requires re-ingestion of `policy_corpus` and `case_history`. (Per [PAF §6.6](PAF.md#66-embedding-models).)
- **Local database image**: full **Oracle Database Free 26ai** container (not the _-lite_ variant), to keep parity with ADB capabilities (Blockchain Tables, Vector, Select AI).
- **Two agents in PAF, distinct tool scopes.** The platform configures `CHAT_WORKFLOW` (customer-facing, OPA + OCR + Select AI over the customer-safe view set + Company Registry HTTP datasource + `create_hitl_task`) and `RESEARCH_WORKFLOW` (backoffice-only, Select AI over a broader read-only view set + RAG, read-only). Same factory, two security envelopes.
- **Company Registry as PAF HTTP datasource (employer verification).** A small FastAPI service in `src/api/registry/` exposes a synthetic company registry; PAF wires it in as an HTTP data source via its OpenAPI 3.1 spec (`/openapi.json`). One lookup per application during chat (`verify_employer(name)` → `{registered, trading_status, sector, registered_address, last_filed_year}`). Chosen specifically to demonstrate PAF's third data-source type (alongside Database and File); kept deliberately light so it doesn't compete with OPA-via-MCP for "extensively used by the LLM" mindshare. Synthetic JSON-backed data; no real bureau dependency.
- **HITL on every application.** Every successful `CHAT_WORKFLOW` turn ends with `create_hitl_task` carrying the recommendation packet; the human is always the decision-maker. Mandatory human review is the compliance posture by design — it keeps the business in control of every credit decision the bank stands behind. OPA outputs are inputs to the recommendation, not gates on the application.
- **`create_hitl_task` transport — same PL/SQL, two exposure mechanisms.** The function itself (`AGENT_TOOLS.PKG_AGENT_TOOLS.create_hitl_task` — insert into `APP.hitl_task` + enqueue `APP.HITL_REQUEST` atomically) is unchanged across environments. **Cloud (ADB)** exposes it as a **Select AI Tool** wrapping the PL/SQL function and calls it from PAF via the Select AI Bridge node — the canonical in-DB tool channel. **Local (Free 26ai)** can't use Select AI (`provider_endpoint` rejected by `DBMS_CLOUD_AI` pre-flight, see below), so we ship a thin Python MCP wrapper at `src/ai/hitl-mcp/` that calls the same PL/SQL function via `oracledb.callfunc`. Business logic stays in-DB either way; only the transport differs.
- **Three-tier recommendation.** The agent's output is one of `APPROVE` (high confidence, no inconsistencies), `REVIEW` (minor flags, needs human attention), or `DECLINE` (inconsistencies, missing data, compliance hits), accompanied by mandatory `reasoning` (LLM-composed, grounded in OPA outputs and cited policy chunks) and — for `REVIEW` only — `explore_hints` listing areas the reviewer should examine or follow-up data to request from the customer.
- **Final decision on Blockchain, written by the Application Service at HITL close.** When the reviewer submits their decision, the Application Service writes one row to `decision` (Blockchain Table) carrying both the human's outcome and the original agent recommendation packet. One row = one bank decision.
- **`CHAT_WORKFLOW` and `RESEARCH_WORKFLOW` shape**: both are explicit Agent Builder **DAGs** (directed acyclic graphs of nodes — Prompt, Agent, Parser, Condition, Tool, Chat Output — wired together with no cycles, so each run has a well-defined path through the flow). `CHAT_WORKFLOW` is a **two-agent pipeline**: SQL Query + Chat Input → Prompt (Evaluation) → `EvaluationAgent` (gathers evidence, no side effects) → Prompt (Recommendation) → `RecommendationAgent` (one side-effect tool, `create_hitl_task`) → Chat Output. The split keeps each agent's tool surface small and isolates the side effect — see [`paf/flows/CHAT_WORKFLOW.md §Two-agent split`](../paf/flows/CHAT_WORKFLOW.md#two-agent-split). `RESEARCH_WORKFLOW` is intentionally smaller: Prompt → Agent → Chat Output, no side-effect nodes.
- **SQL tooling**: queries against `REPORTING.*` views are exposed as **Select AI In-Database Tools** referenced from PAF flows via the Select AI Bridge node, not as plain SQL Query nodes. (Per [PAF §14.5](PAF.md#145-agent-builder-select-ai-nodes).)
- **OPA bundle reload on parameter change**: planned for **v1**. Currently OPA loads its bundle once at boot; parameter edits in the Backoffice still write `policy_parameter_history` but require an OPA restart to take effect.
- **PAF bootstrap automation**: `manage.py paf bootstrap` prints an ordered checklist of manual UI steps (LLM Management entries, data sources, Select AI profiles, MCP servers, Agent Builder flow imports — `CHAT_WORKFLOW` → `RESEARCH_WORKFLOW`). API automation is added later when the PAF admin endpoints are stable enough to drive headlessly. Playwright-driven UI automation is explicitly out of scope (too fragile across PAF versions).
- **Auth — out of scope; mock login on both UIs.** The audience (host core-banking system) is assumed to provide auth in production, so no SSO/OAuth/JWT/API Gateway is wired into the PoC. The mobile UI shows a dropdown of demo customers (selection sets the active `customer_id`); the backoffice shows a dropdown of roles (HITL reviewer, admin, fair-lending reviewer, risk analyst — which gates visible sections). Both UIs offer logout to swap user or role mid-demo.
- **Async messaging — Oracle Database TxEventQ.** All async/offline work (HITL claim, OCR pipeline, retries, future fan-out) runs through TxEventQ queues owned by `APP`. JSON payloads, single-consumer queues, idempotent DDL (catch `ORA-24006`/`ORA-24010`), per-schema `dbms_aqadm.grant_queue_privilege` rather than `aq_administrator_role`, and a dedicated exception queue for poison messages. Initial inventory: `HITL_REQUEST`, `OCR_REQUEST`, `OCR_EXCEPTION_Q`. Future queues (`NOTIFICATION`, `OPA_BUNDLE_RELOAD`, `FAIR_LENDING_SAMPLING`, `ARCHIVE`) follow the same pattern. See [DECISIONING-ENGINE-USE-CASE.md §Async messaging](DECISIONING-ENGINE-USE-CASE.md#async-messaging--txeventq-queues).
- **Select AI is a cloud / ADB feature in this PoC, not local.** Oracle Database Free 26ai (23.26.x) rejects every custom-endpoint variant of a `DBMS_CLOUD_AI` profile: `provider: ollama` / `openai-compatible` fail validation (`ORA-20046`), `provider: openai` with an HTTP `provider_endpoint` fails (`ORA-20047`), and with an HTTPS `provider_endpoint` (via a Caddy TLS proxy) fails pre-flight (`ORA-20401`) — the request never leaves the DB. Plain `UTL_HTTP` through the same wallet to the same Caddy endpoint succeeds, so the constraint is in `DBMS_CLOUD_AI`'s validator. On ADB the same `CREATE_PROFILE` calls succeed (different release stream; the Caddy TLS layer is unnecessary since ADB endpoints are HTTPS-native and PAF reaches the vLLM endpoint directly on `/v1` over a private VCN). Locally, the `CHAT_WORKFLOW` uses a generic **SQL Query node** with LLM-generated SQL against `REPORTING.chat_v_*` (PAF's LLM Management config calls the vLLM endpoint directly — no Select AI Bridge node in the loop). The Caddy proxy, Oracle SSL wallet, `DBMS_CLOUD` install, and network ACL stay in place because they're useful for any future HTTPS-from-DB work (OCI GenAI when sanctioned, RAG embedding calls, etc.). See [DEPLOYMENT.md §7](DEPLOYMENT.md#7-operational-notes) for the operational detail.

## 12. Decisions not yet locked

- **OCR engine**: PaddleOCR vs Tesseract. Pick during the first OCR smoke test on the synthetic templates; the MCP boundary keeps the choice swappable.
- **HITL assignment policy**: claim-next from `HITL_REQUEST` is the default. Whether to support reviewer-pinned assignment (admin reassigns to a named reviewer) is open; the queue already supports it via `correlation`.
- **Customer-facing rejection explanation depth.** When a HITL task closes with REJECT, the Application Service appends a customer-facing outcome to the chat thread. The depth of that explanation — single dominant signal vs. ranked list, plain language vs. raw reason-code names, which signals are disclosable at all (sanctions / AML hits typically aren't) — is deferred until the end-to-end pipeline is stable. Default plan: surface the top `deny[]` / strongest `DECLINE` signal translated into one customer-actionable sentence, gated by a `system_config` allow-list of disclosable signal kinds.
- **Wallet rotation**: out of scope for the PoC; documented as a follow-up.
