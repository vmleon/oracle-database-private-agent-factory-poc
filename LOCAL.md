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
- **Step 4 — LLM Management.** Register the generative model (`Qwen/Qwen2.5-32B-Instruct-AWQ` — native tool-calling, reliably consistent on the 4-step CHAT_WORKFLOW recipe) and the embedding model (`BAAI/bge-m3`) against your vLLM endpoint. Pick **LLM provider: vLLM** (a first-class radio option in PAF's form, alongside OCI GenAI / OpenAI / Ollama / Gemini). The two models run as separate vLLM containers on separate ports (defaults `:8000` for generation, `:8001` for embeddings) — see [Setting up vLLM on a GPU host](#setting-up-vllm-on-a-gpu-host-eg-nvidia-dgx-spark). Paste the host with its scheme into the **Host** field (`http://<gpu_host>`) and the port (`8000` or `8001`) into the separate **Port** field — PAF appends `/v1/…` itself when the provider is vLLM. `paf bootstrap` resolves `.local` mDNS names to an IPv4 address for you, since the PAF container can't do mDNS. Smaller quantisations / 7B variants work for tool-call smoke tests but produce internally inconsistent recommendations across a 4-tool pipeline — see `paf/flows/CHAT_WORKFLOW.md §Operating constraints`.

After install completes, sign in as the admin user.

## 4. Register tools and datasources

Four post-install registrations in the PAF admin area — three MCP servers, one Database datasource, and one HTTP datasource. All target the `CHAT_WORKFLOW` flow; the `RESEARCH_WORKFLOW` flow has no external tools by design.

### 4a. MCP servers

Admin → **MCP Servers** → **Add MCP server**, three times. The form has three fields each time; use the same `Direct` authentication mode for all (no auth — the wrappers are internal to the compose network, not published to the host).

| Server name | Server URL                  | Tools                                                                                                              |
| ----------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `opa-mcp`   | `http://opa-mcp:8500/mcp/`  | seven typed tools wrapping the Rego rules — see table below                                                        |
| `ocr-mcp`   | `http://ocr-mcp:8501/mcp/`  | one stub tool `extract_document(storage_uri, requested_doc_type?)` returning canned classification + OCR responses |
| `hitl-mcp`  | `http://hitl-mcp:8502/mcp/` | one side-effect tool `create_hitl_task(...)` — calls the in-DB PL/SQL function in `AGENT_TOOLS.PKG_AGENT_TOOLS`    |

**Do not use `localhost`** in any URL — PAF must reach the wrappers over the compose network, not the host.

After saving, each server should report a connected status. The discovered tools surface inside the **Agent node** in Agent Builder once you wire each MCP Server node to it (§5) — there isn't a separate global tool-list view.

**Note on `hitl-mcp`.** This is the agent's only side-effect tool — it writes a `hitl_task` row and enqueues `HITL_REQUEST` atomically. The `CHAT_WORKFLOW` flow you build in §5 calls it as the terminal action, sourcing `application_id` from the in-flow SQL Query node (never from the user). The cloud-path equivalent — exposing the same PL/SQL function as a Select AI Tool through the Select AI Bridge node — is documented in `docs/DESIGN.md §11` ("`create_hitl_task` transport").

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
| Host         | `oracle-free-26ai` (compose service name)           |
| Port         | `1521`                                              |
| Service name | `FREEPDB1`                                          |
| User         | `REPORTING`                                         |
| Password     | `DB_PASSWORD` from `.env` (same as `AGENT_FACTORY`) |

`REPORTING` owns the `chat_v_*` and `research_v_*` views and is `SELECT`-only — appropriate for the read-only SQL Query node (per `docs/PAF.md §7.5`, database datasources reject anything other than `SELECT`-like queries). Side-effect writes go through `hitl-mcp`.

**Do not use `localhost`** as the host — same reason as the MCP wrappers: PAF reaches Oracle over the compose network. The PAF installer's Step 2 already proved this hostname works.

After saving, the datasource should report a connected status. It surfaces inside Agent Builder's **SQL Query node** under the **Datasource** dropdown.

### 4c. HTTP datasource (Company Registry)

PAF's **Add new data source** dialog expects a file upload, not a URL — and FastAPI generates the spec at runtime, so there's no static file in the repo. Pull the spec from the running container and save it to the host:

```bash
podman exec paf-oracle-free-26ai curl -s \
  http://registry-api:8600/openapi.json > registry-api-openapi.json
```

The file should start with `{"openapi":"3.1.0",...`.

In PAF: **Data Sources** → **Add new data source** → **Source type: Rest API → OpenAPI specification** → drag-and-drop `registry-api-openapi.json` into the upload area.

The `registry-api` service ships eight synthetic company records that align with the employer names seeded by `010-seed-synthetic.yaml`, including `Phoenix Holdings Ltd` (`dormant`, scenario 28) and `Atlantis Innovations Ltd` (deliberately absent → `registered=false`, scenario 27). Source: `src/api/registry/`.

**Server URL.** The spec carries `"servers": [{"url": "http://registry-api:8600"}]` (set in `src/api/registry/main.py`'s `FastAPI(servers=...)`). PAF reads that — no separate base-URL prompt. If you need to point PAF at a non-compose host (e.g. cloud), override the spec at import time or edit the `servers` block in the file before upload.

### If a server or datasource won't connect

Sanity-check the layers from the outside in.

```bash
# 1. OPA itself — does the policy load and a rule evaluate?
podman exec paf-oracle-free-26ai curl -s http://opa:8181/v1/data/decisioning/eligibility \
  -H 'content-type: application/json' \
  -d '{"input":{"applicant":{"age":34,"dti":0.41,"pti":0.18,"credit_score":642}}}'
# Expect: {"result":{"allow":false,"deny":[],"warn":["Credit score 642 in caution band (< 670)"]}}

# 2. MCP wrappers — do the FastMCP processes accept the streamable-http handshake?
podman exec paf-oracle-free-26ai curl -sf -o /dev/null -w "opa-mcp HTTP %{http_code}\n" \
  http://opa-mcp:8500/mcp/ -X POST -d '{}' -H 'content-type: application/json'
podman exec paf-oracle-free-26ai curl -sf -o /dev/null -w "ocr-mcp HTTP %{http_code}\n" \
  http://ocr-mcp:8501/mcp/ -X POST -d '{}' -H 'content-type: application/json'
# Expect: HTTP 307 (FastMCP's trailing-slash redirect) or HTTP 4xx with a JSON-RPC error.
#         Anything else (timeout, connection refused) = wrapper isn't healthy.

# 3. Registry API — does the FastAPI service answer and serve its OpenAPI spec?
podman exec paf-oracle-free-26ai curl -sf -o /dev/null -w "registry-api HTTP %{http_code}\n" \
  http://registry-api:8600/openapi.json
# Expect: HTTP 200. PAF reads the spec to expose verify_employer as a tool.

# 4. Logs
podman logs paf-opa-mcp           # FastMCP startup banner + per-request log
podman logs paf-ocr-mcp           # same
podman logs paf-registry-api      # uvicorn startup + per-request log
podman logs paf-opa               # OPA bundle load + per-request log
```

If OPA returns a 404 on `/v1/data/decisioning/...`, the `.rego` files didn't load — check `podman logs paf-opa` for a parse error and run `podman restart paf-opa` after fixing.

## 5. Build `CHAT_WORKFLOW`

`CHAT_WORKFLOW` is the customer-facing Agent Builder flow that combines OPA, OCR, Company Registry, and the in-DB HITL tool into the three-tier recommendation contract documented in `docs/DECISIONING-ENGINE-USE-CASE.md`. It is the only Agent Builder flow you need to build in this runbook.

The full blueprint is at [`paf/flows/CHAT_WORKFLOW.md`](paf/flows/CHAT_WORKFLOW.md). It gives you, in one place:

- The node graph (Chat input + Prompt + SQL Query for application context + two MCP server nodes — `opa-mcp` and `hitl-mcp` — + one REST API datasource node + Agent + Chat output). `ocr-mcp` is intentionally NOT wired by default; re-add it only when testing OCR scenarios.
- The SQL Query that resolves `customer_id → application_id`, joining `chat_v_loan_application` + `chat_v_applicant_profile` + `chat_v_credit_bureau` and aggregating monthly facility payments.
- The full **Custom instructions** block to paste into the Agent node — encodes a 4-step recipe (`required_documents` → `verify_employer` → DTI/PTI + `evaluate_eligibility` → `create_hitl_task`), the three-tier recommendation contract, and strict rules against tool loops and customer-facing disclosure of internal numbers.
- The wiring table (port → port).
- Playground test prompts mapped to scenario customers (`1` Alice / `4` David / `5` Eva / `6` Frank / `10` Jane). Each should leave one row in `APP.hitl_task` and one message on `APP.HITL_REQUEST`.
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

## Setting up vLLM on a GPU host (e.g. NVIDIA DGX Spark)

PAF talks to the LLM over the network. On Blackwell / GB10 hardware vLLM substantially outperforms Ollama — NVIDIA's own playbook ships a Spark-tuned vLLM image — so the local default points at **two vLLM containers** on the GPU host: one for generation, one for embeddings, both exposing OpenAI-compatible APIs.

References:

- [NVIDIA vLLM playbook for DGX Spark](https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/vllm)
- [vLLM official Docker deployment](https://docs.vllm.ai/en/latest/deployment/docker.html)
- [eugr/spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) — community Spark reference

### On the GPU host

Prereqs:

- NVIDIA driver installed (`nvidia-smi` works). On Spark, **driver 580.x** is recommended; 590.x has a CUDAGraph deadlock on unified memory.
- `docker` with the NVIDIA Container Toolkit configured. `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi` should print your GPU.
- (Spark only) Disable the pre-installed Snap Ollama so it doesn't fight your containers: `sudo snap stop ollama && sudo snap disable ollama`.

Create `~/vllm-stack/.env`:

```bash
GEN_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
GEN_PORT=8000
GEN_MAX_LEN=8192
GEN_GPU_MEM=0.55                # leave headroom for the embed container

EMB_MODEL=BAAI/bge-m3
EMB_PORT=8001
EMB_GPU_MEM=0.10

HF_TOKEN=                        # only needed for gated models (Llama, etc.)
VLLM_IMAGE=nvcr.io/nvidia/vllm:26.02-py3
```

Create `~/vllm-stack/docker-compose.yml` with two services pointing at `${VLLM_IMAGE}`:

- **`vllm-generate`** — runs `vllm serve ${GEN_MODEL} --port=8000 --gpu-memory-utilization=${GEN_GPU_MEM} --enable-auto-tool-choice --tool-call-parser=hermes --max-model-len=${GEN_MAX_LEN}`, published on `:${GEN_PORT}`. The `--enable-auto-tool-choice` + `--tool-call-parser=hermes` flags are what makes Qwen2.5 emit proper OpenAI tool calls, which PAF needs.
- **`vllm-embed`** — runs `vllm serve ${EMB_MODEL} --port=8000 --gpu-memory-utilization=${EMB_GPU_MEM}`, published on `:${EMB_PORT}`. vLLM 0.10+ auto-detects pooling models like `BAAI/bge-m3` from their HF config — the old `--task=embed` flag was removed and the explicit form is now `--runner=pooling`, but bge-m3 doesn't need it.

Both services need `--gpus all`, `ipc: host`, and a bind mount of `~/.cache/huggingface` for model caching. `--gpu-memory-utilization` fractions sum across containers (unified memory pool), so keep `0.55 + 0.10` under ~0.70 to leave room for kernel scratch.

Start:

```bash
cd ~/vllm-stack
docker compose up -d
# First start downloads weights (~17 GB for Qwen2.5-32B-AWQ + ~1.2 GB for bge-m3)
# and compiles FlashInfer kernels (~5 min, cached after). Subsequent starts are seconds.
docker compose logs -f vllm-generate
# wait for "Application startup complete"
```

Smoke-test both endpoints:

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-32B-Instruct-AWQ","messages":[{"role":"user","content":"hi"}]}' | jq

curl -s http://localhost:8001/v1/embeddings \
  -H 'content-type: application/json' \
  -d '{"model":"BAAI/bge-m3","input":["hello"]}' | jq '.data[0].embedding | length'
# Expect: 1024
```

Open `:8000` and `:8001` only to the laptop's IP — vLLM has no auth by default:

```bash
# firewalld example
firewall-cmd --add-rich-rule="rule family=ipv4 source address=<LAPTOP_IP> port port=8000 protocol=tcp accept" --permanent
firewall-cmd --add-rich-rule="rule family=ipv4 source address=<LAPTOP_IP> port port=8001 protocol=tcp accept" --permanent
firewall-cmd --reload
```

### Model management

vLLM doesn't have an `ollama pull`-style command. Models are HuggingFace handles and are downloaded automatically on the first container start. To switch the generation model, edit `GEN_MODEL` in `.env` and `docker compose down && docker compose up -d` — the new weights download on first run; previous weights stay cached under `~/.cache/huggingface/hub/`.

| Operation                     | Command                                                                                |
| ----------------------------- | -------------------------------------------------------------------------------------- |
| What's loaded right now       | `curl -s http://localhost:8000/v1/models \| jq '.data[].id'`                           |
| List cached HF models         | `du -sh ~/.cache/huggingface/hub/models--* \| sort -h`                                 |
| Remove a single model         | `rm -rf ~/.cache/huggingface/hub/models--<org>--<repo>`                                |
| Pull a newer vLLM image       | `docker compose pull && docker compose up -d`                                          |
| Wipe everything (start fresh) | `docker compose down; rm -rf ~/.cache/huggingface/hub/models--* ~/.cache/flashinfer/*` |
| Stop / start                  | `docker compose down` / `docker compose up -d`                                         |
| Tail one service              | `docker compose logs -f vllm-generate`                                                 |

### Memory budget (Spark has 121 GB unified)

At `GEN_GPU_MEM=0.55` (~67 GB) the generation container can host:

| HF handle                                   | Quant     | Approx. size | Notes                           |
| ------------------------------------------- | --------- | ------------ | ------------------------------- |
| `Qwen/Qwen2.5-32B-Instruct-AWQ`             | AWQ 4-bit | ~17 GB       | recommended default             |
| `RedHatAI/Qwen2.5-32B-Instruct-FP8-dynamic` | FP8       | ~32 GB       | best quality at this size class |
| `meta-llama/Llama-3.3-70B-Instruct` (AWQ)   | AWQ 4-bit | ~35 GB       | requires `HF_TOKEN` (gated)     |
| `nvidia/Llama-3.3-70B-Instruct-FP4`         | NVFP4     | ~18 GB       | NVIDIA's Spark-tuned variant    |

Wrong tool-call parser = the agent sees text instead of structured tool calls. Match `--tool-call-parser` to the model family: Qwen2.5 → `hermes`, Llama 3 → `llama3_json`.

### From the laptop

Verify reachability:

```bash
curl http://<GPU_HOST>:8000/v1/models | jq '.data[].id'
curl http://<GPU_HOST>:8001/v1/models | jq '.data[].id'
```

Re-run setup and pick the GPU host when prompted:

```bash
python manage.py setup local
# vLLM host (e.g. gpu-host.local or its IPv4): <GPU_HOST>
# vLLM generation port:               8000
# vLLM embedding port:                8001
# vLLM generation model:              Qwen/Qwen2.5-32B-Instruct-AWQ
# vLLM embedding model:               BAAI/bge-m3
```

Or edit `.env` directly:

```
VLLM_HOST=<GPU_HOST>
VLLM_GEN_PORT=8000
VLLM_EMBED_PORT=8001
VLLM_GEN_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ
VLLM_EMBED_MODEL=BAAI/bge-m3
```

Then `python manage.py local up` as usual — PAF will resolve `VLLM_HOST` to the GPU box.

If `VLLM_HOST` is a Bonjour/mDNS name (e.g. ends in `.local`), `manage.py local up` resolves it on the host (which can do mDNS) and injects a static `hostname → ip` mapping into the PAF container's `/etc/hosts` via compose's `extra_hosts`. You can then paste the friendly hostname into PAF's LLM Configuration form instead of the raw IP. The mapping refreshes on every `local up`, so a DHCP change is fixed by `python manage.py local up`.

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

**Podman: "no space left on device" during image pull.**
Re-point `TMPDIR` to a partition with at least 15 GB free, then `podman system reset` and retry:

```bash
export TMPDIR=/var/tmp
mkdir -p "$TMPDIR"
```

**Oracle container never becomes healthy.**
The Oracle Database Free image initialises on first boot and can take 3–5 minutes. Tail the logs:

```bash
python manage.py local logs oracle-free-26ai
```

Look for `DATABASE IS READY TO USE!`.

**`liquibase: command not found` when running `local up`.**
Re-run `python manage.py setup local` to surface the prereq check, then install Liquibase per the table above.

**Liquibase update fails with `ORA-01017: invalid username/password`.**
Your `.env`'s `DB_PASSWORD` no longer matches the password baked into the running container. Either edit `.env` to match the running container, or `local down --purge` and re-`local up` to start fresh.

**Port 1521 already in use.**
Stop any existing Oracle client on the host, or edit `deploy/podman/compose.local.yml` to remap the port (e.g. `15210:1521`) and update `DB_PORT` in `.env`.

**`local up` errors with `image not known: localhost/applied-ai-label:…`.**
`PAF_APP_VERSION` is set in `.env` but the image hasn't been built (or you cleared podman storage). Run `python manage.py paf build`, or just re-run `local up` — it builds on demand.

**PAF UI installer can't reach the database.**
The installer must use the service name `oracle-free-26ai` as the host, not `localhost` — `localhost` inside the PAF container points at the PAF container itself. Both containers share the project network so Oracle resolves by service name.

**PAF installer says `AGENT_FACTORY` is missing privileges, or "Test connection" returns 400 with `Unable to determine database compatibility level`.**
Make sure Liquibase ran (`python manage.py local provision`). The Liquibase grants live in `database/liquibase/oracle/001-users-and-grants.yaml` (PAF kit README); the one extra grant on `SYS.V_$PARAMETER` is applied by `manage.py local provision` as sysdba (SYSTEM cannot grant it, hence Liquibase can't).

**PAF logs loop forever on `Waiting for correct permissions to be set to mounted volume...` then exit.**
The kit's startup script polls for `/mount/.config_complete.marker` (a host-side handshake the kit's own `deploy.sh` would otherwise create with `podman exec ... touch`). `local up` writes it automatically; if you brought PAF up manually, create it yourself:

```bash
touch paf-kit/applied-ai/volume/.config_complete.marker
```

**PAF MCP discovery for `opa-mcp` or `ocr-mcp` returns 0 tools, or "connection refused".**
Most common cause is using `localhost` instead of `opa-mcp` / `ocr-mcp` in the URL — PAF must reach the wrapper over the compose network, not the host. Confirm with `podman exec paf-agent-factory getent hosts opa-mcp` (should print the container IP); same for `ocr-mcp`. If the address resolves but tool discovery still fails, run the sanity-check curls in [§4 — If a server or datasource won't connect](#if-a-server-or-datasource-wont-connect). The second most common cause is a network mismatch from rebuilding the container with `-p paf` — see the rebuild snippet in the Day-2 section.

**OPA returns `404` on `/v1/data/decisioning/...` rules.**
A `.rego` file failed to load. Check `podman logs paf-opa` for a parse error (line number + message), fix the file under `opa/packages/`, and `podman restart paf-opa`. The wrapper does not need a restart.
