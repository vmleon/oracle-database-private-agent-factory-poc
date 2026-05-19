# Decisioning Engine PoC — Oracle AI Database Private Agent Factory + OPA + RAG

**Audience:** any retail bank evaluating Oracle AI Database 26ai + Private Agent Factory as the agentic platform for credit-application decisioning.
**Demo bank:** generic, region-agnostic. No country, currency, regulator, or bureau is hard-coded.

---

## Core Message

A small, opinionated PoC showing that Oracle AI Database 26ai + Private Agent Factory can run end-to-end credit decisioning with:

- **Observability over determinism** — every decision is reproducible, auditable, replayable. OPA + business logic are kept as deterministic as possible, but the headline is "we can always explain why" not "we are always right".
- **Human-in-the-loop by default** — in any doubt, a human owns the decision. A backoffice **Mandatory-HITL** flag can force 100% of decisions through human review at any time.
- **Configurability over hard-coding** — every threshold, weight, scale, and policy parameter is editable in the backoffice. The same code base supports any country/region by tuning configuration.
- **Tiny tweak → real product** — the PoC is built to demonstrate the path, not the production system. A bank can adopt the pattern and replace components incrementally.

---

## Design Decisions (Consolidated)

| #   | Decision                                                                                            | Why                                                                                        |
| --- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | Bank-agnostic — no country / region / bureau / regulator hard-coded                                 | Demo must be reusable across institutions in different jurisdictions                       |
| 2   | Credit score, DTI/PTI caps, weights, currencies are runtime **configuration**, not literals in code | Same demo, different parameters per audience                                               |
| 3   | Generic data-protection framework (rights + restrictions common to most regimes)                    | Avoids country-specific compliance claims; signals "we know there are obligations"         |
| 4   | OPA chosen — used in banking, open-source, gives full control of policy code                        | No comparison to commercial BRMS; scope is intentionally limited                           |
| 5   | No auto-approve as a default headline                                                               | When in doubt → human. Toggleable hard requirement via backoffice flag                     |
| 6   | Mandatory-HITL flag — global override forces all decisions to HITL queue                            | Audit periods, warm-up, sensitive products, drift suspicion                                |
| 7   | Observability over determinism                                                                      | Deterministic systems can still be wrong; the recoverable failure mode is a complete trail |
| 8   | Append-only decision history on **Oracle Database Blockchain Table**                                | Immutable, queryable, retention-friendly, no extra infra                                   |
| 9   | Region-agnostic deployment — any OCI region, also portable to ExaCC / on-prem 26ai                  | No tenant / region constraint baked in                                                     |
| 10  | Open-source OCR (PaddleOCR / Tesseract) + YOLO for ID-card field detection                          | Lightweight, no external SaaS, demonstrable on a laptop                                    |
| 11  | OCR tiers: usable → HITL with full context; marginal → HITL; unusable → auto-decline                | Don't reject under the radar; don't saturate humans with garbage                           |
| 12  | Fair Lending Review = generalized non-discrimination backoffice process                             | Periodic disparate-impact sampling across configured protected attributes                  |
| 13  | Simplest possible pricing engine — rate card + risk-band adjustment                                 | Approval without a rate is not a decision; keep it minimal                                 |
| 14  | Affordability stress = backoffice Risk Management Dashboard                                         | Portfolio-level shock view, not per-application gating; consistent across banks            |
| 15  | No counter-offer logic                                                                              | Out of scope                                                                               |
| 16  | No effort budget / timeline in this doc                                                             | Not relevant; PoC is delivered when the demo is convincing                                 |
| 17  | Standalone stack — does not depend on, or align with, any concurrent engagement                     | Clean architectural story; one stack, one demo                                             |
| 18  | Customer UI = chat + document upload. Backoffice UI = traditional CRUD + queue + reports            | Two distinct surfaces, two distinct audiences                                              |
| 19  | Test bench is for **functionality + observability**, not performance                                | Cover all decision paths and prove every step is observable                                |

---

## Goals

- Show Oracle AI Database 26ai as **the agentic platform** for credit decisioning: SQL + Vector + Rule engine + LLM + audit, in one place.
- Prove **end-to-end observability** of every decision — replayable from inputs to rationale.
- Demonstrate a **human-first** decisioning posture with a hard regulator-friendly override.
- Map every decision feature, function, dataset, and integration into a single coherent surface a bank can recognize and adopt.

---

## Demo Scenario — Personal Loan Origination

Generic retail bank. Customer applies for a personal loan via a chat UI, uploads supporting documents, receives one of:

- **REJECT** (with documented reason codes, surfaced through the customer channel).
- **REFER TO HUMAN** (most cases when any uncertainty exists; default behavior on doubt).
- **APPROVE** (with a priced offer — rate, term, amount).

A **Mandatory-HITL** toggle in the backoffice routes 100% of cases to human review regardless of OPA result. Off by default; can be flipped at any time.

---

## Architecture

### Flow

1. Customer opens chat UI → submits loan request → uploads documents.
2. **Application Service** persists application + documents (Object Storage), runs cheap **pre-checks** via OPA REST (sanctions, age, doc presence) — short-circuits obvious denies.
3. **OCR + Document Detection** (open-source: YOLO + PaddleOCR/Tesseract) extracts structured fields and produces per-field confidence; composite **document-quality tier** (usable / marginal / unusable) drives downstream behavior.
4. **Decisioning Agent** (Private Agent Factory inside 26ai) orchestrates tool calls:
   - SQL (Select AI) → customer profile, transactions, credit bureau, existing facilities.
   - OPA MCP tools → eligibility, AML, KYC, escalation, fair-lending hooks.
   - Vector Search → policy citations, similar cases.
   - Pricing tool → rate card lookup + risk-band adjustment.
5. Composite **confidence score** computed from configurable weights (OCR quality + data completeness + policy proximity).
6. Outcome decided by OPA + confidence + Mandatory-HITL flag.
7. **Decision** persisted to a Blockchain Table (append-only). Full audit trail (per tool call) persisted in `decision_audit`.
8. If REFER_HUMAN, application appears in the **backoffice HITL queue** for a bank employee.
9. Customer status surfaces back through the chat UI with reason codes (no decision detail leak).

### Component Map

| Component           | Tech                                                                             | Role                                                                     |
| ------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Customer Chat UI    | Web app (React / Next / similar)                                                 | Chat-style request flow + document upload                                |
| Backoffice UI       | Web app (React / Next / similar)                                                 | CRUD, HITL queue, rule editor, reports, dashboards, parameter management |
| API Gateway         | OCI API Gateway                                                                  | Auth, throttling, request validation                                     |
| Application Service | Spring Boot (Java) stub                                                          | App CRUD, document upload, pre-checks, agent invocation                  |
| Object Storage      | OCI Object Storage                                                               | Uploaded document PDFs / images                                          |
| OCR + Detection     | YOLO (field detection) + PaddleOCR/Tesseract                                     | Open-source extraction; composite confidence tiering                     |
| Decisioning Agent   | Oracle Private Agent Factory (Select AI Agent) in ADB                            | Tool-calling agent                                                       |
| Data plane          | Oracle AI Database 26ai                                                          | All banking data; RLS/VPD enforced at the DB layer                       |
| Vector store        | Oracle AI Vector Search (same 26ai)                                              | `policy_corpus` + `case_history` embeddings                              |
| LLM + embeddings    | OCI Generative AI (model-agnostic — pick what's sanctioned in the target region) | Reasoning + rationale + embeddings                                       |
| Rule engine         | OPA + OPA MCP server (Python FastMCP wrapper)                                    | Eligibility, AML, KYC, escalation, fair-lending rules in Rego            |
| Decision history    | Oracle Database Blockchain Table                                                 | Append-only credit-decision audit; retention-friendly                    |
| HITL surface        | Backoffice UI (queue + decision form)                                            | Bank employee picks up, reviews evidence, decides                        |

---

## Data Model — Synthetic but Realistic

The synthetic dataset is generated to **trigger every decision path** rather than to validate a model. It is intentionally constructed so test-bench scenarios exercise the system end-to-end.

### Entities

| Table                       | Purpose                                                                   |
| --------------------------- | ------------------------------------------------------------------------- |
| `customer`                  | Customer master                                                           |
| `customer_address`          | Current + historical addresses                                            |
| `customer_identity`         | ID / passport docs with expiry                                            |
| `customer_protected_attrs`  | Protected attributes for fair-lending review (configurable per region)    |
| `employment`                | Employers, salary, tenure                                                 |
| `account`                   | Customer accounts (current, savings)                                      |
| `account_transaction`       | Transaction history (12 months) — cashflow source                         |
| `credit_bureau_snapshot`    | Periodic external score + bureau facilities; **scale parameterized**      |
| `existing_facility`         | Loans/cards held elsewhere                                                |
| `product_catalog`           | Loan/card/mortgage products + amount/term ranges                          |
| `rate_card`                 | Pricing per product + risk band                                           |
| `loan_application`          | The application being decisioned                                          |
| `loan_application_document` | Uploaded docs + OCR-extracted JSON + quality tier                         |
| `decision` _(blockchain)_   | Append-only decision history                                              |
| `decision_audit`            | Step-by-step tool-call trail (inputs, outputs, durations)                 |
| `hitl_task`                 | HITL queue entry, state, assignment                                       |
| `policy_corpus`             | Policy chunks + embeddings (for RAG)                                      |
| `case_history`              | Past anonymized decisions for similarity retrieval                        |
| `sanctions_list`            | Synthetic sanctions / PEP list                                            |
| `system_config`             | Tunable parameters (caps, thresholds, weights, Mandatory-HITL flag, etc.) |
| `policy_parameter_history`  | Versioned changes to `system_config` (who changed what, when, why)        |
| `fair_lending_review`       | Periodic disparate-impact sampling + bank reviewer notes                  |

### Schema sketch (key tables)

```sql
CREATE TABLE customer (
  customer_id     NUMBER PRIMARY KEY,
  full_name       VARCHAR2(200),
  date_of_birth   DATE,
  residency       VARCHAR2(64),
  email           VARCHAR2(200),
  phone           VARCHAR2(40),
  kyc_status      VARCHAR2(20) CHECK (kyc_status IN ('PENDING','PASSED','FAILED')),
  kyc_updated_at  TIMESTAMP,
  created_at      TIMESTAMP
);

CREATE TABLE customer_protected_attrs (
  customer_id  NUMBER PRIMARY KEY REFERENCES customer,
  attrs        JSON   -- configurable per region: {"age_band":"30-39","gender":"F",...}
);

CREATE TABLE credit_bureau_snapshot (
  snapshot_id            NUMBER PRIMARY KEY,
  customer_id            NUMBER REFERENCES customer,
  snapshot_date          DATE,
  score                  NUMBER,
  score_scale_min        NUMBER,        -- parameterized
  score_scale_max        NUMBER,        -- parameterized
  bureau_name            VARCHAR2(80),  -- free text, no hard-coded bureau
  total_debt             NUMBER(14,2),
  num_open_facilities    NUMBER,
  num_late_payments_12m  NUMBER
);

CREATE TABLE product_catalog (
  product_id        NUMBER PRIMARY KEY,
  name              VARCHAR2(200),
  product_type      VARCHAR2(20),
  pricing_model     VARCHAR2(20),       -- INTEREST / FEE / PROFIT_SHARE (generic)
  min_amount        NUMBER(14,2),
  max_amount        NUMBER(14,2),
  min_term_months   NUMBER,
  max_term_months   NUMBER,
  currency          VARCHAR2(3)         -- generic ISO code; not hard-coded
);

CREATE TABLE rate_card (
  rate_card_id     NUMBER PRIMARY KEY,
  product_id       NUMBER REFERENCES product_catalog,
  risk_band        VARCHAR2(20),        -- LOW / MID / HIGH (configurable bands)
  rate_value       NUMBER(7,4),         -- meaning interpreted by pricing_model
  effective_from   DATE,
  effective_to     DATE
);

CREATE TABLE loan_application (
  application_id    NUMBER PRIMARY KEY,
  customer_id       NUMBER REFERENCES customer,
  product_id        NUMBER REFERENCES product_catalog,
  amount_requested  NUMBER(14,2),
  term_months       NUMBER,
  purpose           VARCHAR2(200),
  channel           VARCHAR2(20),
  status            VARCHAR2(20),
  submitted_at      TIMESTAMP,
  decided_at        TIMESTAMP
);

CREATE TABLE loan_application_document (
  doc_id          NUMBER PRIMARY KEY,
  application_id  NUMBER REFERENCES loan_application,
  doc_type        VARCHAR2(40),       -- generic: ID / INCOME_PROOF / ADDRESS_PROOF / BANK_STATEMENT / OTHER
  storage_uri     VARCHAR2(500),
  uploaded_at     TIMESTAMP,
  ocr_status      VARCHAR2(20),
  ocr_payload     JSON,
  ocr_confidence  NUMBER(5,4),
  quality_tier    VARCHAR2(20)        -- USABLE / MARGINAL / UNUSABLE
);

-- Append-only decision history (Oracle Blockchain Table)
CREATE BLOCKCHAIN TABLE decision (
  decision_id        NUMBER,
  application_id     NUMBER,
  outcome            VARCHAR2(20),    -- APPROVE / REJECT / REFER_HUMAN
  confidence         NUMBER(5,4),
  rationale          CLOB,
  opa_result         JSON,
  rag_citations      JSON,
  pricing_offer      JSON,            -- {rate, term, amount, expiry}
  reason_codes       JSON,            -- enumerated codes for customer disclosure
  computed_dti       NUMBER(5,2),
  computed_pti       NUMBER(5,2),
  mandatory_hitl     CHAR(1),         -- Y/N (was flag on at decision time?)
  decided_at         TIMESTAMP,
  agent_run_id       VARCHAR2(60)
) NO DROP UNTIL 7 YEARS IDLE
  NO DELETE LOCKED
  HASHING USING "SHA2_512" VERSION "v1";

CREATE TABLE decision_audit (
  audit_id      NUMBER PRIMARY KEY,
  agent_run_id  VARCHAR2(60),
  step_no       NUMBER,
  tool_name     VARCHAR2(80),
  tool_input    JSON,
  tool_output   JSON,
  started_at    TIMESTAMP,
  ended_at      TIMESTAMP,
  duration_ms   NUMBER,
  status        VARCHAR2(20)
);

CREATE TABLE hitl_task (
  task_id         NUMBER PRIMARY KEY,
  application_id  NUMBER REFERENCES loan_application,
  assigned_to     VARCHAR2(120),
  state           VARCHAR2(20),       -- OPEN / IN_REVIEW / APPROVED / REJECTED / EXPIRED
  reason_for_hitl VARCHAR2(200),      -- mandatory_flag / opa_warn / low_confidence / oc r_marginal / amount_over_threshold / fair_lending_flag
  decision_note   CLOB,
  created_at      TIMESTAMP,
  closed_at       TIMESTAMP
);

CREATE TABLE policy_corpus (
  chunk_id     NUMBER PRIMARY KEY,
  source_doc   VARCHAR2(300),
  section_ref  VARCHAR2(60),
  text         CLOB,
  embedding    VECTOR(1024, FLOAT32)
);

CREATE TABLE case_history (
  case_id         NUMBER PRIMARY KEY,
  amount          NUMBER(14,2),
  term_months     NUMBER,
  dti             NUMBER(5,2),
  pti             NUMBER(5,2),
  credit_score    NUMBER,
  outcome         VARCHAR2(20),
  outcome_reason  CLOB,
  case_embedding  VECTOR(1024, FLOAT32)
);

CREATE TABLE system_config (
  config_key    VARCHAR2(80) PRIMARY KEY,
  config_value  VARCHAR2(400),
  value_type    VARCHAR2(20),       -- NUMBER / STRING / BOOLEAN / JSON
  description   VARCHAR2(400),
  updated_at    TIMESTAMP,
  updated_by    VARCHAR2(120)
);

CREATE TABLE policy_parameter_history (
  hist_id       NUMBER PRIMARY KEY,
  config_key    VARCHAR2(80),
  old_value     VARCHAR2(400),
  new_value     VARCHAR2(400),
  changed_at    TIMESTAMP,
  changed_by    VARCHAR2(120),
  change_reason VARCHAR2(400)
);

CREATE TABLE fair_lending_review (
  review_id           NUMBER PRIMARY KEY,
  period_from         DATE,
  period_to           DATE,
  bucketing           JSON,            -- {"age_band":[...], "gender":[...],...}
  disparate_impact    JSON,            -- per-bucket approval rate vs reference
  flagged_decisions   JSON,            -- decision_ids over threshold
  reviewer            VARCHAR2(120),
  conclusion          CLOB,
  reviewed_at         TIMESTAMP
);
```

### Relationships (cardinality)

```
customer (1) ──< (N) customer_identity
customer (1) ── (1) customer_protected_attrs
customer (1) ──< (N) customer_address
customer (1) ──< (N) employment
customer (1) ──< (N) account ──< (N) account_transaction
customer (1) ──< (N) credit_bureau_snapshot
customer (1) ──< (N) existing_facility
customer (1) ──< (N) loan_application
product_catalog (1) ──< (N) loan_application
product_catalog (1) ──< (N) rate_card
loan_application (1) ──< (N) loan_application_document
loan_application (1) ──── (1) decision   -- blockchain table, append-only
decision (1) ──< (N) decision_audit       -- joined via agent_run_id
loan_application (1) ──── (0..1) hitl_task
system_config (1) ──< (N) policy_parameter_history
```

### Synthetic dataset — built to exercise paths, not to mimic a real bank

Volumes calibrated to the test bench, not statistical realism:

- ~2,000 customers spanning configurable risk bands.
- 1–3 accounts per customer; ~12 months of transaction history; salary credits + recurring outflows + variability.
- ~1,000 loan applications mapped 1:1 to test-bench scenarios (see below).
- ~50 ID/payslip/statement/address-proof PDF templates at three quality tiers (clean, marginal, unusable).
- ~150 policy chunks (generic lending policy, generic AML guidance, generic fair-lending guidance).
- ~500 case-history rows for similarity retrieval.
- ~50 synthetic sanctions / PEP entries.

**No circular logic** — risk-band labels are used to generate plausible features (income, score, NSF count, document quality), then _forgotten_. The agent operates only on observable features, not on the label. This way the demo path is engineered, but the agent does real work given the inputs.

---

## OPA — Rule Engine

### Why OPA (one paragraph, no comparison)

OPA is used in production banking, is open-source, and gives full control over policy code. Within the limited scope of this PoC, that is enough. Production institutions can re-evaluate against any BRMS later — OPA is exposed through MCP, so the agent contract doesn't change if the engine is swapped.

### Policy packages

```
packages/
├── eligibility.rego         # age, residency, income, DTI, PTI, score floor (all parameterized)
├── aml.rego                 # sanctions / PEP / suspicious pattern flags
├── kyc.rego                 # ID validity, doc expiry, quality-tier gates
├── product.rego             # product-specific amount/term caps
├── escalation.rego          # routing rules: when to REFER_HUMAN
├── fair_lending.rego        # disparate-impact pre-flight on a single decision
└── pricing.rego             # risk-band mapping for rate-card lookup
```

### Example — `eligibility.rego` (parameterized)

```rego
package decisioning.eligibility

import future.keywords.in

# Parameters arrive as data.config — sourced from system_config + policy_parameter_history.

default allow := false

deny[msg] {
  input.applicant.age < data.config.min_age
  msg := sprintf("Applicant under minimum age (%v)", [data.config.min_age])
}

deny[msg] {
  input.applicant.dti > data.config.dti_hard_cap
  msg := sprintf("DTI %.2f exceeds cap %.2f", [input.applicant.dti, data.config.dti_hard_cap])
}

deny[msg] {
  input.applicant.pti > data.config.pti_hard_cap
  msg := sprintf("PTI %.2f exceeds cap %.2f", [input.applicant.pti, data.config.pti_hard_cap])
}

deny[msg] {
  input.applicant.credit_score < data.config.score_floor
  msg := sprintf("Credit score below configured floor (%v)", [data.config.score_floor])
}

warn[msg] {
  input.applicant.credit_score >= data.config.score_floor
  input.applicant.credit_score < data.config.score_caution_band_upper
  msg := "Credit score in caution band: manual review"
}

warn[msg] {
  input.application.amount > data.config.auto_approve_amount_cap
  msg := sprintf("Amount above auto-approve threshold (%v): manual review", [data.config.auto_approve_amount_cap])
}

allow {
  not deny[_]
  not warn[_]
}
```

`data.config` is loaded from `system_config` at OPA startup (or via OPA bundle refresh). Backoffice edits to `system_config` write a row to `policy_parameter_history` and trigger an OPA bundle reload.

### OPA via MCP

- **OPA MCP server** wraps OPA's `/v1/data/...` HTTP endpoints as typed MCP tools.
- Tools exposed to the agent:
  - `evaluate_eligibility(applicant, application, product)` → `{ allow, deny[], warn[] }`
  - `evaluate_aml(customer, application)` → `{ allow, deny[] }`
  - `evaluate_kyc(documents, quality_tiers)` → `{ allow, deny[] }`
  - `evaluate_escalation(decision_inputs)` → `{ refer_human, reason }`
  - `evaluate_fair_lending_flags(customer_attrs, decision_draft)` → `{ flag, reason }`
  - `lookup_pricing(applicant, application)` → `{ risk_band, rate_value, fee_schedule }`
  - `list_policy_versions()` → version metadata for audit

- **Application Service** also calls OPA over REST for cheap pre-checks (sanctions, age, doc presence) — never bothers the agent with hopeless cases.

---

## RAG

### Corpus

- **`policy_corpus`** — generic lending policy, generic AML guidance, generic fair-lending policy, product policy. Region-neutral phrasing.
- **`case_history`** — anonymized past decisions for similarity retrieval.

### Embedding model

OCI Generative AI embeddings — model chosen at deploy time based on what is sanctioned in the target region. No hard-coded vendor.

### Retrieval

- **Policy retrieval** — `search_policy(reasons)` → top-N policy chunks → cited in rationale.
- **Case retrieval** — `search_similar_cases(applicant features)` → top-N similar past cases → anchor in rationale.
- **Hybrid retrieval** — vector + SQL filter (e.g., `product_type = 'PERSONAL_LOAN'`) for precision.

### What RAG is NOT used for

Not for the decision itself — that's OPA. RAG grounds the rationale text and answers ad-hoc bank-agent questions in the backoffice UI ("what does the lending policy say about X?").

---

## OCR + Document Quality Tiering

### Pipeline

1. **YOLO** — detects regions on the uploaded image / PDF (ID front, ID back, MRZ, photo area, document edges, payslip header, statement table). Open-source weights, fine-tuned on a small synthetic set of mock IDs and payslips.
2. **OCR engine** — open-source (PaddleOCR or Tesseract — pick whichever localizes better for the demo). Extracts text from each detected region.
3. **Per-field confidence** — composite from YOLO detection score + OCR per-character confidence + structural sanity checks (date parses, ID format matches the expected pattern, MRZ checksum where applicable).
4. **Document quality tier** — composite:
   - `USABLE` — every required field detected with per-field confidence ≥ configured threshold.
   - `MARGINAL` — one or more fields below threshold but image is human-readable.
   - `UNUSABLE` — image too dark / blurred / cropped / not-an-ID.

### Behavior by tier

| Tier     | System behavior                                                                                                                     |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| USABLE   | Feed extracted fields to agent; continue decisioning. If everything else is clean and confidence is high, agent may auto-approve.   |
| MARGINAL | Route to **HITL** with the full original document, OCR output, and confidence map. **Do not silently reject.** Human picks up.      |
| UNUSABLE | Auto-decline with a customer-facing reason ("please re-upload — image was not readable"). Don't saturate humans on garbage uploads. |

Thresholds (`USABLE_min_confidence`, `MARGINAL_floor`) are in `system_config` and editable from the backoffice.

---

## Decisioning Agent — Private Agent Factory

### Agent definition (pseudo-DDL)

```sql
BEGIN
  DBMS_CLOUD_AI.CREATE_AGENT(
    agent_name   => 'DECISIONING_AGENT',
    description  => 'Loan-application decisioning, region-agnostic',
    model        => '<sanctioned-model-in-target-region>',
    instructions => '... see prompt below ...',
    tools        => 'SQL_TOOL, VECTOR_SEARCH_TOOL, OPA_MCP_TOOL,
                     DOC_EXTRACT_TOOL, PRICING_TOOL, HITL_TOOL, AUDIT_TOOL'
  );
END;
```

### Tools

| Tool                          | Type                     | Bound to                                                  | Purpose                                              |
| ----------------------------- | ------------------------ | --------------------------------------------------------- | ---------------------------------------------------- |
| `query_customer_profile`      | SQL (Select AI / NL2SQL) | View over `customer` + `employment` + `existing_facility` | Pull profile, compute DTI / PTI                      |
| `query_transaction_summary`   | SQL (Select AI)          | View over `account_transaction`                           | Cashflow aggregates                                  |
| `query_credit_bureau`         | SQL                      | `credit_bureau_snapshot`                                  | Latest snapshot per customer                         |
| `search_policy`               | Vector Search            | `policy_corpus`                                           | RAG over policy text                                 |
| `search_similar_cases`        | Vector Search            | `case_history`                                            | Similarity over past decisions                       |
| `extract_document`            | Function tool            | OCR + YOLO pipeline                                       | Extract fields + per-field confidence + quality tier |
| `evaluate_eligibility`        | MCP                      | OPA MCP server                                            | Eligibility rules                                    |
| `evaluate_aml`                | MCP                      | OPA MCP server                                            | AML rules                                            |
| `evaluate_kyc`                | MCP                      | OPA MCP server                                            | KYC + doc validity + quality gates                   |
| `evaluate_fair_lending_flags` | MCP                      | OPA MCP server                                            | Pre-flight fairness flag on a single decision        |
| `evaluate_escalation`         | MCP                      | OPA MCP server                                            | Routing rule (REFER_HUMAN)                           |
| `lookup_pricing`              | SQL + OPA                | `rate_card` + OPA pricing                                 | Map risk band → rate                                 |
| `create_hitl_task`            | Function tool            | `hitl_task`                                               | Open backoffice review task                          |
| `record_decision`             | SQL                      | `decision` (blockchain) + `decision_audit`                | Persist outcome + per-tool audit trail               |

### Agent instructions (sketch)

```
You are the Decisioning Agent for retail loan applications. Your role is to evaluate
a submitted application and produce one of three outcomes: APPROVE, REJECT, or
REFER_HUMAN.

HARD RULES:
- You do not decide based on your own reasoning. Decisions are derived from OPA tool
  outputs and configured thresholds. Your text only composes the rationale and chooses
  which tools to call.
- Read system_config.mandatory_hitl first. If true, outcome is always REFER_HUMAN —
  call OPA tools anyway (so the audit captures rule outputs) but produce REFER_HUMAN.
- Always call evaluate_kyc, evaluate_aml, evaluate_eligibility, evaluate_fair_lending_flags.
- If any OPA tool returns deny[], outcome = REJECT.
- If any tool returns warn[], or confidence < configured auto-approve threshold,
  or amount > configured auto-approve cap, or any document quality_tier is MARGINAL,
  or fair-lending flag is raised — outcome = REFER_HUMAN.
- Otherwise outcome = APPROVE; call lookup_pricing for the offer.
- Cite policy chunks via search_policy. Never invent citations.
- Persist via record_decision before returning. Audit must be complete.

WORKFLOW:
1. Read system_config (mandatory_hitl, thresholds).
2. Pull customer profile, transactions, credit bureau via SQL tools.
3. For each uploaded document, call extract_document; capture quality_tier.
4. Compute applicant payload (age, DTI, PTI, score, employment tenure).
5. Call OPA: evaluate_kyc → evaluate_aml → evaluate_eligibility → evaluate_fair_lending_flags.
6. Call evaluate_escalation with the combined inputs + confidence.
7. If outcome = APPROVE, call lookup_pricing.
8. Call search_policy on reasons; search_similar_cases on applicant features.
9. Compose rationale with citations and reason codes.
10. If REFER_HUMAN, call create_hitl_task with the full payload + reason_for_hitl.
11. Call record_decision.
```

### Per-decision tool-call sequence

```
1.  read system_config.mandatory_hitl + thresholds
2.  query_customer_profile(customer_id)
3.  query_transaction_summary(customer_id, months=12)
4.  query_credit_bureau(customer_id)
5.  extract_document(doc_id) × N
6.  evaluate_kyc({ documents, quality_tiers })
7.  evaluate_aml({ customer, application })
8.  evaluate_eligibility({ applicant, application, product })
9.  evaluate_fair_lending_flags({ protected_attrs, decision_draft })
10. evaluate_escalation({ ...all + confidence })
11. [if APPROVE candidate] lookup_pricing({ applicant, application })
12. search_policy(deny + warn reasons)
13. search_similar_cases(applicant features)
14. record_decision(...)                  -- writes to blockchain decision + decision_audit
15. [if REFER_HUMAN] create_hitl_task(payload, reason_for_hitl)
```

### Confidence score (configurable)

Composite of weighted components. **All weights live in `system_config`** and are editable from the backoffice:

```
confidence = w1 × min(per_doc_quality_score)
           + w2 × data_completeness_ratio
           + w3 × policy_proximity_score
```

Default weights set to reasonable values for the demo; backoffice operators tune for their context. Confidence is one signal; OPA `warn[]`, document tier, and mandatory-HITL flag all also gate the auto-approve path.

---

## Observability (the headline)

Every decision is reproducible from the audit trail alone. The four observability layers:

1. **Per-tool audit** — `decision_audit` captures every tool call (input, output, duration, status). Replayable.
2. **Append-only decision history** — `decision` is an **Oracle Database Blockchain Table** (`NO DROP UNTIL 7 YEARS IDLE`, `NO DELETE LOCKED`, `SHA2_512` hashing). No row can be modified or deleted; retention is enforced at the DB layer.
3. **Parameter history** — `policy_parameter_history` records every threshold/weight change with reason, timestamp, operator. A decision made yesterday is interpretable against yesterday's parameters, not today's.
4. **Tool-call replay view** — backoffice UI surfaces the full decision trail for any application in chronological order; bank agents can re-run the same agent against the same audit input to verify reproducibility.

> A deterministic system can still be wrong. The recoverable failure mode is a complete trail.

---

## Pricing Engine (simplest possible)

- `product_catalog` defines the product (amount range, term range, currency, pricing model).
- `rate_card` defines `rate_value` per `(product_id, risk_band)`.
- OPA `evaluate_eligibility` produces a `risk_band` (LOW / MID / HIGH, configurable buckets) based on score + DTI.
- Agent calls `lookup_pricing` → returns `{ rate_value, term, amount, expiry }` to the customer.

No rate optimization, no segmented yield models, no multi-product bundling. Approval without a rate isn't a decision; this is the minimal viable rate engine.

---

## Risk Management Dashboard (in Backoffice)

A backoffice dashboard, not a per-application gate. Built once, useful in any banking context:

- **Portfolio view** — sum of approved exposure by product, risk band, channel.
- **Stress scenarios** — recompute portfolio aggregates under configurable shocks:
  - Rate shock: +200 bps, +400 bps
  - Income shock: -10%, -20%
  - Combined
- **Pressure surfaces** — count of accounts whose post-stress DTI breaches the configured cap. Drill-down to specific applications.
- **Threshold suggestions** — what would the approval rate look like if `score_floor` rose by 20 points? If `dti_hard_cap` tightened by 5 points? Counterfactual view.
- **Decision drift** — approval rate, average rate, average DTI, average score, by week/month. Triggers a review if drift exceeds configured bounds.

Same dashboard works across regions because the data model is generic and the parameters are configurable.

---

## Fair-Lending Review (generalized non-discrimination process)

ECOA is US-specific. Most jurisdictions have an analogue (EU equal-treatment directives, UK Equality Act, etc.). The principle is universal: credit decisions should not produce disparate impact across protected attributes. Generalized as a **backoffice process**:

1. **Configure** which attributes are "protected" for this institution (stored on `customer_protected_attrs.attrs`). The PoC ships with `age_band`, `gender`, `nationality` — banks switch them on/off per their regime.
2. **Periodic sampling** — scheduled job buckets decisions by protected attributes, computes approval rate per bucket vs the overall rate, and writes `fair_lending_review` rows.
3. **Disparate-impact flags** — buckets whose approval rate falls below a configured ratio (default 0.80, the US "4/5 rule" as a reasonable default — adjustable) are flagged for review.
4. **Per-decision pre-flight** — `evaluate_fair_lending_flags` is called on every individual decision and surfaces a flag if the case fits a pattern the institution has chosen to monitor.
5. **Review queue** — flagged samples appear in the backoffice for a reviewer; review notes + conclusion persisted on `fair_lending_review`.

Nothing here claims compliance with any specific regulator. The point is the **operational pattern** is implemented and visible — every bank can map it to their own regulator.

---

## Data-Protection Framework (region-agnostic baseline)

A baseline most banks will recognize regardless of region:

| Concern              | Implementation                                                                                                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Purpose limitation   | All tables tagged with a `purpose` policy in `system_config`; the agent rejects tool calls outside the registered purposes.                                                               |
| Data minimization    | Select AI tools target **views**, not raw tables. Views expose only fields needed for the decision.                                                                                       |
| Access control       | RLS / VPD on `customer_id`. Backoffice users have role-scoped views.                                                                                                                      |
| Sensitive attributes | `customer_protected_attrs` separated from `customer`; access logged separately; never sent to the LLM unless explicitly needed.                                                           |
| Retention            | `decision` is a Blockchain Table with `NO DROP UNTIL 7 YEARS IDLE` (configurable). Other tables follow policy-driven retention jobs.                                                      |
| Right of explanation | Every decision has reason codes + replayable audit trail. The bank can produce a customer-facing explanation from the trail.                                                              |
| Append-only audit    | Blockchain Tables for `decision`; standard tables for `decision_audit` (with archive-to-blockchain option configurable).                                                                  |
| Data portability     | Customer record export job in backoffice — JSON dump per customer, signed.                                                                                                                |
| Erasure              | Configurable in backoffice: which fields are eraseable on customer request and which are retained under legal-hold (e.g., the blockchain decision is not erased; supporting docs may be). |
| Region-agnostic      | All of the above implemented as configuration. No region pinned in the code.                                                                                                              |

---

## API Surface

### Customer-facing API (Application Service)

| Method | Path                              | Purpose                                                  |
| ------ | --------------------------------- | -------------------------------------------------------- |
| POST   | `/v1/applications`                | Create draft application                                 |
| POST   | `/v1/applications/{id}/documents` | Upload doc (multipart → Object Storage → queue OCR)      |
| POST   | `/v1/applications/{id}/submit`    | Submit; triggers Decisioning Agent                       |
| GET    | `/v1/applications/{id}`           | Status + sanitized decision view                         |
| POST   | `/v1/applications/{id}/chat`      | Conversational interface — clarifications, doc re-upload |

### Backoffice API

| Method | Path                                    | Purpose                                                       |
| ------ | --------------------------------------- | ------------------------------------------------------------- |
| GET    | `/v1/hitl/tasks?assignee=me&state=open` | HITL queue                                                    |
| GET    | `/v1/hitl/tasks/{id}`                   | Full application + audit + documents + agent rationale        |
| POST   | `/v1/hitl/tasks/{id}/decision`          | Submit human decision + note → closes task → updates decision |
| GET    | `/v1/config`                            | Read all `system_config` entries                              |
| PUT    | `/v1/config/{key}`                      | Update a parameter (writes `policy_parameter_history`)        |
| GET    | `/v1/rules`                             | List OPA policy versions                                      |
| GET    | `/v1/dashboard/risk`                    | Risk Management Dashboard data                                |
| GET    | `/v1/dashboard/fair-lending`            | Fair-lending review data                                      |
| POST   | `/v1/dashboard/fair-lending/review`     | Submit a fair-lending review                                  |
| GET    | `/v1/audit/{decision_id}`               | Full replayable decision audit                                |
| POST   | `/v1/audit/{decision_id}/replay`        | Re-run agent against the stored audit input, compare output   |

---

## UI Surfaces

### Customer UI — chat with document upload

- Chat-style interface ("Hi, what loan are you looking for?"); agent asks structured follow-ups.
- Document upload widget; in-line preview; per-document status (queued → extracting → ok / marginal / unusable).
- If marginal/unusable, customer is told what is wrong and asked to re-upload (avoids silent rejection).
- Decision delivered conversationally:
  - APPROVE → priced offer with accept/decline buttons.
  - REJECT → reason codes + plain-language explanation.
  - REFER_HUMAN → "your application is being reviewed; we'll get back within X" + status tracking.

### Backoffice UI — traditional CRUD + queue + dashboards

Sections:

- **HITL Queue** — open tasks; filters by reason (mandatory_flag / opa_warn / low_confidence / ocr_marginal / amount_over_threshold / fair_lending_flag); claim, review, decide. Shows agent rationale + full audit + original documents.
- **Decisions** — search/browse all decisions; click into the audit trail; replay.
- **Rule Management** — list OPA policies, view current Rego, version metadata. (Editing in-place is out of scope for the PoC; surface read-only.)
- **Parameter Management** — edit `system_config` entries (thresholds, weights, the **Mandatory-HITL master switch**, OCR tier thresholds, fair-lending bucketing). Every change writes `policy_parameter_history`.
- **Risk Management Dashboard** — see Risk Management section above.
- **Fair-Lending Review** — periodic reviews, flagged samples, reviewer notes.
- **Reports** — approval rate, refer rate, reject rate by week/month, by product, by channel. Decision drift alerts.
- **Customer Search** — find a customer, see their applications, decisions, audit.

---

## Test Bench

The test bench is for **functionality and observability**, not performance. Each scenario asserts:

- (a) the correct outcome,
- (b) the correct reason codes,
- (c) every expected tool call appears in the audit,
- (d) the decision is replayable, and
- (e) the blockchain row is intact.

### Scenarios

| #   | Scenario                                              | Expected outcome                                        | Why this case matters                                                                           |
| --- | ----------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1   | Clean profile, low DTI, high score, all docs USABLE   | APPROVE                                                 | Happy path — proves the auto-approve route is wired                                             |
| 2   | DTI above hard cap                                    | REJECT                                                  | OPA hard deny path; rationale cites eligibility chunk                                           |
| 3   | Score below configured floor                          | REJECT                                                  | OPA hard deny path; parameterized floor                                                         |
| 4   | Expired ID document                                   | REJECT                                                  | KYC deny; reason code surfaced to customer                                                      |
| 5   | Sanctions hit on AML                                  | REJECT                                                  | AML deny; cheap pre-check short-circuit (agent not invoked)                                     |
| 6   | Mid-band score                                        | REFER_HUMAN                                             | OPA `warn[]`; HITL with full context                                                            |
| 7   | Amount above auto-approve cap                         | REFER_HUMAN                                             | OPA `warn[]`; HITL                                                                              |
| 8   | One document MARGINAL quality                         | REFER_HUMAN                                             | OCR tier → HITL with original doc + extraction map                                              |
| 9   | All documents UNUSABLE                                | REJECT (silent)                                         | Auto-decline path with "please re-upload" customer message                                      |
| 10  | Mandatory-HITL flag is ON                             | REFER_HUMAN                                             | Regardless of clean profile, mandatory flag routes to human; audit captures rule outputs anyway |
| 11  | Fair-lending pre-flight flag raised                   | REFER_HUMAN                                             | Bank reviewer steps in before automated decision lands                                          |
| 12  | Configuration changed mid-flight (DTI cap tightened)  | Outcome shifts on rerun                                 | Parameter history visible; both old and new audits readable                                     |
| 13  | Audit replay matches original decision                | Reproducible                                            | Observability headline — same input, same audit, same outcome                                   |
| 14  | Blockchain row tamper attempt rejected by DB          | Tamper detected                                         | Blockchain integrity demonstration                                                              |
| 15  | Customer asks the agent "why was I declined?" in chat | Agent answers from `decision.rationale` + policy chunks | Right-of-explanation surface                                                                    |

---

## Feature → Function → Data → Integration Map

| Feature                 | Agent function / tool                              | Data                                                                       | Integration               |
| ----------------------- | -------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------- |
| Submit application      | `record_decision`, orchestration                   | `loan_application`                                                         | API → App Service → Agent |
| Upload document         | `extract_document` (YOLO + OCR)                    | `loan_application_document`, Object Storage                                | OCR pipeline (sidecar)    |
| Eligibility evaluation  | `evaluate_eligibility` (MCP)                       | view(applicant, application, product), `system_config`                     | OPA MCP                   |
| AML screening           | `evaluate_aml` (MCP)                               | `customer`, `sanctions_list`                                               | OPA MCP                   |
| KYC validation          | `evaluate_kyc` (MCP)                               | `loan_application_document.ocr_payload`, `customer_identity`, quality_tier | OPA MCP                   |
| DTI / PTI / cashflow    | `query_transaction_summary`, `query_credit_bureau` | `account_transaction`, `existing_facility`, `credit_bureau_snapshot`       | Select AI NL2SQL          |
| Policy citations        | `search_policy`                                    | `policy_corpus` (vector)                                                   | Oracle AI Vector Search   |
| Similar past cases      | `search_similar_cases`                             | `case_history` (vector)                                                    | Oracle AI Vector Search   |
| Pricing                 | `lookup_pricing`                                   | `rate_card`, `product_catalog`                                             | SQL + OPA                 |
| Refer-to-human routing  | `evaluate_escalation` + `create_hitl_task`         | `hitl_task`                                                                | OPA MCP + DB              |
| Mandatory-HITL override | agent reads `system_config.mandatory_hitl`         | `system_config`                                                            | DB                        |
| Fair-lending pre-flight | `evaluate_fair_lending_flags`                      | `customer_protected_attrs`                                                 | OPA MCP                   |
| Append-only decision    | `record_decision`                                  | `decision` (blockchain)                                                    | DB-internal               |
| Per-tool audit          | DB triggers + tool wrappers                        | `decision_audit`                                                           | DB-internal               |
| Customer chat           | Agent conversational tool                          | `decision`, `policy_corpus`                                                | Customer UI ↔ API ↔ Agent |
| Backoffice HITL         | Backoffice API → close task → finalize             | `hitl_task`, `decision`                                                    | Backoffice UI             |
| Parameter change        | Backoffice API → write `system_config`             | `system_config`, `policy_parameter_history`                                | Backoffice UI             |
| Risk dashboard          | aggregation queries                                | `decision`, `loan_application`, `credit_bureau_snapshot`                   | Backoffice UI             |
| Fair-lending review     | scheduled job + reviewer flow                      | `fair_lending_review`                                                      | Backoffice UI + DB job    |
| Audit replay            | replay endpoint                                    | `decision_audit`                                                           | Backoffice UI             |

---

## Demo Script

1. **Setup walk-through** — show synthetic dataset stats, OPA Rego files + `opa test` green, the Backoffice config panel with thresholds and the **Mandatory-HITL switch**.
2. **Approve path** — customer chats, uploads clean docs → APPROVE with priced offer; show audit trail + policy citations + blockchain row.
3. **Reject paths** — hard DTI cap; expired ID; sanctions hit. Show reason codes surfaced to the customer; show audit.
4. **HITL paths** — mid-band score; amount above cap; MARGINAL OCR. Switch to Backoffice, claim the task, review the full picture, decide. Audit closed.
5. **Mandatory-HITL flag** — flip the switch in the backoffice; rerun the clean profile case; observe REFER_HUMAN, with OPA tool outputs still captured in the audit.
6. **Parameter hot-edit** — change `dti_hard_cap` in the backoffice; rerun a boundary case → different outcome. Show `policy_parameter_history` and the side-by-side audit comparison.
7. **Risk Management Dashboard** — apply a +200bps shock; show pressure surface and the suggested threshold-tightening counterfactual.
8. **Fair-Lending Review** — run the periodic sampler; flagged buckets; reviewer flow.
9. **Audit replay** — pick any decision; click "Replay" → identical outcome from stored audit input.
10. **Blockchain tamper demo** — attempt `UPDATE decision SET outcome = 'APPROVE' WHERE decision_id = …` → DB rejects.
11. **Customer chat — right of explanation** — customer asks the agent "why was I declined?" → agent answers from rationale + policy chunks.

---

## Out of Scope

- Counter-offer / structuring logic.
- Real bureau integration (everything synthetic).
- Production-grade Application Service (Spring Boot stub only).
- Core-banking write-back (mock the booking call).
- Channel UX polish beyond the two demo UIs.
- Region-specific compliance attestations (the PoC is region-agnostic by design).

---

## Risks & Open Questions

| Risk                                                               | Mitigation                                                                                                                                                                                                         |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Demo dataset is engineered to exercise paths — not real evaluation | Explicit messaging: the PoC proves the **architecture pattern**, not credit model quality. With minor tweaks (real data, real bureau, calibrated thresholds), the same plumbing becomes a production-grade system. |
| Sanctioned LLM model varies by region                              | Configuration parameter; pick at deploy time. No code change.                                                                                                                                                      |
| Open-source OCR quality on real-world documents                    | Acceptable for the PoC. Production swap to a commercial ID-verification vendor is a parameter change in `extract_document`.                                                                                        |
| Observability volume                                               | `decision_audit` retention policy is configurable; older audits can be archived to Object Storage + the decision row remains on blockchain for traceability.                                                       |
| OPA bundle reload latency on parameter change                      | Acceptable for the PoC (seconds). Pin reload-on-write + show the timestamp in the backoffice.                                                                                                                      |
| Fair-lending review defaults                                       | Defaults to the 4/5 rule as a reasonable starting point. Every bank tunes.                                                                                                                                         |

---

## Next Steps

- Lock the data model and `system_config` parameter list.
- Generate the synthetic dataset and mock ID templates for the three quality tiers.
- Author the OPA policy packages with `opa test` coverage.
- Stand up the OPA MCP server and bind the tool set to the agent.
- Build the two UIs as thin shells over the API.
- Walk the test bench end-to-end; every scenario green with a complete audit trail.

---
