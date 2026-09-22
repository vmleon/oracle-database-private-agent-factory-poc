# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A banking loan-decisioning PoC on Oracle AI Database 26ai + Oracle Private Agent Factory (PAF). A customer chats with an agent; the agent collects the application, gathers evidence server-side, and files a recommendation packet to a human-review queue. **A human always makes the final decision** — the agent never decides, and that is a design invariant, not a limitation.

OCI is the only deployment target. There is no local/podman path.

## Commands

Everything goes through `manage.py` (Click). Activate the venv first: `source venv/bin/activate`.

Tests:

```bash
./venv/bin/python -m pytest tests/unit -q          # host-side, no infra needed
python manage.py cloud test                        # end-to-end, runs on the bastion
python manage.py cloud test -k alice               # single e2e scenario (args pass through to pytest)
python manage.py cloud bench                       # adversarial conversation bench, 25-45 min
```

`tests/unit` runs anywhere. `tests/test_chat_workflow.py` needs PAF and the private-endpoint ADB, and `tests/conversation/` needs the backend as well, so `cloud test` and `cloud bench` ship them to the bastion — never run either from the host.

Ad-hoc SQL against the deployed ADB: `python manage.py cloud sql "SELECT ..."` (one statement, as `ADMIN`, over the bastion).

There is no linter configured.

## Architecture

### The decision path

Customer → React SPA → Spring `ChatService` → PAF integration endpoint → `CHAT_FLOW` → MCP wrappers → ADB.

`CHAT_FLOW` is **one manager agent with two sub-agent workers**, fed by five deterministic `banking-mcp` nodes. The manager holds no tools. Four nodes run _before_ it (`get_context`, `evaluate_eligibility_for_session`, `required_documents_for_session`, `verify_employer_for_session`) so every fact is computed server-side with no LLM in the loop; a fifth (`hitl_status_for_session`) runs after. The manager delegates to `Intake` (collects amount/term/purpose) or `Recommendation` (files the task).

`RESEARCH_WORKFLOW` is the backoffice counterpart: one Agent node holding no tools, fed by five deterministic `research-mcp` nodes off one wired task id. `research-mcp` is the third database identity's flow — it connects as `BACKOFFICE_AGENT_RO`, `SELECT` only, no `EXECUTE`, no write grant, so the research agent is structurally unable to decide anything.

**The tier is not chosen by a model.** `banking-mcp/gate.py:tier_from()` is a pure function of the OPA eligibility result, the employer record and the KYC and AML findings — a compliance `deny` is a bar that forces `DECLINE`. The worker reads the tier back and writes the customer's sentence within a disclosure policy — it may name a _factor_, never a number. See `paf/flows/CHAT_FLOW.md` for the full blueprint and the exact custom-instruction blocks.

### Where to look

| Question                                         | File                                                          |
| ------------------------------------------------ | ------------------------------------------------------------- |
| Architecture, locked decisions, what is in scope | `docs/DESIGN.md`                                              |
| What is not built yet                            | `BACKLOG.md` — every unimplemented design claim has a section |
| PAF product defects hit during the build         | `issues/NN-*.md`                                              |
| Deployment workarounds, symptom → cause → fix    | `docs/TROUBLESHOOT.md`                                        |
| Flow build steps, node by node                   | `paf/flows/CHAT_FLOW.md`, `paf/flows/RESEARCH_WORKFLOW.md`    |
| Banking terms (DTI, PTI, KYC, AML)               | `docs/GLOSSARY.md`                                            |
| What the conversation suite attacks              | `docs/TEST-BENCH.md`                                          |

### Database identities — the rule that matters

Two kinds of account, and the split is load-bearing:

- **Owners** (`BANK_CORE`, `BANK_VIEWS`, `BANK_TOOLS`) own objects and have **no `CREATE SESSION`**. Nothing logs in as them.
- **Clients** log in, own nothing, and hold only their consumer's grants: `PAF_PLATFORM` (PAF metadata, zero banking grants), `SVC_BACKEND`, `CUSTOMER_AGENT_RO`, `CUSTOMER_AGENT_RW`, `BACKOFFICE_AGENT_RO`. Each has its own password.

**Privilege follows the audience that can reach the identity.** The customer-facing agent and the backoffice agent never share a login, so a prompt injection against the chat agent is bounded by what `CUSTOMER_AGENT_RO` can select. When adding a database call, ask which audience reaches it and grant to that client — never widen an existing one, and never give a data grant to `PAF_PLATFORM`.

The entire grant matrix is `database/liquibase/020-client-grants.yaml`. Keep it that way; grants added elsewhere defeat the point of having one file to read.

### Trust boundary

- **Never take an identity from user input.** No `customer_id` from chat text, prompts or URLs. The Spring backend mints an opaque `sess_...` token at login; every MCP tool takes only that token and resolves the customer server-side. This is why the tools are named `*_for_session`.
- The session token is **wired** through the deterministic nodes and never transcribed by an LLM on any read path — streamed tool-call arguments can drop or duplicate a character.
- **The disclosure policy is enforced, not requested.** The worker's instructions ask it to name a factor and never a number; `Disclosure.screen` in `ChatService.runTurn` is what holds it. Every reply passes through that one line before it reaches `chat_message` or the SSE channel, so a new reply path must go through it too.
- `upsert_application` is agentic **on purpose**: a corrupted token there fails closed and the next turn retries.
- MCP wrappers do not write `decision_audit` directly; they POST to the Application Service, which writes it.

## Conventions

**Liquibase.** Never edit an applied changeset — extend with a new id, or checksum validation fails. The exception is a full teardown (`cloud down` destroys the ADB), when editing in place is correct because the changelog reapplies from scratch. Changesets are `NNN-name.yaml`, registered in `db.changelog-master.yaml`, with contexts `adb` and `seed`.

**A `runOnChange: true` changeset is edited in place — the newest one that defines the object.** `CREATE OR REPLACE` definitions carry `runOnChange`, so Liquibase re-runs them on a checksum change instead of failing. `PKG_AGENT_TOOLS` is defined in `009` and redefined in `017`; editing `009` re-runs it and silently reverts `017`, leaving a package body whose signatures no longer match the spec. Grep for every changeset that defines the object and edit the last one. `SELECT status FROM ALL_OBJECTS WHERE object_name = '<NAME>'` after a `cloud redeploy ops` is the check.

**No hardcoded IDENTITY ids.** Seeds and tests resolve by `full_name`; hardcoded `customer_id` / `application_id` break with `ORA-02291` when identity gaps shift.

**The PAF kit is vendor code.** `paf/dist/` holds the tarball; `paf-kit/` is a read-only extraction for source reading. Never patch either. `PAF_PLATFORM`'s heavy grants (`INSERT ANY TABLE`, `CREATE USER`, `DATA_PUMP_DIR`) are the kit's documented requirement — leave them and keep everything else off that identity.

**Generation model.** `openai.gpt-oss-120b`. PAF's OCI GenAI stream parsers are incomplete for `cohere.*` (manager never delegates) and `meta.*` (bare `[DONE]`). `manage.py setup` refuses both. `paf gen-model` pushes a change to the live config.

**A payload change reaches a running tier through `cloud redeploy`, not `cloud up`.** `/var/lib/paf-poc/bootstrap.ok` makes later boots a no-op, and Terraform keys payload objects by name, so `cloud up` uploads a new archive and changes nothing on the instance — the plan reads like a success. `cloud redeploy <tier>` clears the sentinel and re-runs that tier's play against the uploaded payload. Terraform variables are rendered into cloud-init at instance creation, so changing one still needs a rebuild.

**The backend keeps its integration key across `cloud redeploy backend`; a rebuilt instance does not.** The play creates the key file only when it is absent, so a redeploy leaves it alone, while a new instance starts with an empty one and every chat turn fails on TLS until `paf push-key` delivers the key and PAF's certificate again. `info` reports which state the backend is in under Agent, so check it after either.

## Docs style

The repo describes the **final state**, as if the current version is the only one that ever existed. No "previously", "no longer", "was X", no status markers, no dead-end retellings. When something is removed, delete its traces rather than annotating that it is gone. Iteration history and PAF war stories go in `issues/`, never in the docs.

Diagrams are **mermaid**, never ASCII art.

**Anything off the happy path goes in a blockquote.** A runbook is read top to
bottom by someone in a hurry, so a command that does not belong to the current
step is a trap sitting in the flow of the page. Put it behind `>` — plain
markdown, not the GitHub `[!NOTE]` extension — and open with the condition that
excuses the reader, before the command:

```markdown
> **Not part of a deployment from scratch** — skip it and continue at §3.
>
> To change the generation model on an **already running** install, ...
```

Same for recovery paths, teardown extras and "only if X happened" detours.

`BACKLOG.md` carries its own maintenance rule: when an item is done, remove the section and delete the related `issues/` file. Partial improvements refresh the issue instead.

---

You have user-level OpenAI Codex and Gemini CLI configs. Reply `/import` to see what is importable (MCP servers, slash commands, subagents, skills, instructions); the scan prints a digest you then apply with `/import --yes=<digest>`.
