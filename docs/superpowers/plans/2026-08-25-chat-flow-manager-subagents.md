# CHAT_FLOW Manager/Sub-agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `CHAT_FLOW` as one manager agent with two sub-agents, with every pure function moved into a deterministic MCP node.

**Architecture:** Four deterministic `banking-mcp` calls fan off one token chain and compute every fact the decision rests on before any model runs. A single manager agent converses and delegates to an `Intake` or `Recommendation` worker on its `Sub-agents` port. A fifth deterministic call runs after the manager and reads the database, so the final gate tests a stored fact rather than model output.

**Tech Stack:** Python 3 (`fastmcp`, `oracledb`, `httpx`), Open Policy Agent, PAF Agent Builder canvas, pytest, podman-compose, Oracle AI Database 26ai.

## Global Constraints

- The spec is `docs/superpowers/specs/2026-08-25-chat-flow-manager-subagents-design.md`. Branch: `paf-26.7`.
- **A PAF flow runs one Agent node per execution path.** A second agent on the same path never executes. Multi-agent means a manager with workers on its `Sub-agents` port.
- **A `Condition` branch output takes exactly one target.** Fan-out on a branch silently becomes a control chain between the targets.
- **Agent Custom Instructions contain no `{{placeholder}}`.** Placeholders in Prompt nodes are correct and expected.
- **A Deterministic MCP node escapes inner quotes** in its `{"message":"…"}` envelope, so gate regexes match bare words, never quoted keys.
- Every document describes the system as it is. No "was", "previously", "no longer", "26.4", no changelog entries, no status markers.
- **Commit messages: a single subject line. No body, no `Co-Authored-By` trailer.** Tooling may append one — run `git log -1 --format='%B'` after committing and amend if anything extra appears.
- No personal names, emails, hostnames, or locations in any file or commit message.
- Applied Liquibase changesets under `database/` are never edited.
- No container patches. The one patch this deployment carries sets the agent iteration budget and is unrelated to this work.
- The Spring backend, the session envelope and the integration endpoint are untouched.
- Agent Memory stays off: memory is scoped to a PAF user and workflow, and an integration key runs every request as the key's creator.
- Run Python on the host with `venv/bin/python`. `fastmcp` is **not** installed there, so nothing importing it can be tested on the host.

---

### Task 1: Pure decision helpers

The safety-critical logic is which turns are consistent and what payload OPA receives. Both are pure functions of a context dict, so they live in a module free of `fastmcp` and `oracledb` and are unit-tested on the host. `server.py` imports them.

**Files:**

- Create: `src/ai/banking-mcp/gate.py`
- Create: `tests/unit/test_banking_gate.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `GATE_OK: str = "GATE_OK"`, `GATE_FAIL: str = "GATE_FAIL"`, `documents_payload(context: dict) -> dict | None`, `gate_decision(context: dict, task_id: int | None) -> dict`. The unit test imports all four; Task 2's `server.py` imports the two functions.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_banking_gate.py`:

```python
"""Unit tests for banking-mcp's pure decision helpers.

These run on the host: gate.py imports neither fastmcp nor oracledb.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ai" / "banking-mcp"))

from gate import GATE_FAIL, GATE_OK, documents_payload, gate_decision  # noqa: E402

COMPLETE = {
    "customer": {"residency": "resident"},
    "application": {"product_type": "PERSONAL_LOAN", "amount_requested": 10000, "missing": []},
    "profile": {"employment_type": "salaried"},
}
COLLECTING = {
    "customer": {"residency": "resident"},
    "application": {"product_type": "PERSONAL_LOAN", "amount_requested": None,
                    "missing": ["amount_requested"]},
    "profile": {"employment_type": "salaried"},
}
NO_APP = {"customer": {"residency": "resident"}, "application": None,
          "profile": {"employment_type": "salaried"}}
BAD = {"error": "invalid_or_expired_session"}


def test_documents_payload_builds_the_opa_input():
    assert documents_payload(COMPLETE) == {
        "product_type": "PERSONAL_LOAN",
        "employment_type": "salaried",
        "residency": "resident",
        "amount": 10000,
    }


@pytest.mark.parametrize("ctx", [COLLECTING, NO_APP, BAD], ids=["collecting", "no-app", "bad"])
def test_documents_payload_is_none_when_the_application_is_not_complete(ctx):
    assert documents_payload(ctx) is None


def test_gate_fails_on_an_invalid_session():
    assert gate_decision(BAD, None) == {"gate": GATE_FAIL, "stage": "INVALID_SESSION", "task_id": None}


@pytest.mark.parametrize("ctx", [COLLECTING, NO_APP], ids=["collecting", "no-app"])
def test_gate_passes_a_collecting_turn_with_no_decision(ctx):
    assert gate_decision(ctx, None) == {"gate": GATE_OK, "stage": "COLLECTING", "task_id": None}


def test_gate_passes_a_complete_application_with_a_recorded_decision():
    assert gate_decision(COMPLETE, 42) == {"gate": GATE_OK, "stage": "DECIDED", "task_id": 42}


def test_gate_fails_a_complete_application_with_no_decision():
    assert gate_decision(COMPLETE, None) == {
        "gate": GATE_FAIL, "stage": "DECISION_MISSING", "task_id": None,
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python -m pytest tests/unit/test_banking_gate.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'gate'`.

- [ ] **Step 3: Write the implementation**

Create `src/ai/banking-mcp/gate.py`:

```python
"""Pure decision helpers for the session-scoped banking-mcp tools.

Free of fastmcp and oracledb so the logic can be unit-tested on the host,
where neither package is installed.
"""

from __future__ import annotations

from typing import Any

GATE_OK = "GATE_OK"
GATE_FAIL = "GATE_FAIL"


def documents_payload(context: dict[str, Any]) -> dict[str, Any] | None:
    """Build the OPA `decisioning.required_documents` input from a context.

    Returns None when the application is absent or still collecting, so the
    caller fails closed instead of evaluating a partial payload.
    """
    if context.get("error"):
        return None
    application = context.get("application") or {}
    if not application or application.get("missing"):
        return None
    profile = context.get("profile") or {}
    customer = context.get("customer") or {}
    return {
        "product_type": application.get("product_type") or "PERSONAL_LOAN",
        "employment_type": profile.get("employment_type"),
        "residency": customer.get("residency"),
        "amount": application.get("amount_requested"),
    }


def gate_decision(context: dict[str, Any], task_id: int | None) -> dict[str, Any]:
    """Decide whether this turn is safe to show the customer.

    A turn is consistent when the application is still collecting, so no
    decision is due, or when a HITL task exists for it. The flow's final gate
    matches the bare word in `gate`.
    """
    if context.get("error"):
        return {"gate": GATE_FAIL, "stage": "INVALID_SESSION", "task_id": None}
    application = context.get("application") or {}
    if not application or application.get("missing"):
        return {"gate": GATE_OK, "stage": "COLLECTING", "task_id": None}
    if task_id is not None:
        return {"gate": GATE_OK, "stage": "DECIDED", "task_id": task_id}
    return {"gate": GATE_FAIL, "stage": "DECISION_MISSING", "task_id": None}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python -m pytest tests/unit/test_banking_gate.py -v`
Expected: 9 passed.

- [ ] **Step 5: Confirm the E2E harness still collects**

Run: `venv/bin/python -m pytest tests/ --collect-only -q | tail -3`
Expected: the unit tests and the existing scenarios both collect; no import errors.

- [ ] **Step 6: Commit**

```bash
git add src/ai/banking-mcp/gate.py tests/unit/test_banking_gate.py
git commit -m "feat(banking-mcp): add pure gate and document-payload helpers"
```

---

### Task 2: Session-scoped MCP tools

Three tools join `banking-mcp`, each taking only `session_token`, resolving state through the existing `_get_context_impl`, and failing closed — the shape `evaluate_eligibility_for_session` already establishes at `src/ai/banking-mcp/server.py:328`.

**Files:**

- Modify: `src/ai/banking-mcp/server.py` (add `_REGISTRY_URL` beside `_OPA_URL` near line 49; append three tools before the `if __name__ == "__main__":` block)
- Modify: `deploy/podman/compose.local.yml` (the `banking-mcp` service `environment:` block, beside `OPA_URL`)

**Interfaces:**

- Consumes: `documents_payload(context)` and `gate_decision(context, task_id)` from `gate.py`; the existing `_get_context_impl(session_token) -> dict`, `_audit(...)`, `_now_utc()`, `_OPA_URL`.
- Produces: MCP tools `required_documents_for_session(session_token)`, `verify_employer_for_session(session_token)`, `hitl_status_for_session(session_token)`. Task 4's blueprint wires all three as Deterministic MCP nodes.

- [ ] **Step 1: Add the registry address**

In `src/ai/banking-mcp/server.py`, directly below the `_OPA_URL` assignment:

```python
_REGISTRY_URL = os.getenv("REGISTRY_URL", "http://registry-api:8600").rstrip("/")
```

And add the import beside the existing ones at the top of the file:

```python
from gate import documents_payload, gate_decision
```

- [ ] **Step 2: Add `required_documents_for_session`**

Append before `if __name__ == "__main__":`:

```python
@mcp.tool()
def required_documents_for_session(session_token: str) -> dict:
    """Deterministic document set: token in -> the required doc_type list out.

    Resolves the opaque session token and evaluates `decisioning.required_documents`
    with the product, employment, residency and amount the DB already holds. No
    model constructs the payload, so the policy always sees the fields where it
    expects them.

    Fails closed: an invalid token or an incomplete application returns an empty
    list, which the manager treats as "no evidence yet".
    """
    started = _now_utc()
    print(f"[required_documents_for_session] called session_token={session_token!r}", flush=True)
    ctx = _get_context_impl(session_token)
    payload = documents_payload(ctx)
    if payload is None:
        print("[required_documents_for_session] -> incomplete or invalid, fail-closed", flush=True)
        return {"required": [], "amount_band": None, "rationale": None}
    try:
        resp = httpx.post(f"{_OPA_URL}/v1/data/decisioning/required_documents",
                          json={"input": payload}, timeout=5.0)
        resp.raise_for_status()
        res = resp.json().get("result") or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[required_documents_for_session] OPA error: {exc}", flush=True)
        return {"required": [], "amount_band": None, "rationale": None}
    out = {
        "required": res.get("required", []),
        "amount_band": res.get("amount_band"),
        "rationale": res.get("rationale"),
    }
    _audit("required_documents_for_session", "SUCCESS", started, _now_utc(), payload, out,
           session_token=session_token)
    print(f"[required_documents_for_session] -> {out['required']}", flush=True)
    return out
```

- [ ] **Step 3: Add `verify_employer_for_session`**

Append below it:

```python
@mcp.tool()
def verify_employer_for_session(session_token: str) -> dict:
    """Deterministic employer check: token in -> the registry record out.

    Reads profile.employer_name from the DB-derived context and queries the
    company registry directly. The name is never copied by a model, which is
    what makes a wrong-company answer impossible.

    Fails closed: an invalid token or a missing employer name returns
    registered=false with trading_status "unknown".
    """
    started = _now_utc()
    print(f"[verify_employer_for_session] called session_token={session_token!r}", flush=True)
    closed = {"name": None, "registered": False, "trading_status": "unknown"}
    ctx = _get_context_impl(session_token)
    if ctx.get("error"):
        print("[verify_employer_for_session] -> invalid session, fail-closed", flush=True)
        return closed
    name = ((ctx.get("profile") or {}).get("employer_name") or "").strip()
    if not name:
        print("[verify_employer_for_session] -> no employer name, fail-closed", flush=True)
        return closed
    try:
        resp = httpx.get(f"{_REGISTRY_URL}/v1/companies/verify",
                         params={"name": name}, timeout=5.0)
        resp.raise_for_status()
        out = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[verify_employer_for_session] registry error: {exc}", flush=True)
        return {**closed, "name": name}
    _audit("verify_employer_for_session", "SUCCESS", started, _now_utc(), {"name": name}, out,
           session_token=session_token)
    print(f"[verify_employer_for_session] -> registered={out.get('registered')} "
          f"trading_status={out.get('trading_status')}", flush=True)
    return out
```

- [ ] **Step 4: Add `hitl_status_for_session`**

Append below it. The SQL reads the customer's open application's HITL task through the same REPORTING connection the other tools use; reuse whatever connection helper `_get_context_impl` uses in this file rather than opening a new style of connection.

```python
@mcp.tool()
def hitl_status_for_session(session_token: str) -> dict:
    """Deterministic turn check: token in -> {"gate", "stage", "task_id"} out.

    Reads the context and the HITL queue and reports whether this turn is
    consistent: still collecting, so no decision is due, or complete with a task
    recorded. The flow's final gate matches the bare word in `gate`, because a
    Deterministic MCP node escapes the inner quotes of its JSON envelope.
    """
    started = _now_utc()
    print(f"[hitl_status_for_session] called session_token={session_token!r}", flush=True)
    ctx = _get_context_impl(session_token)
    task_id = None
    application = ctx.get("application") or {}
    application_id = application.get("id") if application else None
    if application_id is not None:
        with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(task_id) FROM APP.hitl_task WHERE application_id = :a",
                    a=int(application_id),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    task_id = int(row[0])
    out = gate_decision(ctx, task_id)
    _audit("hitl_status_for_session", "SUCCESS", started, _now_utc(),
           {"application_id": application_id}, out, session_token=session_token)
    print(f"[hitl_status_for_session] -> gate={out['gate']} stage={out['stage']} "
          f"task_id={out['task_id']}", flush=True)
    return out
```

This file opens connections inline rather than through a helper, exactly as
written above — `_get_context_impl` does the same at `server.py:256`. `DB_USER`,
`DB_PASSWORD` and `DB_DSN` are already module-level in this file.

- [ ] **Step 5: Add the registry address to compose**

In `deploy/podman/compose.local.yml`, in the `banking-mcp` service `environment:` block, directly below the `OPA_URL` line:

```yaml
REGISTRY_URL: "http://registry-api:8600"
```

- [ ] **Step 6: Verify the file parses and the compose file is valid**

Run:

```bash
venv/bin/python -c "import ast;ast.parse(open('src/ai/banking-mcp/server.py').read())" && echo "server.py parses"
venv/bin/python -c "import yaml;yaml.safe_load(open('deploy/podman/compose.local.yml'));print('compose parses')"
grep -n "REGISTRY_URL" deploy/podman/compose.local.yml src/ai/banking-mcp/server.py
```

Expected: both parse; `REGISTRY_URL` appears once in each file. The tools themselves are exercised in Task 6 — they need the container, the DB, OPA and the registry.

- [ ] **Step 7: Commit**

```bash
git add src/ai/banking-mcp/server.py deploy/podman/compose.local.yml
git commit -m "feat(banking-mcp): add session-scoped documents, employer and HITL tools"
```

---

### Task 3: Point the tooling at `CHAT_FLOW`

`manage.py` and the harness resolve the flow by the literal name `CHAT_WORKFLOW`.

**Files:**

- Modify: `manage.py` (`_discover_chat_workflow_id` and its two callers; the `paf api-key` and `paf link-flow` docstrings)
- Modify: `tests/conftest.py` (module docstring and fixture docstrings)
- Modify: `tests/test_chat_workflow.py` (module docstring line 1 and the comment at line 53)

**Interfaces:**

- Consumes: nothing.
- Produces: `_discover_chat_flow_id(session: requests.Session) -> str` resolving the name `CHAT_FLOW`. `paf link-flow` and `paf api-key` call it.

- [ ] **Step 1: Rename the resolver and the name it looks for**

In `manage.py`, rename `_discover_chat_workflow_id` to `_discover_chat_flow_id`, change the name it matches from `"CHAT_WORKFLOW"` to `"CHAT_FLOW"`, and update its error message to name `CHAT_FLOW` and `paf/flows/CHAT_FLOW.md`. Update both call sites — in `paf link-flow` and `paf api-key`.

- [ ] **Step 2: Update the command docstrings**

In the same file, every docstring mentioning `CHAT_WORKFLOW` names `CHAT_FLOW` instead. Check `paf link-flow`, `paf api-key`, and the comment at `manage.py:548`.

- [ ] **Step 3: Update the harness docstrings**

In `tests/conftest.py` and `tests/test_chat_workflow.py`, replace `CHAT_WORKFLOW` with `CHAT_FLOW` and `paf/flows/CHAT_WORKFLOW.md` with `paf/flows/CHAT_FLOW.md`. Do not change any fixture name, assertion or scenario.

- [ ] **Step 4: Verify**

```bash
venv/bin/python manage.py paf --help >/dev/null && echo "cli loads"
venv/bin/python manage.py paf link-flow --help | head -5
venv/bin/python -m pytest tests/ --collect-only -q | tail -3
grep -rn "CHAT_WORKFLOW" manage.py tests/ || echo "no CHAT_WORKFLOW references remain"
```

Expected: the CLI loads, the help text names `CHAT_FLOW`, tests collect, and the final grep returns nothing.

- [ ] **Step 5: Commit**

```bash
git add manage.py tests/conftest.py tests/test_chat_workflow.py
git commit -m "chore: resolve the published flow by its CHAT_FLOW name"
```

---

### Task 4: Rewrite the flow blueprint

`paf/flows/CHAT_WORKFLOW.md` is the flow-build source of truth. It describes the three-agent gate pipeline, which cannot run. It is replaced by `paf/flows/CHAT_FLOW.md` describing the design in the spec.

**Files:**

- Create: `paf/flows/CHAT_FLOW.md`
- Delete: `paf/flows/CHAT_WORKFLOW.md`, `paf/flows/chat_workflow.flow.json`, `paf/flows/chat_flow.paf`
- Modify: any document linking to the old blueprint — check `README.md`, `LOCAL.md`, `docs/DESIGN.md`, `docs/DECISIONING-ENGINE-USE-CASE.md`, `BACKLOG.md`, `issues/*.md`

**Interfaces:**

- Consumes: the node graph, tool table, agent contracts and gate word from the spec.
- Produces: `paf/flows/CHAT_FLOW.md`, the build source of truth Task 6 follows.

- [ ] **Step 1: Write the new blueprint**

Create `paf/flows/CHAT_FLOW.md` carrying over from `CHAT_WORKFLOW.md`: the Purpose, Flow inputs, Test prompts, Operating constraints and Trust boundary sections, which are unchanged. Replace the node graph and build sequence with the spec's design. It must contain:

- The mermaid node graph from the spec.
- A build sequence, one node per step, ordered so every wire's source already exists.
- The "Before you start" rules, carried over from `CHAT_WORKFLOW.md` and extended with the three global constraints at the top of this plan: one agent per execution path, one target per condition branch, no placeholders in Custom Instructions.
- The `subAgents` template note: an edge from a worker's `Agent` output to the manager's `Sub-agents` input is not sufficient on its own; the manager's `subAgents` template value must list the worker node ids, which the canvas writes when the wire is drawn.
- The three Custom Instruction blocks — manager, Intake worker, Recommendation worker — with no `{{placeholder}}` in any of them. Derive them from the existing blocks in `CHAT_WORKFLOW.md`: the manager keeps the stage-selection logic, the Intake worker keeps the collection rules and `upsert_application` contract, the Recommendation worker keeps the tier rules, reason codes and the three customer sentences.
- The Prompt node templates, which do keep their placeholders: the manager prompt takes `{{context}}`, `{{input}}`, `{{eligibility}}`, `{{documents}}`, `{{employer}}`; the JSON-wrap prompt takes `{{token}}`; the assert-wrap prompt takes `{{token}}` and one port fed by the manager to force ordering.
- A wiring checklist table listing every edge, in the shape the old one used.

- [ ] **Step 2: Remove the superseded flow artefacts**

```bash
git rm paf/flows/CHAT_WORKFLOW.md paf/flows/chat_workflow.flow.json paf/flows/chat_flow.paf
```

- [ ] **Step 3: Repoint every link**

```bash
grep -rln "CHAT_WORKFLOW" README.md LOCAL.md BACKLOG.md DEMO.md docs/*.md issues/*.md
```

For each file, change `paf/flows/CHAT_WORKFLOW.md` to `paf/flows/CHAT_FLOW.md` and the flow name to `CHAT_FLOW`. Leave `docs/superpowers/` alone — it is a dated record.

- [ ] **Step 4: Verify**

```bash
grep -rn "CHAT_WORKFLOW\|chat_workflow.flow.json\|chat_flow.paf" README.md LOCAL.md BACKLOG.md DEMO.md docs/*.md issues/*.md paf/ manage.py tests/ || echo "no stale references"
grep -cE "\{\{[a-z_]+\}\}" paf/flows/CHAT_FLOW.md
```

Expected: the first returns nothing. The second is non-zero — Prompt templates keep their placeholders. Then confirm no Custom Instruction block contains one:

````bash
venv/bin/python - <<'PY'
import re, pathlib
t = pathlib.Path("paf/flows/CHAT_FLOW.md").read_text()
for m in re.finditer(r"Custom Instructions[^\n]*\n+```\n(.*?)```", t, re.S):
    ph = re.findall(r"\{\{\s*\w+\s*\}\}", m.group(1))
    print(f"CI block: {len(m.group(1))} chars, placeholders={ph or 'NONE'}")
PY
````

Expected: three CI blocks, each `placeholders=NONE`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs(flow): describe CHAT_FLOW as a manager with sub-agents"
```

---

### Task 5: Document the pattern and file the constraint

Two durable artefacts: the house rule for building any future flow, and the product report for the constraint that is nowhere in the documentation.

**Files:**

- Modify: `docs/DESIGN.md` (add a "Multi-agent in PAF" section)
- Create: `issues/12-one-agent-per-execution-path.md`

**Interfaces:**

- Consumes: the reproduction evidence in the spec's Problem section.
- Produces: the house pattern section and the issue file.

- [ ] **Step 1: Add the pattern section to `docs/DESIGN.md`**

A section titled "Multi-agent in PAF", placed near the existing agent-architecture discussion, stating in present tense:

- A flow runs one Agent node per execution path.
- Multi-agent means a manager agent with workers on its `Sub-agents` port; the manager holds no tools and each worker holds only its own, which is what keeps a write tool unreachable from a path that must not write.
- Wiring the `Sub-agents` edge is not sufficient on its own — the manager's `subAgents` template value must list the worker node ids, which the canvas writes when the wire is drawn.
- Sub-agent calls happen inside the manager's executor, so no `Condition` can sit between them. Gates go before the agent or after it.
- A pure function of values already in the database belongs in a deterministic MCP node, not in an agent. `banking-mcp`'s `*_for_session` tools are the pattern.

- [ ] **Step 2: Write the issue**

Create `issues/12-one-agent-per-execution-path.md` in the house format used by `issues/04-agent-max-iterations-5-cap.md` — `# title`, `## What`, `## Reproduce`, `## Source confirmation`, `## Why it matters`, `## Suggested fix`. Content:

**What** — a flow containing two Agent nodes on the same execution path silently stops after the first. The first agent's message is returned as the flow's result and no downstream node runs. No error is raised.

**Reproduce** — three minimal flows, each `Chat input → …  → Chat output`:

1. `Prompt → Agent1 → Condition(regex `.\*`) → Prompt2 → Agent2` — Agent2 never runs; the reply is Agent1's message.
2. The same two agents on separate branches of one Condition — both run, one per turn.
3. A manager agent with a worker on its `Sub-agents` port — the worker runs and the manager returns its output.

Note that the failure is silent in shape 1: no validation error, no log line naming the skipped node.

**Source confirmation** — a flow's agent is built without `caller_input_mode` at `app/models/agentBuilder/steps/customSteps/AgentStep.py:1321`, taking the default `CallerInputMode.ALWAYS` from `:791`; sub-agents are built with `CallerInputMode.NEVER` at `:1066`. An `ALWAYS` agent yields to the caller after its message, which ends the flow's turn.

**Why it matters** — the palette lets you place two Agent nodes on one path and the validator accepts it, so the topology looks supported. The documentation's sample workflows all use one agent, and the multi-agent sample uses sub-agents, but neither states the constraint. A flow built the obvious way fails with no diagnostic pointing at the cause.

**Suggested fix** — reject the topology when a workflow is saved, naming the second agent and the path; or document the constraint on the Agent node page beside the `Sub-agents` connector.

- [ ] **Step 3: Verify**

```bash
grep -n "Multi-agent in PAF" docs/DESIGN.md
ls issues/
grep -rniE "previously|no longer|used to |26\.4" docs/DESIGN.md issues/12-one-agent-per-execution-path.md || echo "no historical language"
```

Expected: the section exists, the issue file is listed, and the final grep returns nothing.

- [ ] **Step 4: Commit**

```bash
git add docs/DESIGN.md issues/12-one-agent-per-execution-path.md
git commit -m "docs: record the multi-agent pattern and the one-agent-per-path constraint"
```

---

### Task 6: Rebuild and deploy

Operational. Runs on the developer machine and produces no commits.

**Files:**

- Modify: `.env` (via `manage.py`; gitignored, never committed)

**Interfaces:**

- Consumes: Tasks 1-5.
- Produces: a running stack with `banking-mcp` serving the three new tools and a published `CHAT_FLOW`, plus `PAF_AGENT_ID` and `PAF_API_KEY` pointing at it.

- [ ] **Step 1: Rebuild `banking-mcp` onto the new code**

```bash
podman compose -f deploy/podman/compose.local.yml up -d --build --force-recreate --no-deps banking-mcp
podman logs --tail 20 paf-banking-mcp
```

Expected: the container starts with no import error. An `ImportError` for `gate` means the module did not land in the image — check the Containerfile copies the whole directory.

- [ ] **Step 2: Confirm the three tools are exposed**

```bash
podman exec paf-oracle-free-26ai curl -s -X POST http://banking-mcp:8503/mcp/ \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | tr ',' '\n' | grep -i '"name"'
```

Expected: `get_context`, `lookup_application`, `evaluate_eligibility_for_session`, `required_documents_for_session`, `verify_employer_for_session`, `hitl_status_for_session`.

- [ ] **Step 3: Refresh the MCP tool list in PAF**

In the PAF UI, open the `banking-mcp` server registration and run its connection test so the new tools appear in the Deterministic MCP node's tool dropdown.

- [ ] **Step 4: Build `CHAT_FLOW` in the canvas**

Follow `paf/flows/CHAT_FLOW.md` step by step, left to right. Publish it when the graph is complete.

- [ ] **Step 5: Bind and key the flow**

```bash
venv/bin/python manage.py paf link-flow
venv/bin/python manage.py paf api-key
podman compose -f deploy/podman/compose.local.yml up -d --force-recreate --no-deps application-backend
```

Expected: `link-flow` reports every MCP node already correct or rebinds them; `api-key` writes `PAF_AGENT_ID` and `PAF_API_KEY`.

- [ ] **Step 6: Smoke-test one turn**

```bash
TOK=$(curl -s -X POST http://localhost:5173/v1/login -H 'Content-Type: application/json' \
  -d '{"customerId":1}' | venv/bin/python -c 'import sys,json;print(json.load(sys.stdin)["sessionToken"])')
curl -s -X POST http://localhost:5173/v1/chat -H 'Content-Type: application/json' \
  -H "X-Session-Token: $TOK" -d '{"message":"yes, please submit my application"}'
```

`/v1/chat` is asynchronous and answers with a `turnId`; read the reply with:

```bash
curl -s http://localhost:5173/v1/chat/history -H "X-Session-Token: $TOK" | venv/bin/python -m json.tool | tail -20
```

Expected: the last message is a customer sentence with no `[[…]]` marker.

---

### Task 7: Validate

**Files:**

- Modify: `tests/test_chat_workflow.py` only if a `reasoning_re` pattern needs loosening.

**Interfaces:**

- Consumes: the running stack from Task 6.
- Produces: a green harness, or a recorded reason why a scenario cannot pass.

- [ ] **Step 1: Run the tier scenarios**

```bash
venv/bin/python -m pytest tests/test_chat_workflow.py -v
```

Expected: every scenario passes. Each turn takes minutes.

- [ ] **Step 2: Confirm one HITL row per completed turn**

```bash
podman exec -i paf-oracle-free-26ai bash -lc \
  'sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1' <<'SQL'
SET PAGESIZE 50 LINESIZE 200 FEEDBACK OFF
SELECT task_id, application_id, agent_recommendation FROM APP.hitl_task ORDER BY task_id;
EXIT;
SQL
```

Expected: one row per completed scenario, with the tier the scenario table predicts.

- [ ] **Step 3: Handle a failing `reasoning_re`**

If a scenario fails only on `reasoning_re`, read the stored `agent_reasoning` for that task and widen the pattern to match how the Recommendation worker phrases it. Do not weaken the tier assertion or the row-count assertion — those are the acceptance criteria. If a tier is wrong, that is a real failure: stop and report it rather than adjusting the test.

- [ ] **Step 4: Run the backend suite**

```bash
cd src/backend && ./gradlew test
```

Expected: BUILD SUCCESSFUL. Nothing in this plan touches the backend, so a failure here means something else regressed.

- [ ] **Step 5: Commit any test adjustment**

```bash
git add tests/test_chat_workflow.py
git commit -m "test: match the recommendation worker's reasoning wording"
```

- [ ] **Step 6: Final check**

```bash
git status --short
venv/bin/python -m pytest tests/unit -v
```

Expected: a clean tree and the unit tests still green.
