# Agent node fails at run time when Custom Instructions contain a `{{placeholder}}`

## What

An Agent node whose **Custom Instructions** field contains a `{{placeholder}}` fails to build at run time with a pydantic validation error, before the agent executes. The flow returns the raw validation text to the caller as the agent's reply. Verbatim:

```
1 validation error for ExtendedAgent
  Value error, The ExtendedAgent component expected a property titled `context`, but none of the passed properties have this title: ['prompt']. [type=value_error, input_value=ExtendedAgent(id=1af75ffe...cc, name=Concierge, ...), input_type=ExtendedAgent]
    For further information visit https://errors.pydantic.dev/2.13/v/value_error
```

The Prompt node on the same canvas treats `{{name}}` in its text as a first-class feature and auto-exposes a matching input port. The Agent node's Custom Instructions field looks like the same syntax but is not wired to do the same thing, and instead breaks the run.

## Reproduce

1. New custom flow: Chat input → Agent → Chat output.
2. In the Agent node's Custom Instructions, type any placeholder, e.g. `Answer using {{context}}.`
3. Save and run in the Playground.
4. The run fails with the validation error above, naming the placeholder (`context`) but nothing else.

Secondary observation: a flow imported from an earlier release whose Custom Instructions already used `{{placeholder}}` syntax fails the same way once it is run — the field survives import unchanged, and the failure only appears at run time.

## Source confirmation

Kit version: `paf-kit/applied-ai/kit/agent_factory/internal/version.json` → `"app_version":"26.7.0.0.0"`.

**1. Placeholders in the system prompt become required inputs.** `third_party/python3/lib/python3.12/site-packages/pyagentspec/agent.py:61`:

```python
    def _get_inferred_inputs(self) -> List[Property]:
        # Extract all the placeholders in the prompt and make them string inputs by default
        return get_placeholder_properties_from_json_object(getattr(self, "system_prompt", ""))
```

`get_placeholder_properties_from_json_object` (`pyagentspec/templating.py:35`) scans the string with the regex `TEMPLATE_PLACEHOLDER_REGEXP = r"{{\s*(\w+)\s*}}"` (`templating.py:15`) and returns one required `Property` per match — here, `context`.

**2. Missing inferred properties raise.** `third_party/python3/lib/python3.12/site-packages/pyagentspec/component.py:1605`:

```python
    @classmethod
    def _validate_no_missing_property(
        cls, property_titles: Set[str], inferred_property_titles: Set[str]
    ) -> None:
        """
        Validate properties of ComponentWithIO.

        Raises when a ComponentWithIO expects some properties which are missing in the
        properties passed at initialization.
        """
        missing_property_titles = [
            title for title in inferred_property_titles if title not in property_titles
        ]
        if len(missing_property_titles) > 0:
            raise ValueError(
```

**3. `AgentStep` never inspects Custom Instructions for placeholders when it builds the passed-in properties.** `app/models/agentBuilder/steps/customSteps/AgentStep.py:1173`:

```python
    def _create_tool_input_descriptors(self) -> List[StringProperty]:
        input_descriptors = [
            StringProperty(
                name="prompt",
                default_value=self._get_template_value("prompt", ""),
            )
        ]
        if self._get_sub_agents_ids():
            input_descriptors.append(
                StringProperty(
                    name="sub_agent_context",
                    default_value="[]",
                )
            )
        return input_descriptors
```

This is the origin of the `['prompt']` list named in the error: the node only ever declares `prompt` (plus `sub_agent_context` when it has sub-agents) as a passed property, regardless of what the Custom Instructions text contains.

**4. Custom Instructions become the `ExtendedAgent`'s `system_prompt`.** `AgentStep.py:1062` builds each leaf agent with:

```python
            leaves.append(
                node._build_agentspec_runtime_agent_component(
                    system_prompt=node._get_effective_custom_instruction(),
```

`_get_effective_custom_instruction()` (`AgentStep.py:549`) returns `_normalize_custom_instruction(self._get_template_value("custom_instruction", ""), ...)` — i.e. the Custom Instructions field verbatim (after `_ensure_nonempty_instruction`'s empty-string fallback). `_build_agentspec_runtime_agent_component` (`AgentStep.py:818`) forwards it straight into `ExtendedAgent(..., system_prompt=system_prompt, ...)` at `AgentStep.py:848`. This confirms the field feeding `pyagentspec.agent.Agent._get_inferred_inputs()` in point 1 is the Agent node's Custom Instructions.

Note: `_normalize_custom_instruction` also calls `_escape_literal_instruction` (`AgentStep.py:490`), which wraps text containing `{{` or `}}` in Jinja `{% raw %}...{% endraw %}` tags. This wrapping has no effect on the failure: `get_placeholders_from_json_object` matches `{{\s*(\w+)\s*}}` with a plain regex over the raw string and does not parse or respect Jinja `{% raw %}` tags, so `{{context}}` is still extracted as a placeholder from inside the wrapped text.

## Why it matters

- Custom Instructions is a free-text field with no documented restriction on `{{...}}` syntax, and the Prompt node on the same canvas treats that exact syntax as a first-class feature that auto-exposes an input port. A user who has used a Prompt node reasonably expects the same syntax to work in an Agent node's Custom Instructions.
- The failure is not caught by any builder-time validation. It surfaces only when the flow runs, and the pydantic error text is returned to the caller as the agent's reply — so an end user of a published workflow sees an internal stack-trace fragment (`ExtendedAgent`, `pydantic.dev` URL) instead of a workflow error or a helpful message.
- The error names the placeholder (`context`) but not the node, the field, or the fact that Custom Instructions is the source. Nothing in the message points the user at the field they need to edit.
- It blocks a legitimate design: fanning a piece of shared context (e.g. a `{{document_id}}`-style token) to several agents as data, rather than having each agent re-fetch or re-derive it independently.

## Suggested fix

1. Have `AgentStep` scan the Custom Instructions text for `{{placeholder}}` occurrences and declare them as inputs (in `_create_tool_input_descriptors` and the equivalent execution-input path), so the Agent node auto-exposes a port per placeholder exactly as the Prompt node does — making the feature work the way users expect.
2. Failing that, validate in the builder when the flow is saved: reject or warn on a `{{placeholder}}` found in an Agent node's Custom Instructions, naming the node and the field, so the failure is caught at design time instead of at run time.
3. Regardless of which of the above is chosen, stop returning raw pydantic validation text to the caller as the agent's reply.
