# Troubleshooting

Validated workarounds for problems hit during local POC work. One entry per symptom: **symptom → cause → fix**. Add new entries only after the fix has actually been verified — speculative advice belongs in a draft, not here.

Grouped by stack layer for findability.

- [Sanity-check curls (PAF → tools / datasources)](#sanity-check-curls-paf--tools--datasources)
- [Host / podman](#host--podman)
- [Oracle database](#oracle-database)
- [PAF install](#paf-install)
- [PAF runtime / MCP](#paf-runtime--mcp)
- [OPA](#opa)

PAF product bugs (as opposed to local-deploy workarounds) live in [`../issues/`](../issues/) instead — that folder is the backlog reported back to Oracle PAF Product Management.

## Sanity-check curls (PAF → tools / datasources)

When an MCP server or HTTP datasource won't connect in PAF, check the layers from the outside in.

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

## Host / podman

### `no space left on device` during image pull

Re-point `TMPDIR` to a partition with at least 15 GB free, then `podman system reset` and retry:

```bash
export TMPDIR=/var/tmp
mkdir -p "$TMPDIR"
```

### Port 1521 already in use

Stop any existing Oracle client on the host, or edit `deploy/podman/compose.local.yml` to remap the port (e.g. `15210:1521`) and update `DB_PORT` in `.env`.

## Oracle database

### Oracle container never becomes healthy

The Oracle Database Free image initialises on first boot and can take 3–5 minutes. Tail the logs:

```bash
python manage.py local logs oracle-free-26ai
```

Look for `DATABASE IS READY TO USE!`.

### Liquibase fails with `ORA-01017: invalid username/password`

Your `.env`'s `DB_PASSWORD` no longer matches the password baked into the running container. Either edit `.env` to match the running container, or `local down --purge` and re-`local up` to start fresh.

### `liquibase: command not found` when running `local up`

Re-run `python manage.py setup local` to surface the prereq check, then install Liquibase per the prereqs table in [`../LOCAL.md`](../LOCAL.md#prereqs).

### Liquibase changeset fails with `ORA-00903: invalid table name` on a plain identifier

The identifier is an Oracle reserved word. Common offenders: `SESSION`, `USER`, `DATE`, `LEVEL`, `SIZE`, `ORDER`, `GROUP`, `TYPE`, `NUMBER`, `ROWID`, `COMMENT`, `AUDIT`. Quoting (`CREATE TABLE APP."SESSION"`) works but forces case-sensitive references forever after. The clean fix is to rename the table to a non-reserved identifier (e.g. `SESSION` → `AUTH_SESSION`, `USER` → `APP_USER`). Full reserved-word list in Oracle's SQL Language Reference.

If the failing changeset was never applied (`Run: 0` in Liquibase's update summary), it's safe to edit the changeset in place and re-run `local up`. If it was applied and you need to rename, write a new changeset that drops + recreates rather than editing the original (Liquibase checksum validation will reject in-place edits of applied changesets).

### Backend chat/history returns 500 with `ORA-18716: not in any time zone`

The Spring Boot backend's `/v1/chat` and `/v1/chat/history` fail the moment they _read_ a `TIMESTAMP` column (the write at login succeeds, so the symptom only shows up on the first read). Hibernate 6 maps `java.time.Instant` to the `TIMESTAMP_UTC` JDBC type by default, which makes the Oracle driver read our plain `TIMESTAMP` columns (`AUTH_SESSION.created_at/expires_at`, `CHAT_MESSAGE.created_at`) as time-zone-aware values — and Oracle rejects that with ORA-18716. Fix: tell Hibernate to read/write `Instant` as a plain `TIMESTAMP` in `src/backend/src/main/resources/application.yml`:

```yaml
spring:
  jpa:
    properties:
      hibernate.type.preferred_instant_jdbc_type: TIMESTAMP
```

(Hibernate logs a harmless `HHH90006001 ... incubating setting` warning for this key — expected.) Rebuild the backend image and recreate the container so it picks up the change — `up -d --build` alone does not always swap a running container onto the freshly built image, so force it:

```bash
podman compose -f deploy/podman/compose.local.yml build backend
podman compose -f deploy/podman/compose.local.yml up -d --force-recreate --no-deps backend
```

## PAF install

### `local up` errors with `image not known: localhost/applied-ai-label:…`

`PAF_APP_VERSION` is set in `.env` but the image hasn't been built (or you cleared podman storage). Run `python manage.py paf build`, or just re-run `local up` — it builds on demand.

### PAF UI installer can't reach the database

The installer must use the service name `oracle-free-26ai` as the host, not `localhost` — `localhost` inside the PAF container points at the PAF container itself. Both containers share the project network so Oracle resolves by service name.

### PAF installer says `AGENT_FACTORY` is missing privileges, or "Test connection" returns 400 with `Unable to determine database compatibility level`

Make sure Liquibase ran (`python manage.py local provision`). The Liquibase grants live in `database/liquibase/oracle/001-users-and-grants.yaml` (from the PAF kit README); the one extra grant on `SYS.V_$PARAMETER` is applied by `manage.py local provision` as sysdba (SYSTEM cannot grant it, hence Liquibase can't).

### PAF logs loop forever on `Waiting for correct permissions to be set to mounted volume...` then exit

The kit's startup script polls for `/mount/.config_complete.marker` (a host-side handshake the kit's own `deploy.sh` would otherwise create with `podman exec ... touch`). `local up` writes it automatically; if you brought PAF up manually, create it yourself:

```bash
touch paf-kit/applied-ai/volume/.config_complete.marker
```

## PAF runtime / MCP

### Newly added MCP service shows "Unable to reach the MCP server URL" in PAF after `local up`

`manage.py local_up()` passes an **explicit list** of services to `podman compose up -d --build` (see the `services = [...]` array in the function). If a new service is added to `deploy/podman/compose.local.yml` but not to that list, `local up` silently skips building / starting it — PAF can't reach the URL because the container doesn't exist. Add the new service name to the array and re-run `local up`. Quick one-off fix without re-running the whole `local up`:

```bash
podman compose -f deploy/podman/compose.local.yml up -d --build <service>
```

### PAF MCP discovery for `opa-mcp` or `ocr-mcp` returns 0 tools, or "connection refused"

Most common cause is using `localhost` instead of `opa-mcp` / `ocr-mcp` in the URL — PAF must reach the wrapper over the compose network, not the host. Confirm with:

```bash
podman exec paf-agent-factory getent hosts opa-mcp   # should print the container IP
podman exec paf-agent-factory getent hosts ocr-mcp   # same
```

If the address resolves but tool discovery still fails, run the [Sanity-check curls](#sanity-check-curls-paf--tools--datasources) above. The second most common cause is a network mismatch from rebuilding the container with `-p paf` — see the rebuild snippet in [`../LOCAL.md` §Day-2](../LOCAL.md#day-2).

### Flow runs to a "Sorry — we couldn't load..." reply but no errors in any wrapper logs

PAF's runtime traces for flow execution live inside the container at `/mount/log/app/latest/log/state_manager.log` (not in `podman logs paf-agent-factory`, which only shows install/startup). When a Condition gate, agent tool call, or any other step misbehaves and the symptom is only visible in the customer-facing chat output, that's the file to grep.

The two highest-signal lines:

```bash
# What the Condition node actually evaluated and which branch it picked.
podman exec paf-agent-factory grep -E "ConditionStep evaluation|ConditionStep selected branch" \
  /mount/log/app/latest/log/state_manager.log | tail -10
# Fields: text_input=<the regex's input>, match_text=<the regex>, operator=<...>, result=True|False

# Tool-call rejections from the agent executor — exact tool name + the list the runtime saw.
podman exec paf-agent-factory grep -E "Tool named .* is not in the list of available tools" \
  /mount/log/app/latest/log/state_manager.log | tail -10
```

What each tells you:

- **`ConditionStep evaluation: text_input=...`** — copy `text_input` verbatim and you have exactly what the regex evaluated against. If it's the expected Evidence block but the regex doesn't match, the regex is wrong. If it's an error string from the agent ("Tool named X is not in the list..."), the upstream agent failed — chase the second grep.
- **`Tool named X is not in the list of available tools. Available tools: [...]`** — two distinct meanings depending on the listed count:
  - **List length matches the wired tools** (e.g. 10 entries for opa-mcp's 7 + banking-mcp's 1 + registry's 1 + `talk_to_user`): the tool name in the agent's CI doesn't match what the runtime exposes. Common cause: PAF's OpenAPI importer auto-names HTTP tools `<METHOD>_<path>` regardless of `operationId` (see [`../issues/04-openapi-importer-ignores-operationid.md`](../issues/04-openapi-importer-ignores-operationid.md)). Fix the CI to use the auto-name PAF actually exposes.
  - **List length collapses to 1** (`['talk_to_user']` only): the agent hit PAF's hardcoded `max_iterations=5` cap. Wayflow strips all wired tools on the last iteration (see [`../issues/03-agent-max-iterations-5-cap.md`](../issues/03-agent-max-iterations-5-cap.md)). Fix: trim the recipe to ≤4 tool calls, or split the work across multiple agents.

## OPA

### OPA returns `404` on `/v1/data/decisioning/...` rules

A `.rego` file failed to load. Check `podman logs paf-opa` for a parse error (line number + message), fix the file under `opa/packages/`, and `podman restart paf-opa`. The wrapper does not need a restart.
