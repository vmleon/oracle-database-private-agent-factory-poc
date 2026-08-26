# Agent Spec export refuses any flow containing a Regex extractor (or any Agent Builder runtime tool)

## What

Exporting a flow as portable Agent Spec fails when the flow contains a `Regex extractor`:

```
Failed to export flow CHAT_FLOW: Node 'Regex extractor' cannot be exported as
portable Agent Spec because it is implemented as an Agent Builder runtime tool.
```

The password-protected `.paf` export of the same flow succeeds. There is no partial or degraded Agent Spec output, and no way to export the rest of the flow.

## Reproduce

1. Build any flow with a `Regex extractor` node (category Processing) on the path.
2. Agent Builder → **My Custom Flows** → export as Agent Spec.
3. The export fails with the message above, naming the node.

## Why it matters

`Regex extractor` is not a decorative node in our flow — it is the trust boundary. PAF accepts no per-invocation flow input other than the chat message (`issues/03`), so the opaque session token has to travel in-band inside a `[[SESSION <token>]]` envelope, and two `Regex extractor` nodes split the token from the customer's message at flow start. Every deterministic tool call downstream is fed from that wired token, which is what keeps a model from ever transcribing it on a read path.

So the constraint is not "avoid one convenience node". Any flow that authenticates a per-request caller has to parse something at flow start, and doing that with the palette's own component makes the whole flow non-exportable as Agent Spec. The two forms are not equivalent either: `.paf` is opaque, password-protected and only meaningful to another Agent Builder install, whereas Agent Spec is the portable, reviewable, diffable format. Losing it means a flow cannot be code-reviewed as a spec, version-controlled meaningfully, or moved to a non-Agent-Builder runtime.

The failure also arrives late — after the flow is built, tuned and validated — rather than at the point the node is dragged onto the canvas.

## Suggested fix

Any of, in order of preference:

1. Give the Agent Builder runtime tools a portable Agent Spec representation, so a flow using them round-trips. A regex extraction is a pure string operation and needs no runtime privilege.
2. Failing that, export the flow with those nodes represented as a declared extension point, so the rest of the flow is still reviewable and the incompatibility is explicit and localised.
3. At minimum, surface the constraint **when the node is placed** — mark the palette entry as non-exportable, and state in the docs which components are Agent Builder runtime tools. Discovering it at export time, after the flow is finished, is the expensive path.

## Workaround

Ship the `.paf` bundle plus a written build blueprint, and treat the blueprint as the versioned source. See `paf/flows/CHAT_FLOW.md`.
