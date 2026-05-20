# Oracle Database Private Agent Factory — Banking Decisioning Engine PoC

A banking proof of concept showing **Oracle AI Database 26ai + Private Agent Factory** running an end-to-end retail loan decisioning flow with full observability (per-tool audit, Blockchain Tables, parameter history).

## Why this PoC exists — the story

**Lina, a credit risk analyst,** keeps hearing the same complaint from origination: loan officers and underwriters want a fast, governed first look at every incoming personal-loan application, with reasoning they can defend in front of an auditor. Today that work is ad-hoc, undocumented, and impossible to replay.

In **Private Agent Factory**, Lina builds the **Personal-Loan Chat Agent**. It talks to the customer, asks for the right documents per `(employment_type, residency_status, amount_band)`, waits for OCR, pulls customer / bureau / facilities via Select AI over read-only views, cites lending policy via RAG, runs **OPA** for eligibility / AML / KYC / fair-lending, and writes a **recommendation packet** to the HITL queue — with one of three tiers (**APPROVE**, **REVIEW**, **DECLINE**) plus the reasoning that justifies it. **Every** application creates a HITL task. There is no silent automation, no "Mandatory-HITL switch" to remember to flip — the human is always the decision-maker.

This is the **factory moment**. One chat agent today; tomorrow Lina clones the pattern for credit cards, secured loans, SMB lending, mortgage triage, KYC refresh — same MCP toolkit, same Oracle AI Database, different prompt and product config.

**The customer** chats, uploads documents, and gets _"we're reviewing your application"_ — no surprise machine-rejection, no opaque approval.

**Diego, an enterprise application developer,** productises the platform: the **OCR** pipeline (YOLO + PaddleOCR) as an MCP server, an **OPA** wrapper as an MCP server, in-DB writers in the `AGENT_TOOLS` package, **TxEventQ** queues for async OCR and HITL claim, the customer chat UI, the backoffice queue, and the production APIs. He also ships a **second, backoffice-only agent** — the **Case Research Agent** — that lives behind the HITL detail screen and has access to broader data than the customer-safe chat agent: full transaction history, `decision_audit`, `policy_parameter_history`, deeper similarity over `case_history`. It cannot decide; it can read, analyse, and explain.

**Sam, a HITL reviewer,** opens the queue. He sees a **REVIEW** recommendation: _"$25,000 personal loan, self-employed expat, DTI 0.41, payslip OCR marginal on net-pay field"_. The reasoning enumerates exactly which signals tipped it — `dti_in_soft_band`, `ocr_marginal_on_payslip`, `expat_self_employed_doc_set_complete` — plus a short list of **explore-hints** the agent suggests Sam look at. Sam asks the **Case Research Agent**: _"show me how we decided similar cases in the last 12 months"_. It answers from `case_history` with three anchor cases and citations into `decision_audit`. Sam decides REJECT and types his note. The decision lands in the **Blockchain Table** — one row per bank decision — carrying the human's call, the agent's original recommendation, the override reason, and the full evidence packet, retained seven years and tamper-evident.

**The point of the PoC:** Private Agent Factory lets a domain expert wire a governed chat agent over Oracle AI Database — one for personal loans today, dozens for adjacent products tomorrow. The single, immutable record of the bank's decision is the **human's call**, not the AI's. Oracle AI Database 26ai carries the data, the rule-engine inputs, the vector retrieval, the queues, and the tamper-proof audit — all in one engine.

## Deployment

Two deployment options, same source tree:

- **Local** — rootless podman on a laptop or LAN. See [`LOCAL.md`](LOCAL.md).
- **Cloud** — OCI Terraform + Ansible (5 computes + ADB + LB). See [`CLOUD.md`](CLOUD.md) _(not yet implemented)_.

## Documentation

- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture, components, PAF Hybrid runtime mapping, source layout, locked decisions.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — deployment plan, `manage.py` command surface, Liquibase strategy, current scope.
- [`docs/PAF.md`](docs/PAF.md) — Oracle PAF practical study guide (in-repo reference).
- [`docs/DECISIONING-ENGINE-USE-CASE.md`](docs/DECISIONING-ENGINE-USE-CASE.md) — the credit-decisioning use case the PoC implements.
- [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — plain-English glossary of the banking and compliance terms used across the docs (DTI, PTI, KYC, AML, fair lending, etc.).

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

## Current status

The platform plumbing is wired end-to-end on the local stack:

- Oracle Database Free 26ai running locally with the four-schema layout (`APP`, `REPORTING`, `AGENT_TOOLS`, `AGENT_FACTORY`), `max_string_size=EXTENDED`, and PAF-specific grants on `AGENT_FACTORY`.
- Private Agent Factory container built from the vendor kit, talking to the local 26ai database under `AGENT_FACTORY` and reachable at `https://localhost:8080/`.
- LLM Configuration registered against an Ollama endpoint (laptop or LAN GPU host, with mDNS hostnames auto-resolved into the container via `extra_hosts`).
- A trivial `HELLO_AGENT` flow (Chat input → Prompt with `{{message}}` → LLM → Chat output) runs successfully in PAF's Playground.

What is next:

- Extend Liquibase with the banking + decisioning schema (`002-app-banking.yaml` onwards) so the agent has real data to work against.
- Select AI bootstrap (profile + NL2SQL object list over `REPORTING.*`, RAG vector index over `policy_corpus`).
- OPA MCP and OCR MCP services, then the production `CHAT_AGENT` flow (customer-facing, recommendation → HITL).
- Spring Boot Application Service + the two Angular UIs.
- `RESEARCH_AGENT` flow (backoffice-only, broader read scope) wired into the HITL detail screen.

Cloud deployment (OCI Terraform + Ansible, ADB + LB) is documented as a design target in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) but is not implemented.
