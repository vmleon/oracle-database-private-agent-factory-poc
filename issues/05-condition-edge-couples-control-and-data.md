# A Condition branch edge couples control flow and data flow — no control-only routing

## What

In Agent Builder, a single drawn edge from a `Condition`'s `True` / `False` output to a downstream node does **two** things at once:

1. **Control flow** — it makes that node the next step on the taken branch.
2. **Data flow** — it binds the branch's message (`True Message` / `False Message`) into the target node's **input port**.

There is no way to draw a **control-only** edge ("route to step B, carry no payload"), and the canvas exposes **no shared-state / Variable node** and **no mid-flow input** ([`issues/03`](03-no-flow-start-inputs.md)). So when you need to conditionally sequence a step that does **not** consume the predicate's payload, you must repurpose one of that step's real input ports to receive the branch message.

This is not an edge case — "branch to a step that doesn't need the predicate value" is everyday routing.

## Reproduce

1. Build `Concierge agent → Condition (regex on the agent message) → Docs & Employer prompt`.
2. The Docs & Employer prompt has exactly one input port (`session_token`), which must come from the Token extractor.
3. Try to wire the Condition's `True` output so that it **sequences** Docs & Employer **without** overwriting `session_token`. There is no spare port and no control-only connector — the only place to land the `True` edge is `session_token`.
4. Result: `session_token` is fed the Condition's `True Message` (the Concierge's message), not the token → the downstream `get_context(session_token)` fails. (If you instead wire the Token extractor into `session_token` _and_ the Condition's `True` output into the same port, you get two `DataFlowEdge`s into one input — a conflict.)

## Source confirmation

`agent_factory/app/models/agentBuilder/AgentBuilder.py` builds the Wayflow flow from the canvas with two **separate** passes, but both are driven off the same drawn edges:

- `_create_control_flow_edges` (L237+): for a `Condition`, it reads `_branch_successors(node_id, "true_output")` / `("false_output")` (L291) and emits a `ControlFlowEdge(..., source_branch=BRANCH_NEXT|"false")` to whatever node that edge targets (L383–387).
- `_create_data_flow_edges` (L406+): for **every** drawn edge it emits a `DataFlowEdge(source_output=sourceHandleId → destination_input=targetHandleId)` (L448–454). The only exclusions are the structural `agent → subAgents` wiring and `json_inputs` fan-in (L424, L431) — a `true_output → session_token` edge is **not** excluded, so it always creates a data binding.

`agent_factory/app/models/agentBuilder/steps/customSteps/Condition.py`:

- `ConditionStep(BranchingStep)` (L44) selects the branch, and emits `{"true_output": true_message}` or `{"false_output": false_message}` (L165) — the branch output **is** the configured message, so any edge from it carries that message as data.

The underlying engine already separates the concerns: `wayflowcore.controlconnection.ControlFlowEdge` and `wayflowcore.dataconnection.DataFlowEdge` are distinct types (imported at `AgentBuilder.py` L29–30). The coupling is introduced by the Agent Builder canvas, not the runtime.

## Why it matters

The pattern every other agent/flow framework treats as fundamental — _control routing and data state are separate_ — cannot be expressed:

- **LangGraph**: `add_conditional_edges(source, router_fn, path_map)` returns only the next node name; data lives in the shared typed `State`. The router carries no payload.
- **OpenAI Agents SDK / Swarm**: `handoffs` are control; data is the shared context.
- **AutoGen**: a GroupChat manager selects the next speaker (control) over shared message history (data).
- **BPMN**: an XOR gateway routes the token (control) over process variables (data).

In PAF you must instead thread data through the branch you happen to be taking, which forces awkward, error-prone wiring and makes flows harder to read and validate.

## Workaround currently in use

In `CHAT_WORKFLOW` the Docs & Employer stage needs no forwarded payload (every agent re-reads everything from the DB via `get_context`), yet must still be gated to run only when intake is `READY`. We make the gate **forward the session token itself**:

- `Condition G1`: `Text Input` ← Concierge message (tested); `True Message` ← **Token extractor** (forwarded); `False Message` ← Concierge message (the still-collecting question).
- `G1.true_output → Docs & Employer prompt.session_token` — the single edge both sequences the step and delivers the token.

For the Eligibility and Recommendation stages the coupling is harmless, because those prompts have a genuine payload port (`evidence` / `findings`) for the gate output to land on, and they take `session_token` straight from the Token extractor. See [`paf/flows/CHAT_WORKFLOW.md`](../paf/flows/CHAT_WORKFLOW.md) Steps 6–8.

## Suggested fix

Either (any one would resolve it):

1. **A control-only connector** on the canvas — let an edge be marked "sequence only", so it creates a `ControlFlowEdge` with no accompanying `DataFlowEdge`. Then a `Condition.True` can gate a step without touching its inputs.
2. **A shared-state / Variable node** (pairs with [`issues/03`](03-no-flow-start-inputs.md)) so steps read inputs from named state rather than from the edge that triggered them — the LangGraph model.
3. **A dedicated trigger/“run-after” input port** on agent and prompt nodes (MESSAGE-agnostic, no data binding) for branch outputs to attach to.

The runtime already supports (1) — `ControlFlowEdge` and `DataFlowEdge` are independent — so the change is confined to the Agent Builder edge model and palette.
