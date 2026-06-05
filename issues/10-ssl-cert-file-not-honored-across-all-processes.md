# `SSL_CERT_FILE` is not propagated to all PAF processes, so a custom CA isn't trusted for MCP/outbound TLS

**Severity: low** — a workaround exists (append the CA to `certifi`'s bundle). But the standard, documented way to add a private CA (`SSL_CERT_FILE`) silently fails for part of PAF, which is surprising and hard to diagnose.

## What

PAF 26.4 requires **https** for MCP server URLs (and blocks private-network URLs), so an on-prem deployment must front internal MCP servers with TLS using a **private / self-signed CA** and tell PAF to trust it. The conventional mechanism is the `SSL_CERT_FILE` environment variable (a CA bundle path), which the vendored `httpx` honors.

Setting `SSL_CERT_FILE` on the PAF container is **only partially effective**: some PAF processes inherit it, others do not. The process that performs **MCP tool discovery / the connection test** runs without it, so it falls back to `certifi`'s bundle (which has no private CA) and the TLS handshake fails. The MCP server shows **"disconnected"** and the connection test returns the misleading message _"Unable to reach the MCP server URL. Please verify host/port/path and network accessibility."_ — even though the host is fully reachable.

## Reproduce

1. Front an MCP server with TLS using a self-signed cert (e.g. a Caddy gateway), so its URL is `https://<gateway>/<svc>/mcp`.
2. Build a CA bundle = `certifi` + the self-signed cert, mount it into the PAF container, and set `SSL_CERT_FILE=/path/to/bundle` (via compose `environment:`).
3. Register the MCP server in PAF → **connection test fails**.
4. Inspect the real error:
   ```
   tail -40 /mount/log/app/latest/log/agent_factory.err
   # httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
   #   self-signed certificate (_ssl.c:1010)
   ```
5. Confirm the env-var is present on some PAF processes but not others:
   ```bash
   for p in $(pgrep -f "asgi|gunicorn|uvicorn|agent_factory"); do
     printf "pid %s: " "$p"; tr '\0' '\n' </proc/$p/environ | grep -E '^SSL_CERT_FILE=' || echo NONE
   done
   # mixed: some print SSL_CERT_FILE=..., at least one prints NONE — and the
   # MCP-discovery worker is one of the NONE processes.
   ```
6. Proof it's purely env propagation (not the client code): in a process that _does_ have the var, an `httpx.post(...)` to the same URL succeeds (HTTP 200); with `SSL_CERT_FILE` unset it fails with the same `CERTIFICATE_VERIFY_FAILED`.

## Source confirmation

- The vendored `httpx` **does** honor the variable — `agent_factory/third_party/.../httpx/_config.py:34-35`:
  ```python
  if trust_env and os.environ.get("SSL_CERT_FILE"):
      ctx = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
  # else: ctx = ssl.create_default_context(cafile=certifi.where())   # :40
  ```
- The MCP client code uses **default** `verify` / `trust_env` (so it _would_ honor `SSL_CERT_FILE` if present):
  - `app/models/MCPClient.py:151,344` — `httpx.Client(auth=auth, timeout=...)`, no `verify=`/`trust_env=`.
  - `mcp/shared/_httpx_utils.py` `create_mcp_http_client(...)` → `httpx.AsyncClient(**kwargs)`, no `verify=`/`trust_env=`.
- So the clients are correct; the defect is that PAF does not export `SSL_CERT_FILE` into the environment of every worker/daemon it spawns. The failing handshake is logged at `/mount/log/app/latest/log/agent_factory.err` (and `agent_factory.log`).

## Why it matters

- Adding a private/internal CA is a routine on-prem requirement (TLS-fronted MCP servers, corporate TLS-intercepting proxies, internal registries). `SSL_CERT_FILE` is the standard, least-invasive way to do it.
- Because it works for _part_ of PAF, it's a confusing partial failure: a manually-run probe inside the container succeeds, the URL is reachable, yet the UI says "unable to reach" — pointing operators at the network/URL instead of the trust store.
- There is no UI/setting to register a custom CA, so operators are pushed to patch files inside the image.

## Workaround currently in use

Append the private CA to the bundle `certifi.where()` returns — the one trust store **every** `httpx` client falls back to regardless of environment:

```
.../site-packages/certifi/cacert.pem   # inside the PAF image
```

Because it lives in the image (not a bind mount), it must be re-applied whenever the container is recreated. Automated in this repo as `_inject_mcp_ca_into_paf()` in `manage.py` (runs on every `local up` and on `local mcp-tls`).

## Suggested fix

1. **Propagate `SSL_CERT_FILE` (and `SSL_CERT_DIR` / `REQUESTS_CA_BUNDLE`) to every process PAF spawns** — the WSGI/ASGI servers and their workers, and the ingestion/consumer daemons — not just the parent. A single source-of-truth env file read by all launchers would do it.
2. **Or** add a first-class "custom CA bundle" / "trusted certificates" setting (a path or paste-in PEM) that all PAF HTTP clients load explicitly, independent of process environment.
3. Improve the error: distinguish a **TLS trust failure** (`CERTIFICATE_VERIFY_FAILED`) from an actual connectivity failure, instead of collapsing both into _"Unable to reach the MCP server URL."_ — the two have completely different fixes.
