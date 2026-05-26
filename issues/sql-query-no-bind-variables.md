# SQL Query node ignores `:bind` variables in inline query

## What

The Agent Builder SQL Query node hardcodes `params = {}` and exposes no UI for providing bind values. A query containing `:name` placeholders fails at runtime — Oracle receives the literal string `:name`. There is no per-bind input port on the node and no flow-level Variables / Inputs panel anywhere in the canvas.

## Reproduce

1. Agent Builder → add an **SQL Query** node, pick any database datasource.
2. Paste:
   ```sql
   SELECT * FROM some_table WHERE id = :customer_id
   ```
3. Add a **Text Input** node with value `1`. Try to wire it to a `:customer_id` port on the SQL Query node — **no such port exists**. The only input port on SQL Query is `query`, and wiring it _replaces the entire SQL text_.
4. Run the flow → error: `"Wrong query, error occurred"` (Oracle sees unbound `:customer_id`).

## Source confirmation

`agent_factory/app/models/agentBuilder/steps/customSteps/SelectSQLQueryNode.py`:

- L179 `params = {}` (hardcoded empty bind dict)
- L235 `db_client.exec_query(full_query, data=params)` (passes the empty dict)
- L259-264 `input_descriptors` declares one port `query` that overrides the inline SQL
- `get_ui_json` (L287+) defines only `database`, `columns`, `query` — no Variables / Inputs panel

The underlying Wayflow runtime `DatastoreQueryStep` already supports `:name` binds. PAF's `SelectSQLQueryNode` wraps it as a `ServerTool` with an empty `data` dict and discards that capability.

## Why it matters

Looking up initial data by an authenticated user id or record id is the first step of virtually any data-driven workflow. Without bind variables the SQL Query node can only execute constant queries, forcing every team to either:

- inline IDs into the SQL string upstream (loses bind-variable safety, opens injection risk the moment any caller-supplied value reaches the template), or
- wrap the query in an MCP tool just to parameterise it (defeats the purpose of the built-in SQL Query node).

## Severity — silent fail-open data exposure

The bigger problem: with the Prompt-template workaround above, **a missing or wrong substitution does not fail loudly — it leaks another customer's record**.

Concrete repro:

1. Wire two Text Input nodes with placeholder text (e.g. literally `customer_id` and `application_id`) into a Prompt template `WHERE la.customer_id = {{customer_id}} AND la.application_id = {{application_id}}`.
2. Forget to type real integers into the Text Inputs before running.
3. The rendered SQL is `WHERE la.customer_id = customer_id AND la.application_id = application_id`.
4. Oracle resolves the unqualified identifiers against the FROM clause — `customer_id` becomes `la.customer_id`. Both filters become tautologies.
5. The query degenerates to `WHERE status IN ('SUBMITTED','DRAFT','IN_REVIEW') FETCH FIRST 1 ROW ONLY` and returns **the first matching row** — i.e. some other customer's loan application.
6. The agent pipeline processes that data and writes a HITL task for it. The chat output gives no indication anything is wrong.

With real bind variables (`:customer_id`, `:application_id`) this same mistake would fail at parse time with `ORA-01008: not all variables bound` — fail-secure. The current Prompt-template injection workaround is silent and fail-open: any operator (or prompt-injected agent) that mishandles the substitution surfaces another customer's data.

This is OWASP A01:2021 (Broken Access Control) / API1 (BOLA) territory. Any production deployment of a workflow with this shape is one keystroke / one prompt-injection away from cross-customer data exposure.

## Workaround currently in use

Build the resolved SQL in a **Prompt** node whose template body holds the full SQL with `{{customer_id}}` / `{{application_id}}` placeholders. The Prompt node auto-exposes one input port per placeholder; wire the Text Input nodes into those ports. Wire the Prompt node's `Prompt message` output into the SQL Query node's `query` input port (which overrides the inline Query at runtime). Caveats:

- Loses bind-variable safety — any caller-supplied value that reaches the template is a SQL-injection vector. Acceptable here because the IDs are integers from a trusted session; not acceptable once the input surface widens.
- The SQL no longer lives in the SQL Query node — it lives in a Prompt template, which is harder to reason about and validate.
- Assumes the rendered string parses cleanly in Oracle (no escaping issues with the substituted values).

## Suggested fix

Parse `:name` tokens out of the query text, expose one input port per detected bind, and pass the wired values as `data={...}` to `exec_query`. Define precedence vs. the existing `query` override port (e.g. binds apply only when `query` is not wired).
