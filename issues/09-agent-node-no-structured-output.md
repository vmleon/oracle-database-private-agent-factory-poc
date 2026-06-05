# Agent Builder Agent node can't request structured / constrained LLM output, though Wayflow + vLLM support it

**Severity: low** — a markdown contract + a deterministic Condition gate is a working alternative (used in `CHAT_WORKFLOW`). This is a robustness/ergonomics gap, not a blocker.

## What

PAF's Agent Builder "Agent" node exposes only: LLM, tools, sub-agents, custom instructions, description, prompt, temperature. There is no way to ask the model for structured / constrained output — no `response_format`, JSON-schema, or guided-decoding field.

The capability exists one layer down and is simply not surfaced:

- The vendored **Wayflow** runtime builds an OpenAI `response_format: {type: json_schema}` request when a prompt carries a response format, and merges arbitrary generation params via `LlmGenerationConfig.extra_args`.
- The configured backend, **vLLM**, supports structured outputs (`response_format` / guided decoding) natively.

But the PAF Agent node passes **only `temperature`** into the generation config, so none of it is reachable from the builder.

Consequence: an agent whose final message must follow a fixed shape (our `EvaluationAgent` emits a markdown `## Evidence` block consumed by a Condition gate + `RecommendationAgent`) can only be coaxed via prompt instructions + `temperature 0`, with no hard guarantee. We compensate with a deterministic regex Condition gate, which works — but a schema-constrained output would make the contract bulletproof and let smaller models run the recipe reliably.

## Reproduce

1. Open any Agent node in Agent Builder; inspect its config — 7 fields, none for output schema / response format (no advanced section either).
2. LLM Management → open a vLLM LLM Configuration — no advanced / extra generation-params field.
3. Hand-edit an exported flow JSON to add a `response_format` field to the Agent node `template`, re-import via `importAgentIrFlow` — it imports without error, but the field is silently ignored at run time (the executor never reads it).

## Source confirmation

Vendored Wayflow runtime: `paf-kit/applied-ai/kit/agent_factory/third_party/python3/lib/python3.12/site-packages/wayflowcore/`.

Supported one layer down:

- `wayflowcore/models/_openaihelpers/_chatcompletions_processor.py:131` — builds `response_format: {type: json_schema, ...}` when `prompt.response_format` is set; `LlmGenerationConfig.extra_args` are merged into the request kwargs.
- `wayflowcore/models/llmmodel.py` — `Prompt.response_format: Optional[Property]`.
- `wayflowcore/templates/template.py:92` — `PromptTemplate` supports `response_format` + `native_structured_generation`.
- `wayflowcore/models/llmgenerationconfig.py` — `LlmGenerationConfig` exposes an `extra_args` passthrough dict.

Not wired in PAF:

- `app/models/agentBuilder/steps/customSteps/AgentStep.py:174` (and `:282`) — builds `generation_config = LlmGenerationConfig(temperature=temperature_value)` only; no `response_format`, no `extra_args`. The node template schema defines no such field.
- `wayflowcore/agent.py:49` — the Wayflow `Agent` class itself exposes no `response_format`; structured output lives on `Prompt` / `PromptTemplate`, not on the tool-calling `Agent`.
- `app/util/llmConnectionManager.py` — connection config stores host / port / api_key / base_url / proxy only; no place to inject extra generation params.
- `app/blueprints/agentBuilder/agent_builder_blueprint.py:544` (`importAgentIrFlow`) — no field whitelist; an injected `response_format` is accepted and ignored.

## Why it matters

- Agents that must hand a fixed-shape payload to a downstream node (parser, condition, another agent) have no hard output guarantee — only prompt discipline. That is exactly where flows get flaky on smaller / quantised models.
- The capability already exists in the bundled runtime and the configured model server; only the builder wiring is missing — a low-cost thing to expose.
- Subtlety: structured output on a **tool-calling Agent's final message** is a different surface than on a single Prompt step. Wayflow exposes it on `PromptTemplate` / `Prompt`, not on `Agent`, so surfacing it in PAF means either threading it onto the Agent node or offering a structured Prompt/LLM step.

## Suggested fix

1. Add an optional **Output schema / Response format** field to the Agent node (and any LLM/Prompt step) accepting a JSON schema, threaded to the `Prompt.response_format` / `LlmGenerationConfig` path already supported in `_chatcompletions_processor.py`.
2. Alternatively/additionally, expose an **advanced generation params** passthrough on the LLM Configuration (maps to `LlmGenerationConfig.extra_args`), so `response_format` / `guided_*` can be set centrally without a per-node field.
3. Failing both, at least **validate on import** and warn on (or reject) unknown Agent-node template fields like `response_format`, so operators aren't misled into thinking an injected field takes effect.

(1) is the minimum useful change.
