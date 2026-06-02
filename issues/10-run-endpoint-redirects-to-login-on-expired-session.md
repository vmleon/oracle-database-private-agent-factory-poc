# `agentBuilder/run` returns a 303 redirect to an HTML login page on an expired session (not 401 JSON)

## What

The programmatic run endpoint `POST /agentFactory/v1/agentBuilder/run/{agentId}` is authenticated by the `agent_factory_session` cookie obtained from `GET /agentFactory/v1/loginValidation`. When that cookie has **expired**, the run endpoint does not return a machine-readable `401 Unauthorized` with a JSON error. Instead it returns a **`303 See Other` redirecting to `/agentFactory/login`**, which (if redirects are followed) chains to the HTML dashboard (`GET /agentFactory/ → 200`, an HTML page).

An API client therefore receives **HTML with a 200**, not a 401 — so naive auth-refresh logic keyed on 401 never fires, and JSON parsing of the "run result" fails. The session cookie appears to age out at roughly **30 minutes**.

## Reproduce

1. Authenticate (`loginValidation`), cache the cookie, and drive `agentBuilder/run` successfully.
2. Wait ~30 min (or present a stale/garbage `agent_factory_session` cookie) and call `agentBuilder/run` again.
3. Observe (nginx access log):
   ```
   POST /agentFactory/v1/agentBuilder/run/<id>  303 225
   GET  /agentFactory/login                      303 215
   GET  /agentFactory/                           200 1366   (HTML)
   ```
   A direct probe with a garbage cookie returns `HTTP/1.1 303 See Other`, `Location: /agentFactory/login`, `Content-Type: text/html`.

## Source confirmation

Behavior observed against the running PAF container (`POST .../agentBuilder/run` with an invalid `agent_factory_session` cookie → `303 → /agentFactory/login`). The endpoint is a session/cookie-guarded web route that redirects unauthenticated requests to the login page rather than answering API clients with `401 application/json`.

## Why it matters

- Any long-lived API integration (our Spring backend) **starts failing every turn after ~30 min** until restarted, because the standard "refresh auth on 401" pattern never triggers — the response is a 303/HTML 200, not a 401.
- Returning HTML to a JSON API endpoint forces clients to sniff the body ("is this JSON?") to detect expiry — brittle and undocumented.
- Related ergonomics: the run endpoint is **synchronous and slow** (a 4-agent `CHAT_WORKFLOW` turn takes 200–255s), with no async/polling option, forcing very long client socket timeouts (we raised ours to 8 min). A clean auth contract matters more when each call is multi-minute.

## Workaround currently in use

Backend `PafClient` now treats a **non-JSON run response** as "session expired" → drops the cached cookie, re-logs in, and retries once; it also disables the HTTP client's automatic cookie store so a stale cookie can't be replayed over the re-login. See `src/backend/.../chat/PafClient.java` (`postRunWithSessionRetry` / `looksLikeJson`) and `PafClientConfig.java`. Verified self-healing live across the 30-min boundary.

## Suggested fix

1. For `v1/agentBuilder/*` (the documented API surface), return **`401 Unauthorized` with a JSON body** on missing/expired session instead of a `303` to the HTML login page. API clients can then refresh auth on the standard signal.
2. Optionally document the session cookie TTL and provide a lightweight session-keepalive or token-refresh endpoint for long-lived integrations.
