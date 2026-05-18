# Deployment Plan

This document is the **deployment plan** for the Decisioning Engine PoC. It explains the two supported deployment options (local podman, cloud OCI), the `manage.py` command surface that drives both, and the Liquibase strategy.

It is intentionally a _plan_, not a runbook. The user-facing playbooks live at the repository root:

- [`LOCAL.md`](../LOCAL.md) — step-by-step local deployment with podman.
- [`CLOUD.md`](../CLOUD.md) — step-by-step cloud deployment on OCI.

Component definitions and source layout are in [DESIGN.md](DESIGN.md). The PAF platform reference is [PAF.md](PAF.md).

---

## 1. Deployment options at a glance

| Property     | Local (podman)                                  | Cloud (OCI)                                                      |
| ------------ | ----------------------------------------------- | ---------------------------------------------------------------- |
| Audience     | Solo developer, laptop demo, on-prem evaluation | Demos to a bank, multi-user evaluation                           |
| Database     | Oracle Database Free 26ai container             | Autonomous Database 26ai (ADB)                                   |
| PAF          | PAF container, locally installed                | PAF container on a near-DB compute                               |
| Models       | Ollama on host, or pointed at LAN GPU host      | Ollama on a GPU compute (OCI shape)                              |
| OCR          | OCR MCP container (CPU) or LAN GPU host         | OCR MCP on the GPU compute alongside Ollama                      |
| Provisioning | `manage.py setup local → local up` (podman)     | `manage.py setup cloud → build → tf → terraform apply`           |
| Day-2        | `manage.py local <subcmd>`                      | OCI Bastion + Ansible (`manage.py ansible` helpers)              |
| Lifetime     | Ephemeral; destroy by `manage.py local down`    | Long-running; destroy by `terraform destroy` + `manage.py clean` |

Both options drive the same source tree, the same Liquibase changelogs (with separate `oracle/` and `adb/` directories), and the same Private Agent Factory artefacts.

## 2. `manage.py` command surface

Modelled after the [oracle-selectai-adb-sidecar-architecture](../) reference repo. Single Click-based CLI in `manage.py` at the repository root.

| Command                      | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                          | Touches                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| `manage.py setup local`      | Checks host prereqs (`podman`, `ansible-playbook`, `liquibase`, `python>=3.11`), then prompts for Ollama host/port (default `host.containers.internal:11434`, override to LAN GPU host), OCR host/port, embedding model (default `multilingual-e5-base`, 768 dims), local DB password. Writes `.env` with `DEPLOYMENT_TARGET=local`. Errors with install hints if any prereq is missing.                                                         | `.env`                                                  |
| `manage.py setup cloud`      | Checks host prereqs (`terraform`, `ansible-playbook`, `oci` CLI, `python>=3.11`), then reads `~/.oci/config`, lists subscribed regions + compartments, prompts for GPU shape, OCI GenAI region (future migration target), generates an Oracle-compliant ADB password, SSH key path. Writes `.env` with `DEPLOYMENT_TARGET=cloud`. Liquibase itself is **not** a host prereq for cloud — it is installed on the `ops` compute via cloud-init.     | `.env`                                                  |
| `manage.py build`            | Builds local artefacts: `./gradlew build -x test` for Spring Boot, `npm install && npm run build` for both Angular apps, `pip wheel` for Python services, `oras`/`podman build` for container images (local) or zips (cloud upload).                                                                                                                                                                                                             | `src/*/dist`, `src/*/build`, `deploy/tf/app/generated/` |
| `manage.py tf`               | Renders `deploy/tf/app/terraform.tfvars` from `.env`.                                                                                                                                                                                                                                                                                                                                                                                            | `deploy/tf/app/terraform.tfvars`                        |
| `manage.py ansible`          | Renders Ansible vars files (`deploy/ansible/*/vars/main.yml`) from `.env` (DB connection, Ollama host, OCR host, PAF URL, OPA URL, model id, embedding dim).                                                                                                                                                                                                                                                                                     | `deploy/ansible/*/vars/main.yml`                        |
| `manage.py local provision`  | Runs the `database-setup` Ansible playbook against `localhost` with `--connection=local`: renders `database/liquibase/oracle/liquibase.properties`, applies the Liquibase changelog, and performs any post-Liquibase setup (grants, Select AI bootstrap when applicable). Same playbook runs on the cloud `ops` compute against ADB.                                                                                                             | DB schema                                               |
| `manage.py paf bootstrap`    | After PAF is up, **prints an ordered checklist of manual UI steps**: LLM Management entries (Ollama LLM + embedding), data sources, Select AI profile, MCP server entries (OPA, OCR), Agent Builder flow import for `DECISIONING_AGENT`. API automation is planned for later; Playwright-style UI driving is explicitly avoided as too fragile across PAF versions. Captures the published run URL into `.env` once the operator pastes it back. | `.env`, stdout                                          |
| `manage.py local up`         | Brings the local podman stack up: full Oracle Database Free 26ai image, Ollama (if local), OCR, OPA, PAF, AI Services, Spring Boot backend, both Angular frontends. Waits for health. Calls `local provision` (Ansible → Liquibase + grants), then `paf bootstrap` (prints checklist).                                                                                                                                                           | local containers                                        |
| `manage.py local down`       | Stops and removes the local stack. Optional `--purge` clears volumes.                                                                                                                                                                                                                                                                                                                                                                            | local containers, volumes                               |
| `manage.py local logs <svc>` | Streams logs for a chosen service.                                                                                                                                                                                                                                                                                                                                                                                                               | —                                                       |
| `manage.py info`             | Prints LB IP / mobile-UI URL / backoffice-UI URL / agent run URL / ops SSH command.                                                                                                                                                                                                                                                                                                                                                              | —                                                       |
| `manage.py clean`            | Cloud teardown safeguard: refuses if Terraform state still has resources; otherwise prunes generated files.                                                                                                                                                                                                                                                                                                                                      | `deploy/tf/app/generated/`, `.env` (optional)           |

`build` and `info` mirror the reference repo verb-for-verb. `setup` is intentionally **split into `setup local` and `setup cloud`** because the two flows ask non-overlapping questions and produce different `.env` shapes. `local provision` (and the cloud equivalent on the `ops` compute) is the single point that runs the schema-setup Ansible playbook against the active target — `manage.py` itself never invokes Liquibase or sqlcl directly; that lives in Ansible, mirroring the reference repo pattern.

## 3. Local deployment (podman)

### 3.1 Topology

All services run as podman containers on the developer's machine, with two pointers (`OLLAMA_HOST`, `OCR_HOST`) that can resolve either to a local container or to a LAN-reachable GPU host. This means the demo runs on a laptop with a couple of services optionally offloaded — true to the "private on-prem" posture.

```
host (rootless podman)
├── oracle-free-26ai   (1521, 5500)
├── paf                (8080)
├── ai-services        (8000)  — PAF caller + OPA MCP + OCR MCP (or thin proxies to LAN)
├── opa                (8181)
├── ollama [optional]  (11434)  — or pointed at host LAN
├── ocr [optional]     (8500)   — or pointed at host LAN
├── backend            (8090)
├── frontend-mobile    (4200)
├── frontend-backoffice(4300)
└── caddy / nginx      (80/443) — reverse proxy
```

Reasoning for podman + rootless: matches PAF's documented platform stance (see [PAF §5](PAF.md#5-installation-and-deployment-options) — Podman, rootless, `max_string_size=EXTENDED`, supported OSes Oracle Linux 8 and macOS).

### 3.2 First-run flow

1. `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. `python manage.py setup local` — interactive; prompts for Ollama host (default `host.containers.internal:11434`), OCR host, embedding model (`multilingual-e5-base` @ 768 dims), local DB password. Writes `.env` with `DEPLOYMENT_TARGET=local`.
3. `python manage.py build` — builds artefacts and images.
4. `python manage.py local up` — starts podman stack, runs `local provision` (Ansible → Liquibase + grants against Oracle Free), bootstraps PAF.
5. `python manage.py info` — prints the URLs.

### 3.3 Day-2

- `python manage.py local logs <service>` to inspect a service.
- `python manage.py local restart paf` for targeted restarts.
- `python manage.py local provision` to reapply pending changelogs (and grants) after editing the schema.
- `python manage.py paf bootstrap --reload` to push updated Agent Builder flow / Select AI profile after edits.
- `python manage.py local down --purge` for a clean slate.

### 3.4 Local quirks tracked from PAF docs

- Local Ollama is best on the host (better GPU access) rather than inside a container — `OLLAMA_HOST` default is `host.containers.internal:11434`.
- `max_string_size=EXTENDED` is set during Oracle Free 26ai bootstrap via a Liquibase pre-run hook.
- Podman `TMPDIR` may need to be re-pointed to a partition with sufficient space; documented in `LOCAL.md`.
- Self-signed TLS for PAF during dev: the AI Services PAF caller is configured to accept the local PAF cert in non-prod mode (per [PAF §16.2](PAF.md#162-the-core-challenge)).

## 4. Cloud deployment (Terraform + Ansible on OCI)

### 4.1 Topology

Five workload computes plus ADB and LB, mirroring the answer to question 4 in brainstorming:

```
                          OCI Load Balancer (public)
                                  |
              +-------------------+---------------------+
              |                                         |
       /mobile  /backoffice   /api   /agentFactory      |
              |                                         |
   +----------v----------+         +--------------------v---+
   | front compute       |         | app compute            |
   |  - frontend-mobile  |         |  - Spring Boot backend |
   |  - frontend-backoff |         |  - AI Services         |
   +---------------------+         |  - OPA                 |
                                   +-----+------------------+
                                         |
                                         |
                             +-----------v------------+
                             | paf compute            |
                             |  - PAF container       |
                             +-----+------------------+
                                   |
                                   |    (private VCN)
                                   v
                            +------+--------+      +-------------+
                            | model compute |      |  ADB 26ai   |
                            |  - Ollama     |      |  - APP      |
                            |  - OCR MCP    |      |  - REPORTING|
                            |  (GPU shape)  |      |  - AGENT_*  |
                            +---------------+      +-------------+

                            +---------------+
                            | ops compute   |
                            |  (bastion)    |
                            +---------------+
```

GPU shape for the `model` compute is chosen at `manage.py setup cloud` time (e.g. an A10 shape for demos). Falling back to CPU-only Ollama is supported for short or smoke-test deployments and is also a setup choice.

### 4.2 Terraform layout

`deploy/tf/app/` is the root module. Per-role modules in `deploy/tf/modules/`:

| Module              | Provisions                                                                                                      |
| ------------------- | --------------------------------------------------------------------------------------------------------------- |
| `adbs`              | Autonomous Database 26ai, wallet generation, app DB user                                                        |
| `paf`               | VCN subnet, compute (PAF), cloud-init that fetches the PAF artefact via PAR and runs Ansible locally            |
| `model`             | GPU shape compute (or CPU fallback), Object Storage bucket reference for Ollama models, cloud-init runs Ansible |
| `app`               | Compute for Spring Boot + AI Services + OPA, cloud-init runs Ansible                                            |
| `front`             | Compute for both Angular dists, cloud-init runs Ansible                                                         |
| `ops`               | Small bastion compute with admin tooling                                                                        |
| `network` (in root) | VCN, subnets, security lists, NAT, public LB, listeners, backend sets                                           |
| `storage` (in root) | Object Storage bucket + 7-day PARs for every artefact zip (matches reference repo pattern)                      |

Cloud-init on each instance pulls its artefact via PAR and runs Ansible **locally** — no SSH between instances. This mirrors the reference repo's approach so the same operational mental model carries over.

### 4.3 Ansible roles

| Role    | Installs / configures                                                                                                                                 |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `paf`   | Podman + rootless prerequisites, `max_string_size=EXTENDED` validation, PAF tarball install, LLM Management bootstrap pointing at the `model` compute |
| `model` | NVIDIA drivers (if GPU shape), Ollama service unit, model pull for the configured LLM + embedding, OCR MCP container                                  |
| `app`   | JDK 21, Spring Boot service unit, Python 3 + AI Services service unit, OPA service unit + Rego bundle                                                 |
| `front` | nginx serving both Angular dists at `/mobile` and `/backoffice`                                                                                       |
| `ops`   | SSH config, kubectl/oci-cli/sqlcl/liquibase, bastion convenience scripts                                                                              |

### 4.4 First-run flow

1. `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. `python manage.py setup cloud` — picks OCI profile, region, compartment, GenAI region (future migration target), GPU shape, SSH key. Writes `.env` with `DEPLOYMENT_TARGET=cloud`.
3. `python manage.py build` — produces artefact zips into `deploy/tf/app/generated/`.
4. `python manage.py tf` — renders `terraform.tfvars`.
5. `cd deploy/tf/app && terraform init && terraform plan -out=tfplan && terraform apply tfplan`.
6. (Cloud-init on the `ops` compute installs Liquibase + JDBC jars and runs the same `database-setup` Ansible playbook against ADB using the generated wallet. No `manage.py` action needed from the developer's laptop for schema setup.)
7. `python manage.py paf bootstrap` — registers LLM/MCP/data sources/flow on PAF; captures published run URL.
8. `python manage.py info` — prints LB IP and URLs.

### 4.5 Cleanup

`cd deploy/tf/app && terraform destroy` then `python manage.py clean`. `clean` refuses if Terraform state still has resources, mirroring the reference repo guardrail.

## 5. Liquibase strategy

Two parallel changelogs, identical decisioning schema:

```
database/liquibase/
├── oracle/
│   ├── liquibase.properties.j2
│   ├── db.changelog-master.yaml
│   ├── 001-init.yaml                 # users, profiles, max_string_size check
│   ├── 002-app-banking.yaml          # customer, account, application, document
│   ├── 003-app-decisioning.yaml      # decision (Blockchain), decision_audit, hitl_task
│   ├── 004-app-config.yaml           # system_config, policy_parameter_history, fair_lending_review
│   ├── 005-reporting-views.yaml      # REPORTING.* curated views
│   ├── 006-agent-tools.yaml          # AGENT_TOOLS PL/SQL packages
│   ├── 007-vector.yaml               # policy_corpus, case_history, vector indexes
│   └── 008-seed-synthetic.yaml       # synthetic dataset (toggleable)
└── adb/
    ├── liquibase.properties.j2
    ├── db.changelog-master.yaml
    ├── 001-init.yaml                 # DBMS_CLOUD grants, AGENT_FACTORY user
    ├── 002-app-banking.yaml          # (shared with oracle/ via includeAll if practical)
    ├── 003-app-decisioning.yaml
    ├── 004-app-config.yaml
    ├── 005-reporting-views.yaml
    ├── 006-agent-tools.yaml
    ├── 007-vector.yaml               # AI Vector Search indexes
    ├── 008-select-ai-bootstrap.yaml  # Select AI profile + NL2SQL object list + RAG vector index
    └── 009-seed-synthetic.yaml
```

`liquibase.properties.j2` is rendered by the `database-setup` Ansible role from Ansible vars (which are themselves seeded from `.env` for local, or from Terraform outputs for cloud), with contexts `seed` / `noseed`.

Notes:

- Blockchain Table DDL (`CREATE BLOCKCHAIN TABLE ... NO DROP UNTIL 7 YEARS IDLE NO DELETE LOCKED HASHING USING "SHA2_512"`) lives in `003-app-decisioning.yaml` and is supported on both local Oracle Free 26ai and ADB 26ai.
- Seed data is behind a Liquibase context (`seed`) so the cloud deployment can opt out for an empty schema while local always seeds.
- Vector index settings (chunk size, overlap, similarity metric, refresh rate) are parameterised by `.env`-rendered tokens so the same changelog can serve different embedding choices without code edits.
- Schema drift between `oracle/` and `adb/` is kept minimal; where practical, the shared YAML files are symlinked or `includeAll`-ed to avoid duplicate maintenance.

## 6. Environment configuration

`.env` is the single source of truth for infrastructure values. It is generated by `manage.py setup local` or `manage.py setup cloud`, never edited by hand without re-running setup. Selected keys:

| Key                                                                                        | Purpose                                                   |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| `OCI_PROFILE`, `OCI_REGION`, `OCI_COMPARTMENT_OCID`                                        | Cloud only                                                |
| `OCI_GENAI_REGION`                                                                         | Future migration target; unused while Ollama is the model |
| `SSH_PUBLIC_KEY_PATH`, `SSH_PRIVATE_KEY_PATH`                                              | Cloud SSH                                                 |
| `GPU_SHAPE`, `MODEL_COMPUTE_OCPUS`, `MODEL_COMPUTE_MEMORY_GB`                              | Cloud GPU sizing                                          |
| `DB_MODE`                                                                                  | `local-free-26ai` or `adb`                                |
| `DB_HOST`, `DB_PORT`, `DB_SERVICE`, `DB_USER`, `DB_PASSWORD`                               | Local DB                                                  |
| `ADB_WALLET_PATH`, `ADB_CONNECT_STRING`                                                    | Cloud DB                                                  |
| `OLLAMA_HOST`, `OLLAMA_PORT`, `OLLAMA_LLM_MODEL`, `OLLAMA_EMBED_MODEL`, `OLLAMA_EMBED_DIM` | LLM + embedding pointers and choices                      |
| `OCR_HOST`, `OCR_PORT`, `OCR_ENGINE`                                                       | OCR pointer (local or LAN GPU host)                       |
| `PAF_HOST`, `PAF_PORT`, `PAF_ADMIN_USER`, `PAF_ADMIN_PASSWORD`                             | PAF bootstrap targets                                     |
| `PAF_AGENT_RUN_URL`, `PAF_LOGIN_VALIDATION_URL`                                            | Captured after `paf bootstrap`                            |
| `OPA_HOST`, `OPA_PORT`, `OPA_BUNDLE_DIR`                                                   | OPA service                                               |
| `BACKEND_URL`, `MOBILE_URL`, `BACKOFFICE_URL`                                              | UI surfacing                                              |

Policy values (DTI cap, score floor, Mandatory-HITL switch, OCR thresholds, fair-lending bucketing, confidence weights) do **not** live in `.env`. They live in `APP.system_config` and are edited from the Backoffice UI; every change is appended to `policy_parameter_history`.

## 7. Operational notes

- **OPA bundle reload on parameter change**: **deferred to v1**. In v0, OPA loads its bundle once at container start; parameter edits in the Backoffice still write `system_config` + `policy_parameter_history` (so the audit is complete) but require an OPA restart to take effect. v1 will add a reload-on-write trigger from the Application Service over the OPA REST API, with the side-by-side audit comparison shown in the demo script.
- **PAF session cookie handling**: per [PAF §15.2](PAF.md#152-cookie-based-call-from-shell) and [§16.4](PAF.md#164-apex-side-pattern), the AI Services PAF caller acquires `ahffi_session` (or the build-specific equivalent) via `loginValidation`, refreshes when it expires, and threads `roomId` for conversation continuity. The mobile and backoffice UIs never see the cookie.
- **TLS**: cloud uses a load-balancer-managed certificate; local uses self-signed via Caddy/nginx and the PAF caller is configured to bypass verification only when targeting `localhost`/`127.0.0.1`.
- **Backup**: out of scope for the PoC. Documented in the cloud playbook as a follow-up (ADB has built-in backups; local has none and is treated as ephemeral).

## 8. What is intentionally not specified yet

- Exact OCI compute shapes per role (chosen at `setup cloud` time; defaults in `manage.py` to be calibrated after first cloud demo).
- Exact OPA bundle layout vs `.rego` file layout (decided when the OPA MCP server is built).
- **`max_string_size=EXTENDED` enforcement on local Oracle Free 26ai** — required by PAF ([§5.1](PAF.md#51-supported-platforms-and-prerequisites)) but deferred from D1. Belongs as a podman init step / `ALTER SYSTEM ... SCOPE=SPFILE` + restart on first boot, **not** a Liquibase changeset (`sqlCheck` is a precondition, not a change). Track for D2 when PAF is added to the compose.
- Exact PAF flow JSON for the production `DECISIONING_AGENT` DAG (decided after `manage.py local up` is green and the in-DB Select AI tools exist; the v0 hello-world flow is a trivial `Chat Input → Prompt → LLM → Chat Output`).
- HITL assignment policy beyond "queue-claim".
- Backup, log retention, and monitoring beyond the audit-trail observability defined in [DESIGN.md §9](DESIGN.md#9-observability-model).

## 9. v0 milestone — "Hello agent"

The first deliverable, before any decisioning logic, is end-to-end platform wiring:

1. `python manage.py setup local` — writes `.env`.
2. `python manage.py local up` — brings up full Oracle Database Free 26ai, Ollama, PAF, and a thin reverse proxy. Calls `local provision` which runs the `database-setup` Ansible playbook against `localhost` to apply Liquibase `001-init.yaml` and grants.
3. `python manage.py paf bootstrap` — prints the checklist to register Ollama in LLM Management and to import the trivial `HELLO_AGENT` flow (`Chat Input → Prompt → LLM → Chat Output`) via the PAF UI.
4. `python manage.py info` — prints the agent run URL.
5. `curl` (or browser) hits the run URL and the agent answers using Ollama.

That is the v0 done-bar. OPA, OCR, Spring Boot backend, both Angular UIs, Select AI tools, Blockchain Table writes, and the decisioning DAG are all v1+ additions on top of this working foundation.
