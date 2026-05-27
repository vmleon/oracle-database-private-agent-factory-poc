# Local deployment

End-to-end runbook for the Decisioning Engine PoC on rootless podman. The architecture that motivates this is in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md); this file is the click-by-click runbook.

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
- A `caddy-ollama-tls` container terminating TLS in front of the LAN LLM endpoint, plus an Oracle SSL wallet trusting Caddy's CA (registered via the `SSL_WALLET` database property — kept for future HTTPS-from-DB work).
- LLM Configuration in PAF registered against your vLLM endpoint on the GPU host (generation on `:8000`, embeddings on `:8001`).
- The customer-facing `CHAT_WORKFLOW` flow built in PAF Agent Builder from a versioned blueprint, exercising all four tool channels against the seed data.

**Not wired locally**: Select AI profiles (`chat_profile` / `research_profile`). Oracle Database Free 26ai (23.26.x) rejects custom `provider_endpoint` values in `DBMS_CLOUD_AI` pre-flight (`ORA-20401`) — see [`docs/DEPLOYMENT.md §7`](docs/DEPLOYMENT.md). The `CHAT_WORKFLOW` flow uses a SQL Query node + LLM locally; full Select AI Bridge is the ADB demo path.

The Spring Boot backend and the Angular UIs are not in the compose yet, and the OCR service is a stub (real YOLO/Tesseract pipeline is a separate workstream). The next-steps list in [`README.md`](README.md#current-state) shows the order they land in.

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
- `docker.io/openpolicyagent/opa:latest`, `docker.io/caddy:2-alpine`, `docker.io/python:3.12-slim` (the slim base is built once each for `opa-mcp`, `ocr-mcp`, and `registry-api`).
- `ojdbc11` JDBC driver from Maven Central (the Ansible role caches it to `~/.cache/paf-poc/liquibase-libs/`).

## 1. Install prereqs and extract the PAF kit

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py setup local
```

`setup local` checks the prereqs in the table above and writes a `.env` with your Oracle password and vLLM host / port / model choices.

Download the ARM64 PAF tarball from Oracle (e.g. `oracle_agent_factory_25.3.9_arm.tar.gz`, ~2.3 GB), then:

```bash
python manage.py paf prepare ~/Downloads/oracle_agent_factory_25.3.9_arm.tar.gz
```

This extracts the kit into `./paf-kit/` (gitignored, ~6 GB on disk), reads `app_version` from the kit's `version.json`, writes `PAF_APP_VERSION=…` into `.env`, and snapshots the kit's pristine bind-mount state so `local down --purge` can restore it. Required once, plus once per kit upgrade.

## 2. Boot the stack

```bash
python manage.py local up
```

What this does, in order:

- Starts the Oracle container, waits for `DATABASE IS READY TO USE!`, sets `max_string_size=EXTENDED`.
- Generates a self-signed Caddy CA + server cert, builds an Oracle SSL wallet that trusts the CA, and points the database at it via the `SSL_WALLET` property.
- Installs `DBMS_CLOUD` (if missing) via `catcon.pl`.
- Applies pre-Liquibase sysdba grants (TABLE RETENTION, required before the Blockchain `decision` table is created).
- Runs Liquibase against `database/liquibase/oracle/` (via Ansible).
- Applies post-Liquibase sysdba grants + network ACL for `caddy-ollama-tls:443`.
- Builds the `opa-mcp`, `ocr-mcp`, and `registry-api` images (first run only) and starts the `opa`, `opa-mcp`, `ocr-mcp`, `registry-api`, `caddy-ollama-tls`, and `paf` containers.
- Writes PAF's `.config_complete.marker` and `version.json` so the kit's startup script unblocks.

The command is idempotent — re-running it from any state is safe and converges to a healthy stack.

Confirm everything is up:

```bash
python manage.py info
```

Prints the JDBC URL, service users, PAF URL, OPA URL, OPA MCP URL, OCR MCP URL, and Registry API URL.

## 3. Install PAF

Open the installer in your browser:

```
https://localhost:8080/agentFactory/installation
```

PAF terminates TLS itself with a self-signed cert — your browser will warn; accept and continue. Plain `http://` returns HTTP 400.

`python manage.py paf bootstrap` prints the exact values to paste. It covers all four wizard steps:

- **Step 1 — admin user.** Pick a name and password; you'll sign in as this user.
- **Step 2 — database.** DB host: `oracle-free-26ai` (compose service name — **not** `localhost`, which would point at the PAF container itself). Port `1521`, service `FREEPDB1`, user `AGENT_FACTORY`, password = `DB_PASSWORD` from `.env`.
- **Step 3 — install.** Click Install. PAF creates its metadata tables under `AGENT_FACTORY` and a read-only worker user `AAI_RO_AGENT_FACTORY`.
- **Step 4 — LLM Management.** Register two **LLM Configurations** against your vLLM endpoint:
  - **`vllm-gen-qwen2.5-32B`** — generative; model `Qwen/Qwen2.5-32B-Instruct-AWQ` (native tool-calling, reliably consistent on the 4-step CHAT_WORKFLOW recipe).
  - **`vllm-embed-bge-m3`** — embeddings; model `BAAI/bge-m3`.

  PAF's Agent node lists registrations by **configuration name**, not by model ID — `paf/flows/CHAT_WORKFLOW.md` references these names verbatim, so use them exactly. Pick **LLM provider: vLLM** (a first-class radio option in PAF's form, alongside OCI GenAI / OpenAI / Ollama / Gemini). The two models run as separate vLLM containers on separate ports (defaults `:8000` for generation, `:8001` for embeddings). Paste the host with its scheme into the **Host** field (`http://<gpu_host>`) and the port (`8000` or `8001`) into the separate **Port** field — PAF appends `/v1/…` itself when the provider is vLLM. `paf bootstrap` resolves `.local` mDNS names to an IPv4 address for you, since the PAF container can't do mDNS. Smaller quantisations / 7B variants work for tool-call smoke tests but produce internally inconsistent recommendations across a 4-tool pipeline — see `paf/flows/CHAT_WORKFLOW.md §Operating constraints`.

After install completes, sign in as the admin user.

## 4. Register tools and datasources

Five post-install registrations in the PAF admin area — four MCP servers, one Database datasource, and one HTTP datasource. All target the `CHAT_WORKFLOW` flow; the `RESEARCH_WORKFLOW` flow has no external tools by design.

### 4a. MCP servers

Admin → **MCP Servers** → **Add MCP server**, four times. The form has three fields each time; use the same `Direct` authentication mode for all (no auth — the wrappers are internal to the compose network, not published to the host).

| Server name   | Server URL                     | Tools                                                                                                                    |
| ------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `opa-mcp`     | `http://opa-mcp:8500/mcp/`     | seven typed tools wrapping the Rego rules — see table below                                                              |
| `ocr-mcp`     | `http://ocr-mcp:8501/mcp/`     | one stub tool `extract_document(storage_uri, requested_doc_type?)` returning canned classification + OCR responses       |
| `hitl-mcp`    | `http://hitl-mcp:8502/mcp/`    | one side-effect tool `create_hitl_task(...)` — calls the in-DB PL/SQL function in `AGENT_TOOLS.PKG_AGENT_TOOLS`          |
| `banking-mcp` | `http://banking-mcp:8503/mcp/` | one read-only tool `lookup_application(session_token)` — resolves the opaque session token to the customer's app context |

**Do not use `localhost`** in any URL — PAF must reach the wrappers over the compose network, not the host.

After saving, each server should report a connected status. The discovered tools surface inside the **Agent node** in Agent Builder once you wire each MCP Server node to it (§5) — there isn't a separate global tool-list view.

**Note on `hitl-mcp`.** This is the agent's only side-effect tool — it writes a `hitl_task` row and enqueues `HITL_REQUEST` atomically. The `CHAT_WORKFLOW` flow you build in §5 calls it as the terminal action, sourcing `application_id` from `banking-mcp`'s `lookup_application` (never from the user). The cloud-path equivalent — exposing the same PL/SQL function as a Select AI Tool through the Select AI Bridge node — is documented in `docs/DESIGN.md §11` ("`create_hitl_task` transport").

**Note on `banking-mcp`.** This is the trust boundary for `CHAT_WORKFLOW`. The agent receives an opaque `session_token` from a PAF Text Input node (hardcoded per-scenario for the POC; minted by the App Service in production). `banking-mcp.lookup_application` validates the token against `APP.auth_session` and returns the joined application context using `cx_Oracle` bind variables. **Never extract `customer_id` or `application_id` from the customer chat message** — that would be an IDOR vector (see `issues/sql-query-no-bind-variables.md` and `issues/no-flow-start-inputs.md`). The wrapper connects as `REPORTING` (same user as the Banking Application DB datasource in §4b); `REPORTING` is granted `SELECT` on `APP.auth_session` by Liquibase changeset 011, which also seeds one token row per test scenario.

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

The `CHAT_WORKFLOW` flow has a **SQL Query node** that joins `REPORTING.chat_v_loan_application` + `chat_v_applicant_profile` + `chat_v_credit_bureau` + `chat_v_existing_facilities` to resolve `customer_id → application_id` and pull DTI inputs into the prompt. SQL Query nodes only see databases registered as **Database data sources** — they don't reuse PAF's own metadata connection.

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

## 5. Build `CHAT_WORKFLOW`

`CHAT_WORKFLOW` is the customer-facing Agent Builder flow that combines OPA, OCR, Company Registry, and the in-DB HITL tool into the three-tier recommendation contract documented in `docs/DECISIONING-ENGINE-USE-CASE.md`. It is the only Agent Builder flow you need to build in this runbook.

The full blueprint is at [`paf/flows/CHAT_WORKFLOW.md`](paf/flows/CHAT_WORKFLOW.md). It gives you, in one place:

- The node graph (Chat input + Prompt + SQL Query for application context + two MCP server nodes — `opa-mcp` and `hitl-mcp` — + one REST API datasource node + Agent + Chat output). `ocr-mcp` is intentionally NOT wired by default; re-add it only when testing OCR scenarios.
- The SQL Query that resolves `customer_id → application_id`, joining `chat_v_loan_application` + `chat_v_applicant_profile` + `chat_v_credit_bureau` and aggregating monthly facility payments.
- The full **Custom instructions** block to paste into the Agent node — encodes a 4-step recipe (`required_documents` → `verify_employer` → DTI/PTI + `evaluate_eligibility` → `create_hitl_task`), the three-tier recommendation contract, and strict rules against tool loops and customer-facing disclosure of internal numbers.
- The wiring table (port → port).
- Playground test prompts mapped to scenario customers (`1` Alice / `4` David / `5` Eva / `6` Frank / `10` Jane / `11` Kyle), plus a mismatch check that exercises the no-row guard. Each scenario leaves one row in `APP.hitl_task` and one message on `APP.HITL_REQUEST`; the mismatch case emits an `application not found` evidence block instead.
- An **Operating constraints** section listing the non-obvious behaviours that shape the build (port-type compatibility rules, per-agent tool-surface discipline, model-size requirements, customer-id numbering on fresh deploys, etc.) — read it before iterating on the flow.

Verify each run with:

```sql
SELECT task_id, application_id, agent_recommendation, agent_run_id
  FROM APP.hitl_task
 ORDER BY task_id DESC FETCH FIRST 5 ROWS ONLY;

SELECT COUNT(*) FROM "APP"."HITL_REQUEST";
```

When the flow is green across all five scenarios, export the JSON from Agent Builder (top-right menu → Export) and save to `paf/flows/chat_workflow.flow.json` so a clean redeploy can re-import it.

If anything hangs or errors, `python manage.py local logs paf` shows the backend trace.

## Day-2

| Command                                 | What it does                                                                                                                                                                                                                                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `python manage.py local up`             | Idempotent: starts containers if down, runs Liquibase if any pending changesets.                                                                                                                                                                                                                       |
| `python manage.py local provision`      | Re-runs Liquibase + grants only (no podman restart). Use after editing the changelog.                                                                                                                                                                                                                  |
| `python manage.py local logs <service>` | Tails a service (`oracle-free-26ai`, `paf`, `opa`, `opa-mcp`, `ocr-mcp`, `registry-api`, `caddy-ollama-tls`).                                                                                                                                                                                          |
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
