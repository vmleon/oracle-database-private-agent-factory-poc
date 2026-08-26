"""HITL MCP server — exposes the in-DB create_hitl_task PL/SQL function as
an MCP tool so PAF's CHAT_WORKFLOW can write its recommendation packet.

Why an MCP server instead of a PAF SQL Query node:
PAF's SQL Query node is read-only by design (only SELECT-like queries are
allowed — see docs/PAF.md §10). Anything with side effects has to go
through MCP/REST. `create_hitl_task` inserts a row into APP.hitl_task and
enqueues HITL_REQUEST in the same transaction, so it lives behind this
wrapper.

Security boundary:
- This container connects to Oracle as AGENT_FACTORY (the schema PAF
  itself uses). AGENT_FACTORY has EXECUTE on AGENT_TOOLS.PKG_AGENT_TOOLS
  (granted in Liquibase changeset 007).
- The package body runs with definer's rights as AGENT_TOOLS, which has
  INSERT + SELECT on APP.hitl_task (granted in 007 + 009) and ENQUEUE on
  APP.HITL_REQUEST (granted in 009).
- This wrapper does NOT bypass any of those grants — it just gives PAF a
  side-effect-capable tool surface to call the function.

Wired into CHAT_WORKFLOW only. RESEARCH_WORKFLOW is read-only by design (no
side-effect tools).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid

import httpx
import oracledb
from fastmcp import Client, FastMCP

mcp = FastMCP("hitl-mcp")


DB_DSN = (
    f"{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_SERVICE']}"
)
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

_AUDIT_URL = os.getenv("BACKEND_URL", "http://application-backend:8090").rstrip("/") + "/v1/audit/tool-call"
_BANKING_MCP_URL = os.getenv("BANKING_MCP_URL", "http://banking-mcp:8503/mcp")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _audit(tool_name, status, started, ended, tool_input, tool_output, *, session_token):
    """Best-effort per-tool audit to the Application Service. The application is resolved
    server-side from session_token — never sent as a raw id. Never raises — an audit
    failure must not break the live tool call."""
    try:
        httpx.post(_AUDIT_URL, json={
            "sessionToken": session_token,
            "toolName": tool_name,
            "status": status,
            "startedAt": started.isoformat(),
            "endedAt": ended.isoformat(),
            "toolInput": json.dumps(tool_input, default=str),
            "toolOutput": json.dumps(tool_output, default=str),
        }, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 — audit is fire-and-forget
        print(f"[audit] skipped ({tool_name}): {exc}", flush=True)


async def _recommendation_packet(session_token: str) -> dict:
    """The server-computed decision packet from banking-mcp: tier, reasoning and
    the evidence the review portal renders. Returns an empty packet if it cannot
    be reached — the caller then records nothing."""
    try:
        async with Client(_BANKING_MCP_URL) as client:
            result = await client.call_tool(
                "recommend_tier_for_session", {"session_token": session_token}
            )
        return json.loads(result.content[0].text)
    except Exception as exc:  # noqa: BLE001 — fail closed, never write a guess
        print(f"[create_hitl_task] recommendation lookup failed: {exc}", flush=True)
        return {}


@mcp.tool()
async def create_hitl_task(
    session_token: str,
    explore_hints: str | None = None,
) -> dict:
    """Write the CHAT_WORKFLOW recommendation packet to APP.hitl_task and
    enqueue HITL_REQUEST in the same transaction. Returns the new task_id
    and the server-generated `agent_run_id`.

    This is CHAT_WORKFLOW's ONLY side-effect tool: every successful run ends
    with exactly one call. The human reviewer (not the agent) closes the
    task; that close is what writes the Blockchain `decision` row.

    Everything recorded is computed server-side from the opaque session token:
    the application, the recommendation tier, its reasoning and the evidence
    packet. No agent names an application, chooses a tier or re-words a policy
    message, so what the reviewer reads is what the policy actually returned.

    The tier is returned to you — phrase the customer sentence for THAT tier,
    not for one you inferred yourself.

    Argument extraction guidance for the LLM:
      - session_token  — the opaque `sess_...` token from the manager's
                         message. Copy it exactly; never invent one.
      - explore_hints  — REVIEW-only: JSON string array of follow-up
                         questions/checks the reviewer should examine.
                         Pass null otherwise.

    Note: `agent_run_id` is generated server-side as a UUID-4 and returned
    in the response. The agent must NOT supply it — LLMs reliably
    hallucinate non-hex strings (`a4b5c6d7-e8f9-g0h1-…`) when asked to
    produce a UUID.
    """
    started = _now()
    print(f"[create_hitl_task] called session_token={session_token!r}", flush=True)
    agent_run_id = str(uuid.uuid4())
    tool_input = {"explore_hints": explore_hints}

    packet = await _recommendation_packet(session_token)
    tier = packet.get("tier")
    if tier in (None, "UNAVAILABLE"):
        print(f"[create_hitl_task] -> no decision available (tier={tier})", flush=True)
        out = {"error": "no_decision_available"}
        _audit("create_hitl_task", "SKIPPED", started, _now(), tool_input, out,
               session_token=session_token)
        return out
    recommendation = tier
    reasoning = packet.get("reasoning") or ""
    evidence = json.dumps(packet.get("evidence"))

    try:
        with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
            with conn.cursor() as cur:
                task_id = cur.callfunc(
                    "AGENT_TOOLS.PKG_AGENT_TOOLS.create_hitl_task",
                    int,
                    [
                        session_token,
                        recommendation,
                        reasoning,
                        explore_hints,
                        evidence,
                        agent_run_id,
                    ],
                )
            conn.commit()
    except oracledb.DatabaseError as exc:
        # NO_DATA_FOUND inside the package: unknown/expired token, or the
        # customer has no open application. Fail closed, and record the attempt.
        print(f"[create_hitl_task] -> rejected: {exc}", flush=True)
        out = {"error": "invalid_or_expired_session"}
        _audit("create_hitl_task", "FAILED", started, _now(), tool_input, out,
               session_token=session_token)
        return out
    out = {
        "task_id": task_id,
        "tier": recommendation,
        "agent_run_id": agent_run_id,
        "state": "OPEN",
        "queue": "APP.HITL_REQUEST",
        "message": (
            f"HITL task {task_id} recorded with tier {recommendation}; "
            f"enqueued on HITL_REQUEST. Answer the customer with the sentence "
            f"for {recommendation}."
        ),
    }
    _audit("create_hitl_task", "SUCCESS", started, _now(), tool_input, out,
           session_token=session_token)
    print(f"[create_hitl_task] -> success task_id={task_id} agent_run_id={agent_run_id}", flush=True)
    return out


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8502"))
    mcp.run(transport="streamable-http", host=host, port=port)
