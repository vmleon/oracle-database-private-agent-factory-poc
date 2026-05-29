# Backend Chat Slice — Re-deploy & Smoke Test

Pick-up guide for end-to-end testing the Spring Boot Application Service (customer chat slice).

## Where things stand

- Branch: **`feat/backend-chat-slice`** (not merged).
- Code is complete: 9 implementation tasks, **25 unit tests passing**, each task spec- and quality-reviewed, final whole-branch review fixes applied.
- **Not yet validated end-to-end** against the live PAF + Oracle + vLLM — that is what this guide does.
- Reference: spec `docs/superpowers/specs/2026-05-28-spring-boot-chat-slice-design.md`, plan `docs/superpowers/plans/2026-05-28-spring-boot-chat-slice.md` (Task 10 = this smoke).

## Prerequisites (confirm before testing)

- [ ] On the branch: `git checkout feat/backend-chat-slice`
- [ ] `.env` has `DB_PASSWORD`, `PAF_ADMIN_USER`, `PAF_ADMIN_PASS` (from `python manage.py setup local`)
- [ ] vLLM GPU host up (gen `:8000`, embed `:8001`) — PAF needs it to run `CHAT_WORKFLOW`
- [ ] `CHAT_WORKFLOW` built & **published** in PAF (per `paf/flows/CHAT_WORKFLOW.md`). Optional: set `CHAT_WORKFLOW_AGENT_ID` in `.env` to skip auto-discovery
- [ ] Seed data loaded (Liquibase `001`–`011`), including seeded customers with open applications

## Step 1 — Re-deploy (builds + starts the backend container)

```bash
python manage.py local up
```

- This builds the backend image (`src/backend/Dockerfile`) and starts `paf-backend` with the stack (`--build`).
- Verify: `podman ps | grep paf-backend` → running.
- If a code change isn't picked up: `podman compose -f deploy/podman/compose.local.yml build backend && python manage.py local up`.

## Step 2 — Health

```bash
curl -s http://localhost:8090/actuator/health
```

Expect `{"status":"UP"}`. If down: `podman logs paf-backend`. Likely causes:

- Oracle UCP property keys / starter version → check `src/backend/src/main/resources/application.yml` (`spring.datasource.oracleucp.*`).
- DB not healthy yet → wait for the `oracle-free-26ai` healthcheck.
- Wrong `DB_PASSWORD` / can't connect as `APP`.

## Step 3 — List demo customers

```bash
curl -s http://localhost:8090/v1/customers | python -m json.tool
```

Expect an array of seeded customers with open applications (e.g. Kyle = customer 11 / application 10). If empty: confirm seed `010` ran and applications are in `DRAFT`/`SUBMITTED`/`IN_REVIEW`.

## Step 4 — Login (mint a session token)

```bash
curl -s -X POST http://localhost:8090/v1/login \
  -H 'Content-Type: application/json' -d '{"customerId":11}' | python -m json.tool
```

Expect `{ "sessionToken": "sess_...", "customerId": 11, "applicationId": 10, "roomId": "room-app-10" }`.

```bash
export TOKEN=sess_...   # paste the sessionToken from above
```

## Step 5 — Chat turn (the key validation)

```bash
curl -s -X POST http://localhost:8090/v1/chat \
  -H 'Content-Type: application/json' -H "X-Session-Token: $TOKEN" \
  -d '{"message":"I would like to proceed with my loan application"}' | python -m json.tool
```

Expect `{ "reply": "<agent closing sentence>", "agentRunId": null }`. vLLM (72B) can take 60–90s — be patient.

### ⚠️ Watch-item (final-review Issue #3): the reply field

If `reply` is empty or a raw JSON blob instead of the agent's sentence, the live PAF run-response shape differs from `Envelope.extractReply`'s field guesses (`data`-as-string, then `message`/`content`/`reply`/`output`/`text`, then `data.toString()`). To fix:

1. Capture the real response shape by calling PAF directly:
   ```bash
   # get the session cookie (note the Set-Cookie name from the -i headers)
   curl -k -i -u "$PAF_ADMIN_USER:$PAF_ADMIN_PASS" https://localhost:8080/agentFactory/v1/loginValidation
   # find the agentId
   curl -k -s -H "Cookie: <name>=<value>" https://localhost:8080/agentFactory/v1/agents | python -m json.tool
   # run it and inspect the JSON
   curl -k -s -X POST "https://localhost:8080/agentFactory/v1/agentBuilder/run/<agentId>" \
     -H 'Content-Type: application/json' -H "Cookie: <name>=<value>" \
     -d '{"message":"[[SESSION '"$TOKEN"']]\nhello"}' | python -m json.tool
   ```
2. Note which JSON field holds the agent's text.
3. Update `src/backend/src/main/java/com/paf/backend/chat/Envelope.java` `extractReply` to read that field; update `EnvelopeTest` with a sample of the real shape; drop the `data.toString()` fallback.
4. Re-verify: `cd src/backend && ./gradlew test`, then `python manage.py local up`.

(Paste me the captured shape and I'll make the fix.)

## Step 6 — History replay

```bash
curl -s http://localhost:8090/v1/chat/history -H "X-Session-Token: $TOKEN" | python -m json.tool
```

Expect the `CUSTOMER` message then the `AGENT` reply, in order. (Confirms persistence + that the CLOB `body` read works under `open-in-view: false`.)

## Step 7 — Fail-secure

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8090/v1/chat \
  -H 'Content-Type: application/json' -H 'X-Session-Token: bogus' -d '{"message":"hi"}'
```

Expect `401`.

## After the smoke passes

- If `extractReply` needed a fix, commit it: `git add src/backend/src/main/java/com/paf/backend/chat/Envelope.java src/backend/src/test/java/com/paf/backend/chat/EnvelopeTest.java && git commit -m "fix(backend): align PAF reply parsing with live response shape"`.
- Decide how to finish the branch: merge `feat/backend-chat-slice` → `main`, or open a PR. (No push/merge without your go-ahead.)
- Open decision: gate `/v1/login` + `/v1/chat` behind `@Profile("local")`? The mock login is passwordless by design; this only matters if the service is ever exposed beyond the local stack (a flagged-but-accepted security tradeoff).

## Known limitations (by design — not bugs)

- **Mock login**: passwordless, `customerId` from the request body. Auth is out of scope for the PoC; production is assumed to sit behind the host system's auth.
- **No application intake**: only customers with an existing open application can chat. The conversational greeting/intake agent is the documented next step (spec §15).
- **TLS to PAF not verified**: PAF's self-signed cert is trusted and hostname verification is off — POC-only, scoped to the single PAF `RestClient` bean.

## Key files

- `src/backend/src/main/java/com/paf/backend/` — `chat/` (Envelope, PafClient, PafClientConfig, ChatService, ChatController), `login/` (SessionService, LoginService, LoginController), `domain/` (entities + repos), `api/Dtos.java`
- `src/backend/src/main/resources/application.yml` — config (env-driven)
- `src/backend/Dockerfile`, `deploy/podman/compose.local.yml` (the `backend` service), `manage.py` (services list + `info`)
