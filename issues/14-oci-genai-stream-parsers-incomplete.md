# OCI Generative AI streaming: per-format parsers are incomplete, so model choice silently decides whether multi-agent flows work

## What

PAF calls OCI Generative AI through the native SDK (`OciAPIType.OCI`) and streams every agent turn. The request/response format is picked from the model id's vendor prefix — `cohere.*` uses the COHERE format, everything else the GENERIC format — and each format has its own stream parser in Wayflow. The two parsers are not equally complete, and neither gap is visible until an agent runs:

- **COHERE format: the output parser is never applied to a streamed reply.** The manager agent in a manager + sub-agents flow uses a text-based tool-calling template (`native_tool_calling=False`): the model is told to answer as `THOUGHTS … {"name": …, "parameters": …}` and `ManagerWorkersJsonToolOutputParser` turns that text into the `send_message` request. The Cohere stream converter receives that parser as `post_processing` and drops it. The manager's text is returned to the user verbatim, so the flow never delegates and the customer sees `I will delegate to Recommendation. {"name": "send_message", "parameters": {"message": "sess_…", "recipient": "Recommendation"}}` — internal reasoning and the session token included.
- **GENERIC format: the stream terminator is not handled.** `meta.*` models end their stream with a bare `[DONE]` event; the converter runs `json.loads` on every event, and the turn dies with `Expecting value: line 1 column 2 (char 1)`, which then becomes the reply.

Models on the GENERIC format that end their stream with a `finishReason` event (`openai.gpt-oss-*`) work as-is. The non-streaming path applies the output parser for every format and has no terminator to parse, so with `WAYFLOW_EXP_DISABLE_STREAMING` set every model above works — which confirms the gap is in the stream converters, not in the models.

Measured with Wayflow's own `ManagerWorkers` (manager with no tools → one worker with one tool), from inside the PAF container with the instance principal, one turn per model:

| Model (Frankfurt, on-demand)  | Format  | Streaming on (PAF default)           | Streaming off |
| ----------------------------- | ------- | ------------------------------------ | ------------- |
| `cohere.command-a-03-2025`    | COHERE  | fails — manager text never parsed    | passes        |
| `openai.gpt-oss-120b`         | GENERIC | passes                               | passes        |
| `meta.llama-3.3-70b-instruct` | GENERIC | fails — `[DONE]` → `JSONDecodeError` | passes        |

The OpenAI-compatible surface of OCI Generative AI (`OciAPIType.OPENAI_CHAT_COMPLETIONS`), whose converter does apply the parser and skips `[DONE]`, is not reachable from PAF: LLM Management never sets `api_type`, and the `oci_openai` package it imports is not shipped in the kit.

## Reproduce

1. LLM Management → OCI Generative AI, instance principal, model `cohere.command-a-03-2025`.
2. Agent Builder: a manager Agent node with one sub-agent on its `Sub-agents` port; give the worker a single tool and tell the manager to delegate on a trivial condition.
3. Run a turn that meets the condition. The reply is the manager's thoughts plus a literal `{"name": "send_message", …}`; the worker's tool never runs. `agent_factory.log` shows `_managerworkersexecutor.py … Answering to user with content` with that text.
4. Switch the model to `meta.llama-3.3-70b-instruct` and rerun: every turn returns `Expecting value: line 1 column 2 (char 1)`.
5. Switch to `openai.gpt-oss-120b`: the worker's tool runs and the reply is the worker's sentence.

## Source confirmation

`third_party/python3/lib/python3.12/site-packages/wayflowcore/models/ocigenaimodel.py` (wayflowcore 26.1.2, kit 26.7.0):

- L1136 `_CohereOciApiFormatter.convert_oci_chunk_iterator_into_tagged_chunk_iterator` accepts `post_processing`; L1186 yields `final_message` without ever calling it. The generic converter at L843 does call it (L891).
- L855 (generic) and L1149 (Cohere) `json.loads(raw_chunk.data)` on every event, no `[DONE]` guard.
- L445 non-streaming path: `response_message = prompt.parse_output(response_message)` — applied for every format.

`wayflowcore/templates/_managerworkerstemplate.py`:

- L125–137 `_DEFAULT_MANAGERWORKERS_CHAT_TEMPLATE`: `native_tool_calling=False`, `output_parser=ManagerWorkersJsonToolOutputParser()` — the manager always depends on the text parser, whichever model serves it.

`wayflowcore/executors/_managerworkersexecutor.py` L254: the unparsed text message is logged as `Answering to user with content` and returned as the turn's result.

`app/util/llmConnectionManager.py` L2681–2693: the OCI instance-principal `LLM_CONFIG` carries `model_type`, `model_id`, `client_config` and the serving mode — no `api_type`, no `generation_config`.

## Why this matters

- Model choice is presented in LLM Management as a free pick from the region's catalogue, and the connection test passes for every one of them. Whether a manager + sub-agents flow can delegate at all is decided by the vendor prefix, and the failure appears only in a live run — as a customer-facing reply.
- The Cohere failure mode leaks the manager's internal reasoning and the tool-call payload (here, a session token) to the end user. The instructions in the flow say never to reveal it; the runtime does.
- Every OCI Generative AI model works on the non-streaming path, so the models are fine; the parsers are the gap. Streaming is on by default and cannot be turned off from the UI.
- The `[DONE]` sentinel is the standard OpenAI-style terminator. A GENERIC-format parser that cannot skip it is one new model release away from breaking again.

## Suggested fix

1. Apply `post_processing` in the Cohere stream converter, exactly as the generic converter does (two lines before the final `yield`).
2. Skip a `[DONE]` event in both stream converters before `json.loads`.
3. Until then, gate the model catalogue in LLM Management: mark `cohere.*` and `meta.*` as unsupported for streaming agent flows, or fall back to the non-streaming call for them automatically.
4. Longer term, ship `oci_openai` and expose `api_type` so the OpenAI-compatible surface — one format, one parser, standard terminator — is available from LLM Management.
