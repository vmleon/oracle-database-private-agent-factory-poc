# A flow runs only one Agent node per execution path; the second is silently skipped

## What

A flow containing two Agent nodes on the same execution path silently stops after the first. The first agent's message is returned as the flow's result and no downstream node runs. No error is raised.

## Reproduce

Three minimal flows, each `Chat input → … → Chat output`:

1. `Prompt → Agent1 → Condition (regex `.\*`) → Prompt2 → Agent2` — Agent2 never runs; the reply is Agent1's message.
2. The same two agents placed on separate branches of one `Condition` — both run, one per turn, depending on which branch the condition selects.
3. A manager agent with a worker wired to its `Sub-agents` port — the worker runs and the manager returns its output.

The failure is silent in shape 1: no validation error at build time, no error at run time, and no log line naming the skipped node.

## Source confirmation

`paf-kit/applied-ai/kit/agent_factory/app/models/agentBuilder/steps/customSteps/AgentStep.py`:

- A flow's agent is built via `_build_runtime_agent` without passing `caller_input_mode` (`:1321`), so it takes the method's default, `CallerInputMode.ALWAYS` (`:791`).
- Sub-agents are built with `caller_input_mode=CallerInputMode.NEVER` explicitly (`:1066`).

An agent with `CallerInputMode.ALWAYS` yields control back to its caller once it produces a message, which ends the flow's turn. A flow-level agent (shape 1 and shape 2) is always built this way, so a second agent placed after it on the same path is never reached. A sub-agent (shape 3) is built with `NEVER`, so control stays inside the manager's executor across the delegation.

## Why it matters

The palette lets you place two Agent nodes on one path and the flow validator accepts it, so the topology looks supported. The documentation's sample workflows all use a single Agent node, and the one advanced sample that uses multiple agents does so via a master agent orchestrating sub-agents — but neither the samples nor the reference documentation state the constraint. A flow built the obvious way — agent, then a second agent further down the same path — fails with no diagnostic pointing at the cause; the flow simply returns the first agent's answer.

## Suggested fix

1. Reject the topology at save time: when a workflow is saved, detect a second Agent node reachable on the same execution path after a first Agent node (outside a `Sub-agents` wiring) and fail validation, naming the second agent and the path.
2. Failing that, document the constraint on the Agent node's reference page, next to the `Sub-agents` connector, so a builder sees it before wiring two agents in series.
