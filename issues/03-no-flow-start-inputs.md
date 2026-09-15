# PAF flows have no per-invocation inputs other than the Chat message

## What

PAF's Agent Builder only surfaces the **Chat input** node as an operator-prompted runtime input. The **Text Input** node is static-only — whatever text is typed in its UI is the value emitted at runtime; there is no flag to mark it as "prompt at flow start" or surface it as a JSON field on the published REST endpoint. The runtime call hardcodes `inputs={}` regardless of node configuration.

## Reproduce

1. Agent Builder → add a **Text Input** node, type any string in its Text field (e.g. `customer_id`).
2. Wire its `Message` output into a Prompt template's `{{customer_id}}` placeholder, then on to a downstream consumer (SQL Query node, agent, anything).
3. Save and run the flow in Playground.
4. Observe: Playground prompts the operator only for the **Chat input** message. The Text Input value at runtime is the literal string typed in step 1 — no operator prompt for it.
5. Publish the flow → the REST endpoint accepts only the chat message; the Text Input value is not declared as an input field.

## Source confirmation

`agent_factory/app/models/agentBuilder/steps/customSteps/InputTextStep.py`:

- L42-57: the underlying tool just returns `input_text` unchanged.
- L60-69: `default_value = self.node["data"]["template"]["input_text"]["value"]` — the value typed in the UI is the default, used whenever nothing upstream is wired.

`agent_factory/app/models/agentBuilder/steps/flowGenericTemplates/components/InputText.py` (L50-91): `InputTextComponent` declares `required` and `display` flags but no "prompt at runtime" / "flow input" mechanism.

`agent_factory/app/models/agentBuilder/AgentBuilder.py`:

- L153 `execute_workflow` calls `flow.start_conversation(inputs={})` — empty dict, no operator-provided inputs ever flow through.
- L141 / L143 `create_conversation` calls `flow.start_conversation()` (no inputs) or with chat history only.

`ChatInput.py` is the only input component that uses `InputMessageStep.USER_PROVIDED_INPUT` — the single mechanism by which operator input reaches the flow at runtime.

## Why it matters

Any workflow that needs per-invocation structured parameters — authenticated user id, record id, tenant id, date range, options, configuration toggles — cannot receive them through PAF. The two non-options:

- Type the values inside the chat message and have an agent parse them out (natural-language parsing for IDs is brittle and wastes a model call).
- Hand-edit the Text Input node's value and re-save the flow per distinct invocation (unworkable in any multi-user / production setting; in our POC it means edit-save-run six times to cover the six scenarios).

The underlying Wayflow runtime already supports `Flow.start_conversation(inputs=...)`. PAF discards the capability by hardcoding the empty dict.

## Workaround currently in use

For the POC test harness we accept the limitation and use a Text Input node to carry an opaque session token. The flow:

1. `BANK_CORE.auth_session(session_token PK, customer_id, application_id, expires_at)` — one row per test scenario, seeded by Liquibase changeset 011. Tokens are deterministic + readable for ergonomics (`paf-test-alice-salaried`, `paf-test-david-highdti`, etc.).
2. Operator pastes the desired scenario's token into a `Text Input(session_token)` node in the canvas, saves the flow, runs.
3. A Prompt template renders `Session token: {{session_token}}` into the EvaluationAgent's prompt.
4. EvaluationAgent's first tool call is `banking-mcp.lookup_application(session_token)` — the MCP wrapper validates the token and returns the joined application context using `cx_Oracle` bind variables.

This is **acceptable only because** the operator (not an end user) sets the token, and only as a test harness. In production the token would have to be minted at login and threaded into the flow at invocation — which is impossible until PAF accepts per-invocation inputs. Critically: **never** extract `customer_id` / `application_id` from the chat message as a substitute — that's an IDOR vector (any user could supply any IDs).

## Suggested fix

Add an `expose_as_flow_input: true` flag to Text Input (and any analogous structured-input components). When set:

- The node's value is sourced from `inputs[<node_name>]` at runtime instead of the static UI default.
- Playground renders an additional input field per flagged node, alongside the chat message.
- The published REST endpoint declares each flagged node as a typed field in its JSON schema.

`execute_workflow` must forward those inputs to `flow.start_conversation(inputs=...)` rather than always passing an empty dict.
