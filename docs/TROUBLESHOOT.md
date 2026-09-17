# Troubleshooting

Validated workarounds for problems hit while running the PoC on OCI. One entry per symptom: **symptom → cause → fix**. Add new entries only after the fix has actually been verified — speculative advice belongs in a draft, not here.

Grouped by stack layer for findability.

- [Reaching the tiers](#reaching-the-tiers)
- [Sanity-check curls (PAF → tools / datasources)](#sanity-check-curls-paf--tools--datasources)
- [Oracle database](#oracle-database)
- [PAF install](#paf-install)
- [PAF runtime / MCP](#paf-runtime--mcp)
- [OPA](#opa)

PAF product bugs (as opposed to deployment workarounds) live in [`../issues/`](../issues/) instead — that folder is the backlog reported back to Oracle PAF Product Management.

## Reaching the tiers

Only the `ops` bastion has a public address; the other tiers are reached through it. `-J` does not carry `-i` to the jump hop, so name the key on both:

```bash
ssh -i ~/.ssh/id_rsa -o ProxyCommand="ssh -i ~/.ssh/id_rsa -W %h:%p opc@<ops_public_ip>" opc@backend.private.<vcn>.oraclevcn.com
```

The VCN DNS label is `OCI_LABEL` with the dashes removed, so `paf-poc` gives `paf.private.pafpoc.oraclevcn.com`. On the `paf` compute the container is named `paf`; on the `backend` compute every service is a systemd unit named `paf-poc-<service>`.

## Sanity-check curls (PAF → tools / datasources)

When an MCP server or HTTP datasource won't connect in PAF, check the layers from the outside in.

On the `backend` compute — does each service answer on the loopback the units address each other by?

```bash
curl -s http://127.0.0.1:8181/v1/data/decisioning/eligibility -H 'content-type: application/json' -d '{"input":{"applicant":{"age":34,"dti":0.41,"pti":0.18,"credit_score":642}}}'
```

Expect `{"result":{"allow":false,"deny":[],"warn":["Credit score 642 in caution band (< 670)"]}}`.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8503/mcp -X POST -d '{}' -H 'content-type: application/json'
```

Expect a 4xx with a JSON-RPC error — FastMCP rejecting the body means the wrapper is up. A timeout or connection refused means it is not.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8600/openapi.json
```

Expect 200. PAF reads that spec to expose `verify_employer` as a tool.

On the `paf` compute — does PAF complete the TLS handshake with the internal load balancer against its own trust store?

```bash
sudo podman exec paf curl -s -o /dev/null -w "%{http_code}\n" --cacert /mount/config/app/latest/certs/.agent-factory-ca/agent-factory-ca-bundle.pem https://<mcp_lb_ip>:8503/mcp -X POST -d '{}' -H 'content-type: application/json'
```

Expect a 4xx. `SSL certificate problem: self signed certificate` means the CA is not in the store — run `manage.py paf prepare`.

Logs on the `backend` compute:

```bash
sudo journalctl -u paf-poc-banking-mcp --since "10 min ago"
```

## Oracle database

### Liquibase changeset fails with `ORA-00903: invalid table name` on a plain identifier

The identifier is an Oracle reserved word. Common offenders: `SESSION`, `USER`, `DATE`, `LEVEL`, `SIZE`, `ORDER`, `GROUP`, `TYPE`, `NUMBER`, `ROWID`, `COMMENT`, `AUDIT`. Quoting (`CREATE TABLE BANK_CORE."SESSION"`) works but forces case-sensitive references forever after. The clean fix is to rename the table to a non-reserved identifier (e.g. `SESSION` → `AUTH_SESSION`, `USER` → `APP_USER`). Full reserved-word list in Oracle's SQL Language Reference.

If the failing changeset was never applied (`Run: 0` in Liquibase's update summary), it's safe to edit the changeset in place. If it was applied and you need to rename, write a new changeset that drops + recreates rather than editing the original — Liquibase checksum validation rejects in-place edits of applied changesets.

### Backend chat/history returns 500 with `ORA-18716: not in any time zone`

The Spring Boot backend's `/v1/chat` and `/v1/chat/history` fail the moment they _read_ a `TIMESTAMP` column (the write at login succeeds, so the symptom only shows up on the first read). Hibernate 6 maps `java.time.Instant` to the `TIMESTAMP_UTC` JDBC type by default, which makes the Oracle driver read plain `TIMESTAMP` columns (`AUTH_SESSION.created_at/expires_at`, `CHAT_MESSAGE.created_at`) as time-zone-aware values — and Oracle rejects that with ORA-18716. `src/backend/src/main/resources/application.yml` therefore pins the mapping:

```yaml
spring:
  jpa:
    properties:
      hibernate.type.preferred_instant_jdbc_type: TIMESTAMP
```

Hibernate logs a harmless `HHH90006001 ... incubating setting` warning for this key.

## PAF install

### PAF installer says `PAF_PLATFORM` is missing privileges, or "Test connection" returns 400 with `Unable to determine database compatibility level`

The `ops` tier has not finished applying the changelog — the grants live in `database/liquibase/001-users-and-grants.yaml` and the two prerequisites PAF's wizard checks (`SYS.V_$PARAMETER`, the read-only worker user) in `019-paf-install-prerequisites.yaml`. Wait for `/var/lib/paf-poc/bootstrap.ok` on the bastion, then retry the connection test.

### Model calls fail in PAF's LLM Management

Almost always the dynamic group or the policy: `manage.py cloud iam` was skipped, or the connection names a different compartment from the one the policy grants. Re-apply `deploy/tf/iam` with a tenancy-admin profile.

### A PAF command reports that the listener certificate does not verify

`manage.py` and the end-to-end harness check the public listener's certificate against `deploy/tf/app/generated/lb-ca.pem`, and `info` reports the sign-in as *the listener certificate does not verify*. The file is stale or missing — the listener's certificate renews 30 days before it expires, and the export is a Terraform `local_file`, so it only catches up on the next apply.

```bash
python manage.py cloud up
```

That rewrites the file from the certificate in state. A run from the bastion picks it up on the next `cloud test`, which copies it across.

### A scripted PAF command returns HTTP 401

`prepare`, `link-flow`, `gen-model` and `api-key` all sign in with `PAF_ADMIN_USER` / `PAF_ADMIN_PASS`. `setup` generates those before PAF exists and `paf bootstrap` step 1 prints them, so the wizard is meant to be *given* them rather than asked for something new. A 401 means the admin that exists is not the one in `.env`.

> **Only if the wizard was given different credentials** — otherwise the fix is to re-read step 1 and retype them. To record what actually exists:
>
> ```bash
> python manage.py paf admin
> ```
>
> It writes both values to `.env` and signs in once to prove they work.

## PAF runtime / MCP

### The manager never delegates — the reply is its thoughts plus `{"name": "send_message", …}`

**Symptom.** A `CHAT_FLOW` turn returns the manager's internal reasoning followed by a literal `{"name": "send_message", "parameters": {"message": "sess_…", "recipient": "Recommendation"}}`. The `banking-mcp` nodes all succeed; no worker runs and no `hitl_task` row is written. `manage.py cloud test` fails every scenario on the customer-facing reply. `agent_factory.log` shows `_managerworkersexecutor.py … Answering to user with content` with that text.

**Cause.** The generation model is a `cohere.*` one. The manager in a manager + sub-agents flow uses a text-based tool-calling template, and PAF's Cohere stream parser never applies the output parser that turns the text into a delegation (`wayflowcore/models/ocigenaimodel.py`, `_CohereOciApiFormatter`). See [`../issues/14-oci-genai-stream-parsers-incomplete.md`](../issues/14-oci-genai-stream-parsers-incomplete.md).

**Fix.** Use a generation model on OCI's generic format, `openai.gpt-oss-120b`: set `GENAI_MODEL` in `.env` and push it to the live install.

```bash
python manage.py paf gen-model
```

`manage.py setup` defaults to that model and warns before letting a `cohere.*` or `meta.*` one through.

### Every agent turn returns "Expecting value: line 1 column 2 (char 1)"

**Symptom.** A `CHAT_FLOW` turn returns that string as the customer-facing reply. The MCP tools all succeed and then the run dies.

**Cause.** The generation model is a `meta.*` one. Its stream ends with a bare `[DONE]` event, and PAF's generic stream parser runs `json.loads` on it. Same issue brief as above.

**Fix.** Same as above — `openai.gpt-oss-120b`, then `python manage.py paf gen-model`.

### Every MCP server fails its connection test with "Could not connect to the remote MCP server"

The wording points at reachability, but the failure is TLS verification. PAF's outbound HTTP client verifies against its **administrator certificate store**, not the container's OS trust store or `SSL_CERT_FILE`, so the internal load balancer's self-signed certificate has to be uploaded there once per install:

```bash
python manage.py paf prepare
```

Then re-run **Test connection** in the UI — the store is re-read per test, so no restart is needed. It applies to both MCP servers at once, since they share the one listener certificate.

The tell that it's trust and not reachability: the curl in [Sanity-check curls](#sanity-check-curls-paf--tools--datasources) succeeds from inside the PAF container with `-k` and fails without it.

### The first MCP server registration is rejected with "URL resolves to a private or non-routable network address"

PAF's outbound-URL guard, which the internal load balancer's 10.0.x.x address trips. The same command relaxes it — `prepare` does both halves of the post-wizard configuration, so running it for either symptom fixes the other too:

```bash
python manage.py paf prepare
```

### Flow runs to a "Sorry — we couldn't load..." reply but no errors in any wrapper logs

PAF's runtime traces for flow execution live inside the container under `/mount/log/app/latest/log/` — `agent_factory.log` for the manager/worker exchange and every MCP tool result, `state_manager.log` for step-level traces. `podman logs paf` only shows install and startup. When a Condition gate, agent tool call, or any other step misbehaves and the symptom is only visible in the customer-facing chat output, those are the files to grep.

The highest-signal lines, run on the `paf` compute:

```bash
sudo podman exec paf grep -E "ConditionStep evaluation|ConditionStep selected branch" /mount/log/app/latest/log/agent_factory.log | tail -10
```

Fields: `text_input=` the regex's input, `match_text=` the regex, `result=True|False`. Copy `text_input` verbatim and you have exactly what the regex evaluated against. If it's an error string from the agent, the upstream agent failed — chase the next grep.

```bash
sudo podman exec paf grep -E "New execution round|Calling agent|Answering back to manager|Answering to user" /mount/log/app/latest/log/agent_factory.log | tail -20
```

The manager → worker → manager exchange for each turn: what the manager sent, what the worker's tool returned, and what the customer read.

```bash
sudo podman exec paf grep -E "Tool named .* is not in the list of available tools" /mount/log/app/latest/log/agent_factory.log | tail -10
```

Two distinct meanings depending on the listed count:

- **List length matches the wired tools**: the tool name in the agent's Custom Instructions doesn't match what the runtime exposes. Common cause: PAF's OpenAPI importer auto-names HTTP tools `<METHOD>_<path>` regardless of `operationId` (see [`../issues/06-openapi-importer-ignores-operationid.md`](../issues/06-openapi-importer-ignores-operationid.md)). Fix the instructions to use the auto-name PAF actually exposes.
- **List length collapses to 1** (`['talk_to_user']` only): the agent hit PAF's hardcoded `max_iterations=5` cap. Wayflow strips all wired tools on the last iteration (see [`../issues/04-agent-max-iterations-5-cap.md`](../issues/04-agent-max-iterations-5-cap.md)). Fix: trim the recipe to ≤4 tool calls, or split the work across multiple agents.

## OPA

### OPA returns `404` on `/v1/data/decisioning/...` rules

A `.rego` file failed to load. On the `backend` compute, check `sudo journalctl -u paf-poc-opa` for a parse error (line number + message), fix the file under `opa/packages/`, then `manage.py build`, `manage.py cloud up` and `manage.py cloud redeploy backend`. The wrappers do not need a restart.
