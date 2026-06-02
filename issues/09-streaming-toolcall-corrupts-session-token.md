# Streaming agent tool-calls intermittently corrupt a tool argument (drops/duplicates a character)

## What

When a PAF Agent node calls a tool, the tool-call **arguments** are produced by the model and streamed back from the LLM endpoint. The streamed tool-call argument assembly occasionally **drops or duplicates a single character** in a string argument. For an opaque value that must round-trip verbatim — e.g. the `session_token` our `Concierge` agent passes to `get_context(session_token=...)` — a one-character change makes the token invalid, so `get_context` returns `{"error": "invalid_or_expired_session"}`, the agent emits its fail-secure apology, gate `G1` goes False, and the customer gets _"Sorry — we couldn't process your application right now. Please try again in a moment."_ instead of an answer.

It is non-deterministic: the same input succeeds on most turns and fails on a few, with no error logged anywhere — the token simply arrives at the MCP tool one character off.

## Reproduce

1. Any flow where an Agent passes a long opaque string to a tool (here: `CHAT_WORKFLOW`, Concierge → `get_context(session_token)`).
2. Run the same turn repeatedly. Occasionally the run returns the apology in ~22s (it bailed at G1) instead of the normal ~210s decision path.
3. In the banking-mcp log, the failing run shows `get_context` was called with a token that differs from the one issued by one character, e.g. issued `…05e47e1` → received `…05e7e1` (the `4` dropped) → `invalid_or_expired_session`.

Controlled isolation (same model, same prompt, temp 0.01):

- **Non-streaming** OpenAI-compatible tool-call: **0 corruptions / 160 trials**.
- **Streaming** (`stream=true`) tool-call, deltas reassembled: **1 corruption / 150 trials** (a chunk-boundary duplication, `…eecfa…` → `…eecfafa…`).
- The only changed variable is streaming vs non-streaming.

## Source confirmation

- `agent_factory/app/models/agentBuilder/steps/customSteps/AgentStep.py` builds a `wayflowcore` `Agent` and runs it in streaming mode. The corruption is visible in PAF's own `/mount/log/app/latest/log/state_manager.log`:
  ```
  AgentStep.py ... ConversationMessageAddedEvent(... role='assistant',
    tool_requests=[ToolRequest(name='get_context',
      args={'session_token': 'sess_…05e7e1'}, ...)], ... streamed=True)
  ```
  i.e. the assembled `ToolRequest` already holds the corrupted token (the same run's prompt/extraction logged the correct token), and the message is tagged `streamed=True`. The corruption is in the streamed tool-call argument path, not in the model's generation.

## Why it matters

- It silently breaks the primary happy path a few percent of the time, with **no error in any PAF log** (the token is simply wrong) — extremely hard to diagnose.
- It is fundamentally unsafe to route an opaque secret/identifier through the model and depend on the streamed reconstruction being byte-exact. This is aggravated by there being **no way to bind a tool-call argument to a flow value deterministically** (the model must transcribe it) — see the data-flow coupling in [`issues/08`](08-condition-edge-couples-control-and-data.md).
- It compounds: every agent that re-passes the token is an independent chance to corrupt it.

## Workaround currently in use

Backend `ChatService.handleTurn` detects the exact apology sentinel and re-runs the turn up to 3 attempts (the corruption is random per run). See `src/backend/.../chat/ChatService.java`. This masks the issue but wastes a full run on each occurrence and cannot fix the underlying corruption.

## Suggested fix

1. **Use non-streaming completion for agent tool-call turns** (or fix the streaming tool-call argument assembler so deltas can't drop/duplicate characters at chunk boundaries). Non-streaming was corruption-free across 160 trials.
2. **Provide a deterministic way to pass a tool argument from a flow value/secret without the model transcribing it** (a tool-input binding), so opaque tokens never depend on LLM/stream fidelity.
