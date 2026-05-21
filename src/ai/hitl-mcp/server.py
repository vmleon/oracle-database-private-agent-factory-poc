"""HITL MCP server — exposes the in-DB create_hitl_task PL/SQL function as
an MCP tool so PAF's CHAT_AGENT can write its recommendation packet.

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

Wired into CHAT_AGENT only. RESEARCH_AGENT is read-only by design (no
side-effect tools).
"""

from __future__ import annotations

import os
from typing import Literal

import oracledb
from fastmcp import FastMCP

mcp = FastMCP("hitl-mcp")


DB_DSN = (
    f"{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_SERVICE']}"
)
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


Recommendation = Literal["APPROVE", "REVIEW", "DECLINE"]


@mcp.tool()
def create_hitl_task(
    application_id: int,
    recommendation: Recommendation,
    reasoning: str,
    agent_run_id: str,
    explore_hints: str | None = None,
    evidence: str | None = None,
) -> dict:
    """Write the CHAT_AGENT recommendation packet to APP.hitl_task and
    enqueue HITL_REQUEST in the same transaction. Returns the new task_id.

    This is CHAT_AGENT's ONLY side-effect tool: every successful run ends
    with exactly one call. The human reviewer (not the agent) closes the
    task; that close is what writes the Blockchain `decision` row.

    Argument extraction guidance for the LLM:
      - application_id — integer loan application id from the conversation
                         context (the customer-safe REPORTING views surface
                         this when the customer chats).
      - recommendation — one of "APPROVE" / "REVIEW" / "DECLINE" based on
                         the signals gathered (OPA outputs, OCR quality,
                         employer verification, etc.). REVIEW for any
                         non-strong-signal case.
      - reasoning      — short prose explaining the recommendation. Cite
                         the tool outputs (e.g. "OPA eligibility allow=true,
                         OCR PAYSLIP MARGINAL on first upload, employer
                         verified active").
      - agent_run_id   — opaque correlation id for this agent run. The
                         caller (PAF) should pass a unique value per
                         conversation turn so the audit trail joins back
                         to decision_audit rows.
      - explore_hints  — REVIEW-only: JSON string array of follow-up
                         questions/checks the reviewer should examine.
                         Pass null for APPROVE / DECLINE.
      - evidence       — JSON string of structured evidence captured
                         during the run (tool outputs, doc references).
                         Pass null if you have nothing to attach.
    """
    with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
        with conn.cursor() as cur:
            task_id = cur.callfunc(
                "AGENT_TOOLS.PKG_AGENT_TOOLS.create_hitl_task",
                int,
                [
                    application_id,
                    recommendation,
                    reasoning,
                    explore_hints,
                    evidence,
                    agent_run_id,
                ],
            )
        conn.commit()
    return {
        "task_id": task_id,
        "state": "OPEN",
        "queue": "APP.HITL_REQUEST",
        "message": (
            f"HITL task {task_id} created for application {application_id} "
            f"with recommendation {recommendation}; enqueued on HITL_REQUEST."
        ),
    }


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8502"))
    mcp.run(transport="streamable-http", host=host, port=port)
