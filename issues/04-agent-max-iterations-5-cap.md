# Agent node hardcodes `max_iterations=5`, last iteration strips all wired tools

## What

PAF's Agent Builder constructs every Wayflow `Agent` with `max_iterations=5` (Wayflow's own default is 10, but PAF overrides). On the last iteration (`curr_iter == max_iterations - 1`), Wayflow's executor calls `_collect_tools` with logic that returns **only** `[talk_to_user, submit, exit_conversation]` — every wired MCP / REST / sub-agent tool is removed from the model's tool list, by design ("we don't want the model to output a tool call for the last iteration").

The combined effect is an undocumented ceiling: an agent can make at most **4 successful tool calls** per turn before being forced into reply mode. The 5th LLM round-trip is for the final message only, and any attempted tool call there returns:

```
Tool named <X> is not in the list of available tools.
Remember that you ONLY have access to 1 'tools'.
Available tools:
['talk_to_user'].
```

A failed tool call (e.g. wrong tool name → runtime feeds error back to model → model retries) consumes an iteration just like a successful one, so the real ceiling can drop to 3 successful calls if any go wrong.

## Reproduce

1. Build a workflow with one Agent node + at least one MCP server providing ≥4 distinct tools.
2. Custom Instructions: instruct the agent to call 5 different tools in sequence, then emit a final message.
3. Run the flow. The 5th tool call fails with the error above. The Condition / downstream nodes see the error string as the agent's `Message` output.

For a real-world repro: `paf/flows/CHAT_WORKFLOW.md`'s EvaluationAgent recipe needs exactly 4 tool calls + 1 final emission. When the 3rd call (`verify_employer`) failed because of the related operationId issue ([[06-openapi-importer-ignores-operationid]]), the retry burned the budget and the 4th call (`evaluate_eligibility`) hit this cliff.

## Source confirmation

`paf-kit/applied-ai/kit/agent_factory/app/models/agentBuilder/steps/customSteps/AgentStep.py`:

- L183 `"max_iterations": 5,` (default config injected into the Agent node)
- L322 `max_iterations=5,` (literal passed when constructing the Wayflow Agent)

`paf-kit/applied-ai/kit/agent_factory/third_party/python3/lib/python3.12/site-packages/wayflowcore/executors/_agentexecutor.py`:

- L1166 `if curr_iter == config.max_iterations - 1:` — last-iteration gate
- L1177-1182 returns only `{_SUBMIT_TOOL_NAME, _TALK_TO_USER_TOOL_NAME, EXIT_CONVERSATION_TOOL_NAME}` on the last iteration

The `Tool named ... is not in the list` error is emitted by the same file at L609.

## Why this matters

- The cap is invisible in the UI — no setting on the Agent node exposes it.
- The "available tools list collapses to `['talk_to_user']` on the last iteration" behavior is not documented anywhere reachable from the UI; the only diagnostic surface is `state_manager.log` inside the PAF container.
- The cap forces a per-agent tool-budget below what most non-trivial recipes need. Splitting work across multiple agents becomes mandatory rather than stylistic, with the corresponding extra prompt-engineering cost (handing evidence between agents through Prompt + Condition nodes — see CHAT_WORKFLOW's two-agent split).
- A single transient tool-call error (e.g. tool name typo, network blip, MCP timeout) eats an iteration silently and can push downstream tool calls into the "stripped" iteration, producing the exact same misleading error as a real tool-list misconfiguration.

## Suggested fix

1. **Expose `max_iterations` on the Agent node UI** as a numeric input (with a sane default of 5 or 10 and a clear tooltip about the behavior on the last iteration).
2. **Surface a more diagnostic error on the last-iteration tool-strip case** — distinguish "this tool was never wired" from "this tool was stripped because you're on the last iteration" so users can tell whether the bug is configuration or budget.
3. Failing UI work: at minimum, document the cap and the last-iteration tool-strip behavior prominently — this is the kind of detail that turns a working workflow into a flaky one when one tool call hiccups.
