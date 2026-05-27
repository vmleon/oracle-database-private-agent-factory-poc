# Agent Builder has no flow-export endpoint or UI button

## What

PAF's Agent Builder canvas top bar shows `Save`, `New Flow`, `Playground`, `Publish` — but no **Export** option. The kit's `agent_builder_blueprint.py` exposes a `POST .../v1/agentBuilder/importAgentIrFlow` route (you can import a flow JSON) but **no symmetric export route**. The asymmetry is undocumented.

The flow definition IS reachable via the same internal endpoint the SPA uses to load the canvas — `GET /agentFactory/v1/agents/<agent_id>` — which returns the full agent record (edges, nodes, custom instructions, all node config). But:

- That endpoint isn't surfaced as "export" anywhere in the UI.
- The `agent_id` (Oracle `RAW(16)` hex, e.g. `52CFF6D1A1380A43E0630200590A72A7`) is not in the canvas URL — the SPA hash-routes to `/agentFactory/#/home/agentBuilder` with no ID component — so the operator has to scrape it from DevTools Network traffic before they can build the export URL.

In practice, capturing a flow for version control means: open DevTools → Network → filter Fetch/XHR → open the flow → find the response whose body contains `edges` + `nodes` → Copy → Copy response → paste into a file.

## Reproduce

1. Open the Agent Builder canvas with any non-trivial flow.
2. Scan the top toolbar — `Save`, `New Flow`, `Playground`, `Publish`. No Export.
3. Look at the URL — `https://localhost:8080/agentFactory/#/home/agentBuilder`. No `agent_id`.
4. Grep the kit for any export endpoint:

   ```bash
   grep -nE "export.*Flow|exportAgent|/export" paf-kit/applied-ai/kit/agent_factory/app/blueprints/agentBuilder/agent_builder_blueprint.py
   # returns nothing
   ```

5. The only path to the JSON is DevTools Network inspection, as documented in the workaround.

## Source confirmation

`paf-kit/applied-ai/kit/agent_factory/app/blueprints/agentBuilder/agent_builder_blueprint.py`:

- L544 `@agent_builder_blueprint.route("/v1/agentBuilder/importAgentIrFlow", methods=["POST"])` — the import endpoint exists.
- No `export*` route is defined anywhere in the file (grep returns zero matches).
- L442 `@agent_builder_blueprint.route("/v1/agents/<agent_id>", methods=["GET"])` — returns the full agent record; this is what the SPA fetches when loading the canvas, and what the workaround scrapes.

The SPA routes for the builder are hash-only — see any `Agentagent_factoryLayout.tsx` / `MainSideNavigation.tsx` reference; no `agent_id` URL parameter exists for the canvas view.

## Portability defect — flow JSON pins dependencies by install-specific integer ID

Even when the JSON is captured successfully via the workaround, it is **not portable across PAF installs**. The Agent Builder node config references MCP servers and HTTP datasources by **internal auto-incremented integer**, not by name or URL:

```jsonc
// Inside an MCP server node:
"serverSource": { "value": 4, ... }

// Inside a REST API tools node:
"src_select":   { "value": 1, ... }
```

Those integers are the primary keys PAF assigns when the operator registers each MCP server or datasource in the admin UI. They depend on **insertion order** on the source install. The actual `http://opa-mcp:8500/mcp/` URL of the referenced MCP server is **not** included in the export — only the ID pointing at it.

Consequences on a clean redeploy or migration:

- Best case — the operator happens to register MCP servers and datasources in the exact same order as the source install. IDs line up. Flow works untouched.
- Realistic case — any drift in registration order (operator follows a slightly different runbook, a service was registered separately and then deleted, etc.). The imported flow now wires the agent to either a non-existent ID (the node's dropdown shows empty) or to the **wrong server** (the integer happens to match a different registered MCP). The flow validates and runs; the agent silently calls the wrong tools.

The export is therefore an artifact, not a portable specification. Two flows exported from two PAF installs that wire the same MCP servers will not be byte-identical, and either one re-imported on the other install would point at the wrong tools.

## Why it matters

- **Flows can't be versioned in git without a manual scrape per export.** Repeatable deployments are an explicit goal of any production agentic platform; without a one-click export, the canvas is the source of truth, and the canvas is mutable shared state. We hit this directly in our POC: during a clean redeploy after a model swap, the canvas rebuild used a stale Custom Instructions block, causing four scenarios to silently fail with fabricated tool responses (see `paf/flows/CHAT_WORKFLOW.md` — the `verify_employer` → `GET_v1_companies_verify` retake). A clean export + diff workflow would have caught the drift before testing.
- **The asymmetry with `importAgentIrFlow` looks like an oversight.** Import without export means flows can be deployed from JSON but never round-tripped. That's not a coherent lifecycle.
- **The Network-tab scrape is fragile.** It depends on the operator knowing which response carries the graph (multiple XHRs fire when the canvas loads), and on the SPA's internal URL shape not changing between PAF versions.
- **Operators can't safely back up a flow before edits.** A single misclick (delete a wire, paste over a CI) is permanent unless you remembered to scrape the JSON first.

## Workaround currently in use

Documented in `paf/flows/CHAT_WORKFLOW.md §Export`. The captured artifact for this POC lives at [`paf/flows/chat_workflow.flow.json`](../paf/flows/chat_workflow.flow.json). Re-import on a clean deploy is still manual — the symmetric `importAgentIrFlow` endpoint accepts the same shape, but the round-trip isn't wired into `manage.py` yet (listed as a follow-up).

## Suggested fix

1. **Add a symmetric `GET /v1/agentBuilder/exportAgentIrFlow/<agent_id>` endpoint** that returns the same body shape `importAgentIrFlow` accepts.
2. **Replace install-specific integer IDs with stable identifiers in the exported shape.** For MCP servers reference the URL (e.g. `http://opa-mcp:8500/mcp/`); for HTTP datasources reference the OpenAPI spec hash or registered name. Import then resolves the stable identifier back to whatever local ID it has on the target install. Without this, fix (1) alone produces non-portable exports.
3. **Surface an Export option in the canvas top bar.** Fits naturally in a `⋮` overflow menu next to `Save / New Flow / Playground / Publish`.
4. **Expose `agent_id` in the canvas URL** (e.g. `/agentFactory/#/home/agentBuilder/<agent_id>`) so operators can share / bookmark / scrape it without DevTools.
5. **Strip mutable inline values from export by default** — at minimum the Text Input `input_text.value` field, which captures whatever literal string was typed in last (a real session token, in production). Optionally a `?withInlineValues=true` flag for the rare case the operator wants them.

(1) + (2) together are the minimum useful change; (1) alone produces JSON that imports successfully but silently mis-wires.
