# Flow validator surfaces internal IDs instead of node names

## What

PAF's Agent Builder flow validator rejects malformed graphs with errors keyed on internal step IDs, not the human-readable node titles shown in the canvas. The user has no realistic way to map the error back to which canvas node is wrong without dumping the saved JSON from the DB.

Example error verbatim (truncated):

```
No step is transitioning to step node-1779808939230-c4ede103-1317-4e94-a4c7-a0a2ae055946.
Except the begin step, all steps should be transitioned to.
Steps: ['initial_step', 'node-1779808803926-d0852ba3-30bc-4b50-873c-c81b841cad96',
        'node-1779808806114-131a7d4c-e9e1-4180-95a8-76803c79447c',
        ... 12 more node IDs ...]
Control flow edges: ControlFlowEdge(source_step=initial_step, source_branch=next,
        destination_step=node-1779808855830-f4203d59-b581-4550-8346-92e384da6852)
        ... 13 more edges, all keyed by node ID ...
```

There is no node title (`Chat output`, `Condition`, `TextCombiner`, etc.) anywhere in the error. The user has to query `AGENT_FACTORY.AAI_AGENT_BUILDER.data` and join the IDs back to titles manually.

## Reproduce

1. Build a flow in Agent Builder where two branches of a Condition node converge on a downstream step (e.g. both branches eventually feed a single Chat output via a Text Combiner).
2. Save the flow.
3. Click Run / Playground.
4. Observe the validation error above — entirely IDs, no titles.

## Why it matters

- **Debugging time.** A non-trivial flow has 10+ nodes; mapping `node-1779808939230-c4ede103-…` back to "the second Chat output I added" is 5–10 minutes of cross-referencing per error, every iteration.
- **Triage is impossible from logs.** The same flow surfaces the same error to the user, to support, and to any monitoring tool. None of them can act without re-mapping IDs to titles.
- **The error is also wrong about the root cause.** "No step is transitioning to X" reads as "you forgot to wire X", but the underlying problem can be "you wired X from two upstream branches and the validator can't pick one" — a completely different fix. The error text mentions only the symptom, not the unsupported topology.

## Suggested fix

- **Substitute node titles for IDs** in the user-facing validator output. The mapping is trivially available — `AAI_AGENT_BUILDER.data` already has `nodes[].data.title` next to each node id.
- **Distinguish "missing inbound edge" from "ambiguous inbound edge" / "branch convergence not supported"** with separate error messages. Each suggests a different fix.
- **Include in the error message a hint** about which canvas operation typically causes it (e.g. "Two upstream nodes target the same input — Wayflow requires a single control-flow predecessor per step. Split into two terminal nodes or add a join step.").

Reasonable target output for the same error:

```
Flow validation failed:
  - "Chat output" has no inbound wire (orphan node).
  - "Recommendation Agent" and "Text Combiner" both end in no-next branches.

Likely cause: two Condition branches converge on a single downstream step.
Wayflow requires each step to have exactly one control-flow predecessor per
branch. Either (a) split the downstream into two terminal nodes (one per
branch) or (b) add a supported merge step before the convergence point.
```
