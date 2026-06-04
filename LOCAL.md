# Local deployment

End-to-end runbook for the Decisioning Engine PoC on rootless podman. The architecture and the four-agent rationale live in [`docs/DESIGN.md`](docs/DESIGN.md) (deployment strategy in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)); the flow itself is [`paf/flows/CHAT_WORKFLOW.md`](paf/flows/CHAT_WORKFLOW.md). This file is the click-by-click runbook.

You walk through five steps:

1. [Install prereqs and extract the PAF kit.](#1-install-prereqs-and-extract-the-paf-kit)
2. [Boot the stack (`local up`).](#2-boot-the-stack)
3. [Install PAF and register the LLM through its UI wizard.](#3-install-paf)
4. [Register the MCP servers and datasources in PAF.](#4-register-tools-and-datasources)
5. [Build the `CHAT_WORKFLOW` Agent Builder flow.](#5-build-chat_agent)

When you're done you have:

- Oracle Database Free 26ai on `localhost:1521` (service `FREEPDB1`), `max_string_size=EXTENDED`, schema users `APP` / `REPORTING` / `AGENT_TOOLS` / `AGENT_FACTORY`, full banking + decisioning schema, and `DBMS_CLOUD` + `DBMS_CLOUD_AI` installed.
- Private Agent Factory at `https://localhost:8080/`, installed against the local 26ai database under `AGENT_FACTORY`.
- An `opa` container (Open Policy Agent in server mode loading every `.rego` under `opa/packages/`) and a sibling `opa-mcp` container — a FastMCP wrapper exposing each Rego rule as a typed MCP tool at `http://opa-mcp:8500/mcp/`. PAF reaches it as an **MCP Server node** wired to `CHAT_WORKFLOW` only.
- A stub `ocr-mcp` container — FastMCP wrapper with one `extract_document` tool at `http://ocr-mcp:8501/mcp/`. Returns canned classification + extraction results keyed on the document filename (placeholder for the real YOLO + PaddleOCR/Tesseract pipeline).
- A `registry-api` container — synthetic FastAPI Company Registry with a single `verify_employer(name)` route. OpenAPI 3.1 spec at `http://registry-api:8600/openapi.json`. Registered with PAF as an **HTTP datasource** wired to `CHAT_WORKFLOW` only.
- An `application-backend` container — the Spring Boot Application Service on `localhost:8090`. (It stands in for the bank's **existing application backend, extended to drive PAF flows** — it is the PAF _client_, not part of the PAF platform.) It lists demo customers (`GET /v1/customers`), mints the opaque session token at `POST /v1/login`, brokers each chat turn at `POST /v1/chat` (enveloping the token, stripping the agent's internal marker blocks), and replays history at `GET /v1/chat/history`. It is the client that drives `CHAT_WORKFLOW`.
- An `application-mcp` container — FastMCP write tool `upsert_application(session_token, amount?, term_months?, purpose?)` at `http://application-mcp:8504/mcp/`. The intake agent uses it to create / patch a customer's `DRAFT` loan application. Connects as `AGENT_FACTORY`; the customer is resolved from the token server-side.
- LLM Configuration in PAF registered against your vLLM endpoint on the GPU host (generation on `:8000`, embeddings on `:8001`). PAF reaches vLLM directly — there is no TLS proxy in the loop.
- The customer-facing `CHAT_WORKFLOW` flow built in PAF Agent Builder from a versioned blueprint, exercising all four tool channels against the seed data.

**Not wired locally**: Select AI profiles (`chat_profile` / `research_profile`). Oracle Database Free 26ai (23.26.x) rejects custom `provider_endpoint` values in `DBMS_CLOUD_AI` pre-flight (`ORA-20401`) — see [`docs/DEPLOYMENT.md §7`](docs/DEPLOYMENT.md). The `CHAT_WORKFLOW` flow uses local MCP tools + LLM; full Select AI Bridge is the ADB demo path.

> **Note — Caddy / HTTPS-from-DB removed.** Oracle's `DBMS_CLOUD` requires an HTTPS callout, so an earlier iteration ran a Caddy TLS terminator in front of vLLM (self-signed cert added to the Oracle SSL wallet) plus a network ACL. That has been removed: Select AI never worked locally anyway (`ORA-20401`), so the Caddy proxy, SSL wallet, and ACL were pure inconsistency. **If you ever wire Select AI locally** you'd need to re-introduce TLS termination in front of vLLM, add its CA to the Oracle wallet, and grant the ACL — but the `ORA-20401` validator still blocks it, so Select AI stays a cloud/ADB feature. `CHAT_WORKFLOW` reaches the LLM through PAF's vLLM provider directly.

The Spring Boot backend (`application-backend`) is part of the compose and comes up with `local up`. The two Angular UIs (customer chat, backoffice) are not yet implemented, and the OCR service is a stub (real YOLO/Tesseract pipeline is a separate workstream). The next-steps list in [`README.md`](README.md#current-state) shows the order the rest land in.

## Prereqs

Install these on the host once.

| Tool               | macOS                                                                | Oracle Linux 8                                     |
| ------------------ | -------------------------------------------------------------------- | -------------------------------------------------- |
| `podman`           | `brew install podman && podman machine init && podman machine start` | `dnf install -y podman`                            |
| `podman-compose`   | `brew install podman-compose`                                        | `pip install podman-compose`                       |
| `python` 3.11+     | `brew install python@3.12`                                           | `dnf install -y python3.12`                        |
| `ansible-playbook` | `brew install ansible`                                               | `dnf install -y ansible-core`                      |
| `liquibase`        | `brew install liquibase`                                             | Download from <https://www.liquibase.org/download> |

`manage.py setup local` checks for all of these and prints install hints if any are missing.

You also need network access to pull:

- `container-registry.oracle.com/database/free:latest` (Oracle Database Free 26ai image; ~9 GB).
- `docker.io/openpolicyagent/opa:latest`, `docker.io/python:3.12-slim` (the slim base is built once each for `opa-mcp`, `ocr-mcp`, and `registry-api`).
- `ojdbc11` JDBC driver from Maven Central (the Ansible role caches it to `~/.cache/paf-poc/liquibase-libs/`).

## 1. Install prereqs and extract the PAF kit

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py setup local
```

Download the ARM64 PAF tarball from Oracle first (e.g. `oracle_agent_factory_arm64_26.4.0.tar.gz`, ~2.4 GB) so you can point `setup local` at it.

`setup local` checks the prereqs in the table above and writes a `.env` with your Oracle password, vLLM host / port / model choices, and the path to the PAF tarball (stored as `PAF_TARBALL`).

Then extract the kit — with no argument, `paf prepare` reads the path from `PAF_TARBALL` in `.env`:

```bash
python manage.py paf prepare
```

This extracts the kit into `./paf-kit/` (gitignored, ~6 GB on disk), reads `app_version` from the kit's `version.json`, writes `PAF_APP_VERSION=…` into `.env`, and snapshots the kit's pristine bind-mount state so `local down --purge` can restore it. Required once, plus once per kit upgrade.

## 2. Boot the stack

```bash
python manage.py local up
```

What this does, in order:

- Starts the Oracle container, waits for `DATABASE IS READY TO USE!`, sets `max_string_size=EXTENDED`.
- Installs `DBMS_CLOUD` (if missing) via `catcon.pl`.
- Applies pre-Liquibase sysdba grants (TABLE RETENTION, required before the Blockchain `decision` table is created).
- Runs Liquibase against `database/liquibase/oracle/` (via Ansible).
- Applies post-Liquibase sysdba grants (`EXECUTE` on `DBMS_CLOUD` / `DBMS_CLOUD_AI` to `AGENT_FACTORY`) and **creates the read-only worker user `AAI_RO_AGENT_FACTORY`** — 26.4 requires it to pre-exist before the PAF install wizard's DB step.
- **Configures TCPS** on the Oracle listener (port `2484`, self-signed cert CN=`oracle-free-26ai`) and exports the client wallet to `./tcps-wallet.zip` for the PAF install. TCP/1521 stays up alongside.
- **Generates the MCP TLS gateway cert + PAF trust bundle**, then starts the `mcp-proxy` Caddy gateway (terminates TLS for the MCP servers on `:8443`) and **injects the gateway cert into PAF's `certifi` bundle** so PAF trusts it.
- Builds the `opa-mcp`, `ocr-mcp`, and `registry-api` images (first run only) and starts the `opa`, `opa-mcp`, `ocr-mcp`, `hitl-mcp`, `application-mcp`, `banking-mcp`, `registry-api`, `application-backend`, `mcp-proxy`, and `paf` containers.
- Writes PAF's `.config_complete.marker` and `version.json` so the kit's startup script unblocks.

The command is idempotent — re-running it from any state is safe and converges to a healthy stack.

Confirm everything is up:

```bash
python manage.py info
```

Prints the JDBC URL, service users, PAF URL, OPA URL, OPA MCP URL, OCR MCP URL, and Registry API URL.

## 3. Install PAF

Run:

```bash
python manage.py paf bootstrap
```

It prints the installer URL plus the exact values to paste into each wizard step. Open the URL it shows (PAF serves a self-signed cert, so your browser will warn — accept and continue; plain `http://` returns HTTP 400) and follow the output, which has four sections:

- **Step 1 — admin user.** Pick a name and password; you sign in as this user after install.
- **Step 2 — database (TCPS / wallet).** 26.4 connects over **TCPS**, so pick **Connection type: Wallet**, drop the `tcps-wallet.zip` that `local up` exported, pick the `freepdb1` network alias from the wallet, and supply user `AGENT_FACTORY` / password `DB_PASSWORD`. The wallet carries the TCPS host (`oracle-free-26ai:2484`) + trusted cert, so you don't type host/port/protocol. After the connection succeeds PAF asks two more questions — answer **air-gapped? No** and **OCI certificates in wallet? No** (the Knowledge Assistant is skipped, which is fine — we don't use it). `paf bootstrap` prints all of this verbatim; follow its output. _(Fallback if PAF rejects the self-signed wallet: Basic / TCP / `oracle-free-26ai` / 1521 / no wallet.)_
- **Step 3 — install.** Click Install. PAF creates its metadata tables under `AGENT_FACTORY`. (The read-only worker user `AAI_RO_AGENT_FACTORY` was already created by `local up` — 26.4 requires it to pre-exist.) After install, before §4, relax the private-network guard once: `python manage.py paf allow-internal-mcp`.
- **Step 4 — LLM Management.** Register two **LLM Configurations** against your vLLM endpoint, using **generic configuration names** so they survive a model swap:
  - **`gen-model`** — generative; Model ID = `VLLM_GEN_MODEL` from `.env`.
  - **`emb-model`** — embeddings; Model ID = `VLLM_EMBED_MODEL` from `.env`.

  PAF's Agent node lists registrations by **configuration name**, not by model ID — `paf/flows/CHAT_WORKFLOW.md` references **`gen-model`** verbatim, so use that exact name; because the name is model-agnostic, swapping the underlying model later needs no flow change. Pick **LLM provider: vLLM** (a first-class radio option in PAF's form, alongside OCI GenAI / OpenAI / Ollama / Gemini). Paste the host with its scheme into the **Host** field (`http://<gpu_host>`) and the port into the separate **Port** field (gen `:8000`, embed `:8001`) — PAF appends `/v1/…` itself when the provider is vLLM. `paf bootstrap` resolves `.local` mDNS names to an IPv4 address for you, since the PAF container can't do mDNS.

**Recommended models** (chosen in `manage.py setup local`, stored in `.env` as `VLLM_GEN_MODEL` / `VLLM_EMBED_MODEL`):

| Role                     | Validated                                             | Also under test                    |
| ------------------------ | ----------------------------------------------------- | ---------------------------------- |
| Generative (`gen-model`) | `Qwen/Qwen2.5-72B-Instruct-AWQ` (native tool-calling) | `Qwen/Qwen3.6-35B-A3B`, and others |
| Embeddings (`emb-model`) | `BAAI/bge-m3` (1024 dims)                             | —                                  |

Smaller / heavily-quantised generative models are not recommended for the 4-tool pipeline — they drop the marker emissions `CHAT_WORKFLOW` relies on (see [`paf/flows/CHAT_WORKFLOW.md §Operating constraints`](paf/flows/CHAT_WORKFLOW.md)).

After install completes, sign in as the admin user.

## 4. Register tools and datasources

Six post-install registrations in the PAF admin area — five MCP servers and one HTTP datasource. (A Database datasource is no longer required by `CHAT_WORKFLOW` — the agents read through `banking-mcp.get_context`, not a SQL Query node; see §4b.) All target the `CHAT_WORKFLOW` flow; the `RESEARCH_WORKFLOW` flow has no external tools by design.

> ⚠️ **Run this once before any registration below — every install, including after `--purge`:**
>
> ```bash
> python manage.py paf allow-internal-mcp
> ```
>
> PAF 26.4 blocks private-network URLs by default. Skip this and the **first** MCP server (or the Company Registry datasource) fails with _"400 Bad Request: MCP server URL resolves to a private or non-routable network address and is not allowed"_. The setting lives in PAF's metadata DB and **resets to the secure default on every reinstall**, so re-run it after each fresh install.

### 4a. MCP servers

Admin → **MCP Servers** → **Add MCP server**, five times. The form has three fields each time; use the same `Direct` authentication mode for all (no auth — the wrappers are internal to the compose network, not published to the host).

> **26.4 — MCPs go through the `mcp-proxy` TLS gateway.** PAF 26.4 rejects `http://` MCP URLs and blocks private-network URLs by default. So the MCP apps are fronted by a Caddy TLS gateway (`mcp-proxy:8443`, self-signed cert PAF trusts via `SSL_CERT_FILE` — both wired by `local up`), and you must relax the private-network guard once per install: `python manage.py paf allow-internal-mcp`. URLs below are the gateway routes, **not** the raw `http://<svc>:<port>` (those still exist internally; the gateway forwards to them).

| Server name       | Server URL                                | Tools                                                                                                                                                                                                                               |
| ----------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `opa-mcp`         | `https://mcp-proxy:8443/opa/mcp/`         | seven typed tools wrapping the Rego rules — see table below                                                                                                                                                                         |
| `ocr-mcp`         | `https://mcp-proxy:8443/ocr/mcp/`         | one stub tool `extract_document(storage_uri, requested_doc_type?)` returning canned classification + OCR responses                                                                                                                  |
| `hitl-mcp`        | `https://mcp-proxy:8443/hitl/mcp/`        | one side-effect tool `create_hitl_task(...)` — calls the in-DB PL/SQL function in `AGENT_TOOLS.PKG_AGENT_TOOLS`                                                                                                                     |
| `banking-mcp`     | `https://mcp-proxy:8443/banking/mcp/`     | two read-only tools: `get_context(session_token)` (the universal token-keyed read the origination agents use — customer + application + profile + credit + `missing[]`/staleness) and the older `lookup_application(session_token)` |
| `application-mcp` | `https://mcp-proxy:8443/application/mcp/` | one write tool `upsert_application(session_token, amount?, term_months?, purpose?)` — creates / patches the customer's `DRAFT` application via `AGENT_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application`                               |

**Do not use `localhost`** in any URL — PAF must reach the gateway over the compose network, not the host.

After saving, each server should report a connected status. The discovered tools surface inside the **Agent node** in Agent Builder once you wire each MCP Server node to it (§5) — there isn't a separate global tool-list view.

**Note on `hitl-mcp`.** This is the agent's only side-effect tool — it writes a `hitl_task` row and enqueues `HITL_REQUEST` atomically. The `CHAT_WORKFLOW` flow you build in §5 calls it as the terminal action, sourcing `application_id` from `banking-mcp`'s `get_context` (never from the user). The cloud-path equivalent — exposing the same PL/SQL function as a Select AI Tool through the Select AI Bridge node — is documented in `docs/DESIGN.md §11` ("`create_hitl_task` transport").

**Note on `banking-mcp`.** This is the trust boundary for `CHAT_WORKFLOW`. The agent receives an opaque `session_token` minted by the Spring backend at login, enveloped in the chat message as `[[SESSION …]]` and split out by a RegexExtractor at flow start (the static Text Input node from earlier iterations is gone). `banking-mcp.get_context` validates the token against `APP.auth_session` and returns the customer's full context using `cx_Oracle` bind variables. **Never extract `customer_id` or `application_id` from the customer chat message** — that would be an IDOR vector (see `issues/01-sql-query-no-bind-variables.md` and `issues/02-no-flow-start-inputs.md`). The wrapper connects as `REPORTING` (same user as the Banking Application DB datasource in §4b); `REPORTING` is granted `SELECT` on `APP.auth_session` by Liquibase changeset 011, which also seeds one token row per test scenario. The origination agents call **`get_context(session_token)`** for the same trust-boundary reasons — one token-keyed read returns the customer's full picture (identity, KYC freshness, the open application or `null` with its `missing[]` fields, profile, credit, derived DTI/PTI) so each agent is self-sufficient from the database.

**Note on `application-mcp`.** The single **write** surface for intake. `upsert_application(session_token, …)` resolves `customer_id` from the token (bind variables — never from the chat message, the same IDOR-safe boundary as `banking-mcp`), creates the customer's `DRAFT` application on the first call, and patches supplied fields after — idempotent per the customer's open draft. It connects as `AGENT_FACTORY` and calls the definer-rights PL/SQL function `AGENT_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application` (grants from Liquibase changeset 012). Wire it only to the intake (Concierge) agent.

`opa-mcp` exposes:

| Tool                          | Rego rule                        | What it does                                                     |
| ----------------------------- | -------------------------------- | ---------------------------------------------------------------- |
| `required_documents`          | `decisioning.required_documents` | Document set for `(product, employment, residency, amount_band)` |
| `evaluate_eligibility`        | `decisioning.eligibility`        | Age / DTI / PTI / score gates → `{allow, deny[], warn[]}`        |
| `evaluate_aml`                | `decisioning.aml`                | Sanctions / PEP / suspicious-pattern flags                       |
| `evaluate_kyc`                | `decisioning.kyc`                | ID validity, document expiry, OCR quality tier                   |
| `evaluate_fair_lending_flags` | `decisioning.fair_lending`       | Disparate-impact pre-flight against monitored patterns           |
| `lookup_pricing`              | `decisioning.pricing.quote`      | Risk-band → indicative rate from the configured rate card        |
| `list_policy_versions`        | `/v1/policies`                   | Audit: list loaded Rego modules                                  |

Each tool's input schema is auto-derived from the FastMCP type hints in `src/ai/opa-mcp/server.py`. Outputs mirror Rego's `{allow, deny[], warn[]}` signal model — the agent folds them into the recommendation packet as evidence, never as automatic gates.

`ocr-mcp` is a stub. Its single `extract_document` tool returns canned responses keyed on the filename in `storage_uri` so the test-bench scenarios from `010-seed-synthetic.yaml` resolve correctly (e.g. `henry-payslip.pdf` → `MARGINAL`, `iris-*.pdf` → `UNUSABLE`, anything else → a `USABLE` fallback). Source: `src/ai/ocr-mcp/server.py`. Real OCR (YOLO + PaddleOCR/Tesseract, async via `OCR_REQUEST` queue) is a separate workstream.

### 4b. Database datasource (Banking Application DB)

**Optional — not required by `CHAT_WORKFLOW`.** The origination flow reads the customer's context through `banking-mcp.get_context` (cx_Oracle bind variables, fail-secure), **not** a PAF SQL Query node — so you can skip this registration for the runbook. Register a Database datasource only if you want an ad-hoc **SQL Query node** for experiments: SQL Query nodes only see databases registered as **Database data sources** (they don't reuse PAF's own metadata connection), and they must never carry untrusted input ([`issues/01-sql-query-no-bind-variables.md`](issues/01-sql-query-no-bind-variables.md)).

In PAF: **Data Sources** → **Add new data source** → **Source type: Database**. Fill in:

| Field        | Value                                               |
| ------------ | --------------------------------------------------- |
| Name         | `Banking Application DB`                            |
| Protocol     | `TCP`                                               |
| Host         | `oracle-free-26ai` (compose service name)           |
| Port         | `1521`                                              |
| Service name | `FREEPDB1`                                          |
| User         | `REPORTING`                                         |
| Password     | `DB_PASSWORD` from `.env` (same as `AGENT_FACTORY`) |

`REPORTING` owns the `chat_v_*` and `research_v_*` views and is `SELECT`-only — appropriate for the read-only SQL Query node (per `docs/PAF.md §7.5`, database datasources reject anything other than `SELECT`-like queries). Side-effect writes go through `hitl-mcp`.

**Do not use `localhost`** as the host — same reason as the MCP wrappers: PAF reaches Oracle over the compose network. The PAF installer's Step 2 already proved this hostname works.

After saving, the datasource should report a connected status. It surfaces inside Agent Builder's **SQL Query node** under the **Datasource** dropdown.

### 4c. HTTP datasource (Company Registry)

PAF's **Add new data source** dialog expects a file upload, not a URL — and FastAPI generates the spec at runtime, so there's no static file in the repo. Pull the spec from the running container and save it to the host (`~/Downloads/` is just a convenient scratch location — anywhere outside the repo works):

```bash
podman exec paf-oracle-free-26ai curl -s \
  http://registry-api:8600/openapi.json > ~/Downloads/registry-api-openapi.json
```

The file should start with `{"openapi":"3.1.0",...`.

In PAF: **Data Sources** → **Add new data source** → **Source type: Rest API → OpenAPI specification** → drag-and-drop `~/Downloads/registry-api-openapi.json` into the upload area.

The `registry-api` service ships eight synthetic company records that align with the employer names seeded by `010-seed-synthetic.yaml`, including `Phoenix Holdings Ltd` (`dormant`, scenario 28) and `Atlantis Innovations Ltd` (deliberately absent → `registered=false`, scenario 27). Source: `src/api/registry/`.

**Server URL.** The spec carries `"servers": [{"url": "http://registry-api:8600"}]` (set in `src/api/registry/main.py`'s `FastAPI(servers=...)`). PAF reads that — no separate base-URL prompt. If you need to point PAF at a non-compose host (e.g. cloud), override the spec at import time or edit the `servers` block in the file before upload.

### If a server or datasource won't connect

Run the sanity-check curls + log tail in [`docs/TROUBLESHOOT.md §Sanity-check curls`](docs/TROUBLESHOOT.md#sanity-check-curls-paf--tools--datasources).

## Application Service (`application-backend`)

`local up` also starts the Spring Boot Application Service on `localhost:8090` — the client that drives `CHAT_WORKFLOW`. It exposes:

- `GET /v1/customers` — demo customers for the login picker, each flagged `hasOpenApplication`. Customers with **no** open application (e.g. `Liam NoApplication`) are included so you can exercise conversational intake.
- `POST /v1/login` `{"customerId": N}` — mints an opaque, **customer-bound** session token. `applicationId` is `null` for a customer with no open application; `roomId` is `room-cust-{customerId}`. Passwordless by design (mock login, POC).
- `POST /v1/chat` `{"message": "…"}` with header `X-Session-Token: sess_…` — one chat turn. The backend envelopes the token as `[[SESSION …]]`, calls the published flow, and strips the agent's internal `[[…]]` marker blocks before returning the customer-facing reply.
- `GET /v1/chat/history` (same header) — replays the conversation for the session's customer.

`/v1/customers` and `/v1/login` work as soon as the database is up (§2); `/v1/chat` additionally needs the `CHAT_WORKFLOW` flow built and **published** (§5) and the vLLM endpoint reachable. Confirm the service is live:

```bash
curl -s http://localhost:8090/actuator/health                    # {"status":"UP"}
curl -s http://localhost:8090/v1/customers | python -m json.tool # find Liam NoApplication → "hasOpenApplication": false
```

The trust-boundary rationale (token-only envelope, customer resolved server-side) is in the design spec [`docs/superpowers/specs/2026-05-30-loan-origination-chat-design.md`](docs/superpowers/specs/2026-05-30-loan-origination-chat-design.md).

## 5. Build `CHAT_WORKFLOW`

`CHAT_WORKFLOW` is the customer-facing Agent Builder flow that combines OPA, OCR, Company Registry, and the in-DB HITL tool into the three-tier recommendation contract documented in `docs/DECISIONING-ENGINE-USE-CASE.md`. It is the only Agent Builder flow you need to build in this runbook.

The full build blueprint — the node graph, the four agents' (`Concierge` → `Docs & Employer` → `Eligibility` → `Recommendation`) custom instructions, the wiring table, test prompts (including the no-application intake walkthrough), and the operating constraints — is **[`paf/flows/CHAT_WORKFLOW.md`](paf/flows/CHAT_WORKFLOW.md)**. Build it there. This runbook only gets you to the point of opening Agent Builder with the tools (§4) and the LLM (§3) registered; the blueprint is the single source of truth for the flow itself.

Verify each run with:

```sql
SELECT task_id, application_id, agent_recommendation, agent_run_id
  FROM APP.hitl_task
 ORDER BY task_id DESC FETCH FIRST 5 ROWS ONLY;

SELECT COUNT(*) FROM "APP"."HITL_REQUEST";
```

When the flow is green across the test scenarios, capture the JSON for version control. PAF has **no Export button** — grab it from the browser's Network tab (`GET /agentFactory/v1/agents/<agent_id>`) per [`paf/flows/CHAT_WORKFLOW.md §Export`](paf/flows/CHAT_WORKFLOW.md) and save to `paf/flows/chat_workflow.flow.json`. It's a reference snapshot, not a clean re-import — see [`issues/05-no-flow-export-endpoint.md`](issues/05-no-flow-export-endpoint.md).

If anything hangs or errors, `python manage.py local logs paf` shows the backend trace.

## Day-2

| Command                                 | What it does                                                                                                                                                                                                                                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `python manage.py local up`             | Idempotent: starts containers if down, runs Liquibase if any pending changesets.                                                                                                                                                                                                                       |
| `python manage.py local provision`      | Re-runs Liquibase + grants only (no podman restart). Use after editing the changelog.                                                                                                                                                                                                                  |
| `python manage.py local logs <service>` | Tails a service (`oracle-free-26ai`, `paf`, `opa`, `opa-mcp`, `ocr-mcp`, `hitl-mcp`, `application-mcp`, `banking-mcp`, `registry-api`, `application-backend`).                                                                                                                                         |
| `python manage.py local down`           | Stops and removes containers. State persists in the `paf-oradata` volume and PAF's bind-mounted `paf-kit/applied-ai/{volume,dev-shared}` directories.                                                                                                                                                  |
| `python manage.py local down --purge`   | Also removes the Oracle data volume **and** resets PAF's bind-mounted `applied-ai/{volume,dev-shared}` directories to the kit-shipped defaults (snapshotted at `paf prepare` time). Next `local up` starts with a fresh DB and PAF presents the install wizard again. Does **not** re-extract the kit. |

Editing OPA policy: change a `.rego` file under `opa/packages/`, then `podman restart paf-opa`. The `opa-mcp` wrapper is stateless and picks up the new policy on the next call — no rebuild needed.

Rebuilding a wrapper image after editing `src/ai/opa-mcp/`, `src/ai/ocr-mcp/`, `src/ai/hitl-mcp/`, or `src/api/registry/`: re-run `python manage.py local up`. It passes `--build` to compose, so changed contexts get a fresh image (layer cache makes unchanged ones near-instant). Force a single-service rebuild without restarting the stack with:

```bash
podman compose -f deploy/podman/compose.local.yml build <service>
podman compose -f deploy/podman/compose.local.yml up -d <service>
```

…where `<service>` is `opa-mcp`, `ocr-mcp`, `hitl-mcp`, or `registry-api`.

(No `-p <name>` flag — `manage.py local up` uses the default project name derived from the compose dir, so all containers share network `podman_default`. Passing `-p paf` here would put the rebuilt container on a separate `paf_default` network and break DNS to its siblings.)

## Verifying

Connect with `sqlcl` (or any JDBC client):

```bash
sql SYSTEM/<password>@localhost:1521/FREEPDB1
```

Inside SQLcl:

```sql
SELECT username
  FROM dba_users
 WHERE username IN ('APP', 'REPORTING', 'AGENT_TOOLS', 'AGENT_FACTORY')
 ORDER BY username;
```

Expected: four rows.

## Troubleshooting

All validated workarounds for stack problems hit during local POC work live in [`docs/TROUBLESHOOT.md`](docs/TROUBLESHOOT.md), grouped by stack layer (host / Oracle / PAF install / PAF runtime / OPA). Add new entries there after the fix has been verified.
