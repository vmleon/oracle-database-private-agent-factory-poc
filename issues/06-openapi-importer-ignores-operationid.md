# OpenAPI importer ignores `operationId`, auto-names tools as `<METHOD>_<path>`

## What

When importing an OpenAPI spec as an HTTP datasource, PAF's parser never reads each operation's `operationId`. Instead it generates the tool name from the HTTP method + path (with slashes replaced by underscores), e.g. `GET_v1_companies_verify`. The `operationId` field is part of the OpenAPI 3.x standard for exactly this purpose ("Unique string used to identify the operation. The id MUST be unique among all operations described in the API. Tools and libraries MAY use the operationId to uniquely identify an operation..."), so the spec-author's chosen name is silently dropped.

This is confusing because:

- The agent's Custom Instructions naturally reference the descriptive name set in the spec (`verify_employer`).
- The runtime then rejects the call with `Tool named verify_employer is not in the list of available tools.`
- The available-tools list shows `GET_v1_companies_verify` instead, with no indication that this came from the same spec.
- Users have no way to influence the tool name short of restructuring the URL path.

In our `CHAT_WORKFLOW`, this caused the model to waste an iteration calling the spec's `operationId` name, then retry with the auto-name. The wasted iteration combined with the [[04-agent-max-iterations-5-cap]] to push the next tool call into the "tools stripped" last iteration, producing a misleading "tool not available" error for a tool that was actually wired correctly.

## Reproduce

1. FastAPI route (`src/api/registry/main.py`):

   ```python
   @app.get("/v1/companies/verify", operation_id="verify_employer", ...)
   def verify_employer(name: str = Query(...)) -> CompanyRecord:
       ...
   ```

2. Dump the spec and verify the operationId is present:

   ```bash
   curl -s http://registry-api:8600/openapi.json | grep -o '"operationId":"[^"]*"'
   # "operationId":"verify_employer"
   ```

3. PAF: **Data Sources** → **Add new data source** → **Rest API → OpenAPI specification** → upload the spec.
4. Wire the resulting REST tool into an Agent node. Inspect the agent's available tool list (e.g. via the error message produced when the model calls a tool that doesn't exist, or via `state_manager.log`'s `ConversationMessageAddedEvent` entries).
5. The exposed tool name is `GET_v1_companies_verify`, not `verify_employer`.

## Source confirmation

`paf-kit/applied-ai/kit/agent_factory/app/util/openapi_parser.py`, in the path-extraction loop (L220-309) for both GET and POST operations:

- The dict assembled for each endpoint includes `endpoint`, `tag`, `method`, `summary`, `description`, `details` (parameters, consumes, produces, responses).
- `operationId` is never referenced — neither read from the spec nor stored.
- Tool name derivation downstream falls back to `{method}_{path-with-underscores}`.

## Suggested fix

1. Read `operationId` from each operation in `_extract_endpoints` and pass it through as the canonical tool name when present.
2. Fall back to `{method}_{path}` only when `operationId` is missing.
3. Refuse imports where two operations share the same `operationId` (the OpenAPI spec already requires uniqueness, so this is just enforcing it).

## Workaround until fixed

Either:

- Update the Custom Instructions in the consuming Agent to call the auto-name (`GET_v1_companies_verify`) instead of the spec's `operationId`. Brittle — couples the agent's recipe to a PAF-internal naming convention, breaks if PAF ever changes auto-naming.
- Reshape the URL path so the auto-name is readable, e.g. `/verify_employer` → tool `GET_verify_employer`. Couples the REST API design to PAF's auto-naming, but no agent-side change needed.
