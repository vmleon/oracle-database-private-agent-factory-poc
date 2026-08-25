# Multi-agent flow binds every agent's tools to the FIRST agent's source

## What

In a flow with 2+ Agent nodes, each wired to its **own** tool node(s), at runtime
**every agent runs with only the FIRST agent's tools**. Each subsequent agent's
tools are silently dropped — the agent still reasons under its own custom
instructions but is handed the first agent's toolset. No error is raised. The
saved flow definition is 100% correct, and **clone / from-scratch rebuild /
`paf-agent-factory` restart do NOT fix it** (all three confirmed against PAF
26.4).

## Reproduce

`CHAT_FLOW` has three sequential agents, each with a distinct tool:

| Agent           | Wired tool node                                       | MCP source                         |
| --------------- | ----------------------------------------------------- | ---------------------------------- |
| Concierge       | `upsert_application`                                  | application-mcp (source 4)         |
| Docs & Employer | `required_documents` + REST `GET_v1_companies_verify` | opa-mcp (source 1) + registry REST |
| Recommendation  | `create_hitl_task`                                    | hitl-mcp (source 2)                |

1. Mint a session for a clean customer, send one chat turn.
2. **Concierge works** (it is the first agent) → emits `[[INTAKE status=READY]]`.
3. **Docs & Employer is handed `upsert_application`** instead of its own tools.
   It calls `upsert_application` (returns `{"application_id":1}`), never produces
   the `[[EVIDENCE …]]` block, so the downstream condition goes False → flow
   returns its static error, writes 0 HITL rows.
4. `/mount/log/app/latest/log/agent_factory.log` shows
   `MCPServerToolsStep: source_id=4` logged **3×** (once per agent); sources 1
   and 2 are **never attempted** — no discovery, no token lookup, no error.

The flow definition is correct both at rest and as loaded: `/v1/agents/<id>`
and the run-time blueprint dump (`agent_builder_blueprint.py:139`) both show the
three agents with distinct `tools.value` → distinct `serverSource` (4 / 1 / 2).

## Source confirmation

Root cause is a **first-write-wins, name-keyed tool registry** combined with a
**non-unique tool name shared by every Agent node**.

- `AgentStep._create_tool` (`.../steps/customSteps/AgentStep.py`) builds the
  per-agent executable as a closure named — by the Python function name —
  `agent_step`. **Every** Agent node produces a tool literally named
  `agent_step`. The closure reads its toolset from the captured
  `self.node["data"]["template"]["tools"]["value"]`, but receives `prompt` and
  `custom_instruction` as call parameters (per-step input descriptors).
- `AgentBuilder._register_tools_from_step` (`AgentBuilder.py:601-620`):
  ```python
  for tool in tools:
      name = getattr(tool, "name", None)
      ...
      if name not in self._tool_registry:   # L618  ← first-write-wins
          self._tool_registry[name] = tool   # L619
  ```
  Iterating nodes in order, the **first** agent's `agent_step` is registered;
  the second and third are skipped because the name already exists.
- `AgentSpecLoader(tool_registry=self.get_tool_registry())` (`AgentBuilder.py:412`)
  then resolves **every** agent step's `agent_step` reference to that single
  registered tool — a closure over the **first** agent's `self.node`, hence the
  first agent's MCP source (4) for all agents.

Everything else is correct in isolation, which is why the bug looks like
"corrupted flow state": definition correct at save + load; `steps_classes`
keyed by node id (`AgentBuilder.py:496`); `StepFactory.create_step` returns a
fresh instance per node (`StepFactory.py:188`); each `AgentStep` tool-gather
reads its own `self.node`. The collapse is solely the name-keyed registry.

Per-step `custom_instruction` still flows through correctly (it is a call
parameter, not captured), which is why each agent _reasons_ as itself but
_acts_ with the wrong tools — the most confusing possible symptom.

## Why it matters

This breaks **every** multi-agent flow whose agents carry different tools — the
headline PAF use case. It is silent (no error; agents call tools they were never
granted, or hallucinate), and it corrupts decisions rather than failing closed.
Users cannot work around it through the product: clone, rebuild, and restart all
reproduce it (confirmed). Single-agent flows and Deterministic-MCP nodes are
unaffected (the deterministic node is a different step type with its own name).

Not the cause / red herrings ruled out: wiring (correct), method/tool selection
(correct), MCP reachability (every server reachable + correct tools direct and
via proxy), publish/unpublish (just a DB flag), and the `mcp_auth_<n>` wallet
"Could not get secret" / "Failed to retrieve token for MCP server" errors —
benign, local MCP servers need no auth (`token_present=False` still works).

## Suggested fix

Make each Agent node's executable tool name unique, e.g.
`agent_step__{node_id}`, so `_register_tools_from_step` no longer collides.
Equivalently: key `_tool_registry` by node id, or don't dedupe `agent_step`
tools by name. A uniqueness/collision warning in `_register_tools_from_step`
(it currently drops silently) would also have surfaced this immediately.

## Workaround (flow-level, until patched)

Wire **all** tool nodes to the **first** agent in execution order. Because every
agent reuses the first agent's `agent_step` closure, and that closure gathers
**all** of the first agent's wired tools, every agent then has access to every
tool and can call the one its own instructions require (the per-step
`custom_instruction` still selects behaviour). Needs empirical confirmation
before relying on it; the structurally safe alternative is to move each tool
call onto a Deterministic-MCP node (different step type, immune to this bug).
