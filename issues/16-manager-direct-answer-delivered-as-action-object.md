# The manager's direct answer is delivered as its action plan instead of text

## What

When the manager of a manager-workers agent answers the customer itself rather than delegating, the integration endpoint sometimes returns the model's raw action plan as the `message` field, an object instead of a string:

```json
{"roomId": "5BADD9F3…",
 "message": {"thought": "The application is already submitted and has no missing fields, but the user hasn't explicitly agreed to proceed …",
             "actions": [{"name": "talk_to_user",  "parameters": {"text": "Could you let me know if you'd like me to go ahead and finalize your loan decision?"}},
                         {"name": "submit_result", "parameters": {"tool_output": "Could you let me know if you'd like me to go ahead and finalize your loan decision?"}}]}}
```

The customer's sentence is present, inside the `talk_to_user` action. The `thought` field, which the runtime's own system prompt promises the user will never see, is delivered alongside it. Every other turn returns `message` as a plain string.

Measured at roughly one turn in fifty over five bench runs, always on a turn where the manager had no worker to delegate to.

## Reproduce

1. A flow with one manager Agent node and two sub-agents, generation model `openai.gpt-oss-120b`.
2. Drive the flow to a state the manager's instructions do not name: here, an application already filed for review.
3. Ask a status question a few turns in a row (`Where does that leave me?`).
4. Read the integration endpoint's response body. On the turn where the manager answers directly, `message` is the object above.

## Source

`third_party/.../wayflowcore/templates/_managerworkerstemplate.py`, `parse_tool_request_from_str` (`:113`): when the model's text is not a tool call in the default format, the template runs it through `json_repair` and accepts `{"thought": …, "actions": [...]}` as a list of tool requests, so the format is a known model output.

`third_party/.../wayflowcore/executors/_agentexecutor.py`, `_convert_talk_to_user_tool_call_into_agent_message` (`:1263`): a parsed `talk_to_user` request is rewritten into an assistant message carrying only its `text`. The turn above reached the caller with the object intact, so on that path the conversion did not run and the raw model text was returned as the message.

## Why it matters

A consumer that reads `message` as a string, which is what every documented example shows, gets a parse error on those turns and no reply to show. The failure looks like a hang from the customer's side and from a test harness polling for a reply. The model's `thought` also leaks to the integration surface, which the runtime's system prompt explicitly promises does not happen.

## Suggested fix

1. Apply the `talk_to_user` conversion before the message reaches the flow's output, whichever parsing path produced the request, so `message` is always the text the user is meant to see.
2. Never include the `thought` field in an integration response.
3. Until then, document the object shape so consumers can read `actions[].talk_to_user.parameters.text`.

## Workaround in this repository

`Envelope.extractRawReply` in the Spring backend reads the sentence out of the `talk_to_user` action, falling back to `submit_result.tool_output`, so the turn produces a reply.
