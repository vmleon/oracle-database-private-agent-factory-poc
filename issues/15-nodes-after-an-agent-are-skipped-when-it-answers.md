# Nodes wired after an Agent node are skipped whenever the agent answers without a tool call

## What

Any node placed downstream of an Agent node — a Prompt, a Type Convert, a Deterministic MCP tool, a Condition — runs only when the agent's final LLM message carries tool requests alongside its answer. On the normal path, where the agent simply answers, the flow's turn ends at the Agent node and every downstream node is silently skipped. No error, no log line naming the skipped nodes, and the flow returns the agent's message as its result.

The effect is intermittent rather than absolute, which is what makes it costly: the same flow, same input, same model, runs its post-agent nodes on some turns and not others. The turns that do run them are the ones where the model happened to emit an answer and a tool call in the same step.

## Reproduce

Flow: `Chat input → … → Agent → Prompt → Type Convert → Deterministic MCP tool → Condition → Chat output`, where the Deterministic MCP tool is a read-only check over the database and the Condition tests its result.

Run the same single-turn scenario five times. Count the executions:

```bash
podman exec <paf> sh -lc 'grep -c "ConditionStep evaluation" /mount/log/app/latest/log/agent_factory.log'
```

Observed over five identical runs of one scenario: five turns, five evaluations of the Condition that sits _before_ the agent, and **one** evaluation of the Condition that sits after it. The MCP tool's own server logged one call and wrote one audit row for the five turns.

The single turn that executed the chain is the only one whose log carries:

```
_agentexecutor.py, line 372 [WARNING]
  The LLM tries to call tools and answer to the user. The tools will be run and
  the LLM will be re-prompted for its answer to the user.
```

The correlation was 5/5 in that sample and 1/13 in an earlier one on the same flow.

## Source confirmation

`third_party/.../wayflowcore/executors/_agentexecutor.py`, `_decide_next_action` (`:328`):

```python
# if no tool_requests, we simply yield to the user
if new_message.tool_requests is None or len(new_message.tool_requests) == 0:
    return True
```

`True` means yield. At `:1141` the yield is overridden only for an agent whose `caller_input_mode` is `CallerInputMode.NEVER` — the model is reminded to submit its outputs and execution continues. A flow's own Agent node does not get that mode: `AgentStep.py:1321` calls `_build_runtime_agent` without `caller_input_mode`, so it takes the default `CallerInputMode.ALWAYS` (`:791`). Sub-agents are built with `NEVER` explicitly (`:1066`).

So a flow-level agent yields to its caller the moment it produces a message with no tool requests, and the turn ends there. The mixed answer-and-tool-call path at `:372` is the only route that keeps the executor looping long enough for the flow to reach the nodes after the Agent step.

## Why it matters

The canvas accepts the topology, the validator accepts it, and the node palette offers exactly the components that invite it — a Deterministic MCP tool and a Condition are the natural way to assert something about a turn _after_ the agent has produced its answer. A guard built that way appears to work, because it does work on the turns where it runs.

That intermittency is worse than a hard failure. A flow whose post-agent Condition is a safety gate — "do not show this answer unless the record it claims exists" — will pass its tests, pass a demo, and enforce nothing most of the time. Nothing in the product surface distinguishes "the gate ran and passed" from "the gate never ran", and neither does the flow's own result.

The related constraint on a _second Agent node_ is [`12-one-agent-per-execution-path`](12-one-agent-per-execution-path.md). This issue is the broader case: the skipped node need not be an agent, and the documented guidance to place gates after an agent does not hold.

## Suggested fix

1. Keep the flow's turn alive until the flow's own graph is exhausted: when a flow-level agent yields, run the remaining steps on that execution path before returning the turn's result. The agent's answer is still the agent's answer; the flow's remaining nodes are part of the same turn.
2. Failing that, reject the topology at save time the way a second Agent node should be rejected — if a node is reachable downstream of an Agent node on the same execution path, fail validation and name it, so the constraint is visible before a guard is built on top of it.
3. At minimum, log the skip. One line naming the nodes that were not reached would have turned this from a multi-hour investigation into a grep.
