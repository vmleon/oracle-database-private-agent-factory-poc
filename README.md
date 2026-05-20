# Oracle Database Private Agent Factory — Banking Decisioning Engine PoC

A banking proof of concept showing **Oracle AI Database 26ai + Private Agent Factory** running an end-to-end retail loan decisioning flow with full observability (per-tool audit, Blockchain Tables, parameter history).

## Why this PoC exists — the story

**Lina, a credit risk analyst,** keeps hearing the same complaint from origination: loan officers want a fast, governed pre-screen on incoming personal-loan applications before committing to a full credit decision and a priced offer. Today that work is ad-hoc, undocumented, and impossible to audit.

In **Private Agent Factory**, Lina builds a **Personal-Loan Pre-Screen Agent** using approved read-only tools — customer master, credit bureau snapshot, existing facilities, and Select AI RAG over the bank's lending policy corpus. This gets the business **60–70% of the way there**: a useful, policy-aware triage agent built quickly by a domain expert, without a project on IT's backlog.

This is the **factory moment**. Lina can create one agent today, then ten, twenty, or a hundred specialized agents for adjacent products — credit cards, secured loans, SMB lending, mortgage pre-screen, KYC refresh triage — all reusing the same approved data tools and the same policy RAG.

**Sam, a loan officer,** asks: _"Should we proceed with this customer's $25,000 personal-loan request?"_ The agent returns a **moderate-confidence pre-screen** grounded in bureau evidence and cited lending policy: applicant in band, no obvious sanctions or KYC blockers, DTI within soft range — recommend proceeding to full decisioning.

Lina **publishes the Agent Factory endpoint** as the business-approved contract: _this_ is what pre-screen means, _this_ is the data it's allowed to touch, _this_ is how it cites policy.

**Diego, an enterprise application developer,** consumes that endpoint and productizes it into a full **Credit Decisioning Agent Loop**: a deterministic **OPA** rule engine (eligibility, AML, KYC, fair-lending), governed **vector** retrieval over policy and similar past cases, an **OCR pipeline** (YOLO + PaddleOCR) over uploaded ID and payslip documents, a **pricing engine** with risk-band rate-card lookup, **TxEventQ** for HITL claim and async OCR, a **Blockchain Table** for an append-only decision audit, a **Mandatory-HITL** toggle, a customer chat UI, a backoffice queue, and production APIs.

Sam asks again: _"$25,000 personal loan for this customer — what's the decision?"_ Now the production Agent Loop returns a **REFER_HUMAN with a priced indicative offer** — grounded in vector policy citations, similar past cases, OPA reason codes (`dti_in_soft_band`, `ocr_marginal_on_payslip`), OCR-verified document completeness, a risk-band-adjusted rate, a HITL task auto-created in the backoffice queue, and an immutable blockchain decision record retained for seven years. The customer sees only the reason codes the bank chose to disclose.

**The point of the PoC:** Private Agent Factory lets business experts rapidly create useful, governed agents. Developers then productize those approved endpoint contracts into enterprise-ready Decisioning Loops — deterministic where banks demand determinism, observable where regulators demand audit — all powered by Oracle's converged AI Database.

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
- OPA MCP and OCR MCP services, then the production `DECISIONING_AGENT` flow.
- Spring Boot Application Service + the two Angular UIs.

Cloud deployment (OCI Terraform + Ansible, ADB + LB) is documented as a design target in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) but is not implemented.
