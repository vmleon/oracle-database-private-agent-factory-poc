# Backlog

The prioritised backlog for the PoC: near-term backoffice work, broader-plan
features, and platform hardening.

## 1. Proactive product recommendation as a second workflow

Clone the `CHAT_WORKFLOW` pattern into a second PAF Agent Builder flow over the same `REPORTING.*` view set, with a different agent prompt + tool surface + signal weights, writing to a recommendation queue rather than `hitl_task`. Reuses the existing backbone (HITL, audit, OPA grounding, RAG citations, configurable signal weights) for a recommendation surface alongside the decisioning surface.

## 2. Customer 360 curated view

Finish `REPORTING.cust_360` — one well-named view joining demographics, balances, products held, recent transactions, bureau snapshot, employer-verification. Consumed by both the existing `CHAT_WORKFLOW` and the future product-recommendation workflow, and the feature source for the XGBoost training in §3.

## 3. XGBoost credit-scoring tool

A separate Python component that trains an **XGBoost** model in **OML4Py** (Oracle Machine Learning for Python, runs in-database) on the existing synthetic data, registers it in the OML model registry, and exposes it as an additional tool the agent calls during evidence gathering:

`predict_credit_score(customer_id)` → `{score, top_features}`

The agent appends this to the evidence packet alongside OPA outputs, OCR quality, and employer verification. The backoffice reviewer then sees in the recommendation panel something like: _"Customer 12345 has a credit-risk score of 0.42, driven by (1) low transaction velocity in the last 90 days, (2) recent salary increase, (3) no late payments in the last 12 months."_

Shape of the new component:

```
src/ml/credit-score/
├── train.py        # OML4Py — reads REPORTING.cust_360, fits XGBoost, registers model
├── deploy.py       # creates AGENT_TOOLS.predict_credit_score PL/SQL wrapper
├── Containerfile   # one-shot container; run via manage.py
└── README.md
```

Wired into the PoC via:

- New Liquibase changeset for the `AGENT_TOOLS.predict_credit_score` PL/SQL function and any model-registry references.
- New `manage.py ml train` / `manage.py ml deploy` commands.
- The `Recommendation` agent's prompt (and the `Eligibility` agent's evidence) updated to ingest the new score field; a weight added to `system_config` so it contributes to the tier composition.
- Exposed to PAF following the existing `create_hitl_task` pattern — **Select AI Tool** on cloud / ADB, thin **MCP wrapper** on local / Free 26ai. Same PL/SQL function on both sides; only the transport differs.

End-to-end coverage: **training** (OML4Py + XGBoost) → **deployment** (model registry + PL/SQL wrapper) → **inference** (in-DB scoring via `PREDICTION()`) → **explainability** (top features surfaced in evidence). The feedback loop already exists — the `decision` Blockchain row captures human outcomes, ready for future retraining cycles.

## 4. TOON feasibility spike

TOON ("Token-Oriented Object Notation") is a compact JSON-alternative serialization that uses 30–50% fewer tokens for structured payloads sent to an LLM. Worth applying once the §3 evidence (score + top features) starts landing in the prompt alongside RAG chunks and OPA outputs.

Open questions the spike must answer:

- Can a PAF **Function node** import a `toon` Python library and transform tool output before it reaches the next node?
- Can a **Prompt template** invoke a custom serializer, or is it plain string interpolation?
- What packages ship with the PAF container runtime, and can we add more?

Outcome: TOON encoding happens either inside the PAF flow (clean, one place to look) or in the prompt-builder code outside PAF (still works, less tidy). Document the recipe (or the constraint).

---

## Execution order

1. Finish the current loan-decisioning end-to-end (OCR real pipeline, Application Service, Angular UIs, Blockchain write at HITL close).
2. §2 — `REPORTING.cust_360`. Feature source for step 3.
3. §3 — XGBoost credit-scoring tool.
4. §1 — product-recommendation workflow. Consumes the credit-score tool from step 3 as one of its signals.
5. §4 — TOON spike. Independent of steps 1–4, can happen in parallel.

---

## Platform follow-ups (hardening)

Operational/structural next steps surfaced while building the backoffice review
loop.

### A. Investigate the empty `decision_audit`

`APP.decision_audit` is empty — the per-tool agent trace (every `CHAT_WORKFLOW`
tool call with step / timing / status; test-bench assertion (c)) is never
written, even though the tool _outputs_ do land in `hitl_task.agent_evidence`.
Find which component is responsible (MCP tool wrappers, the PAF flow, or the
backend) and why it never fires, then decide whether to implement the per-tool
write. Investigation first; no architectural change. (Note: the human decision
audit — the immutable `decision` blockchain row with outcome, reviewer, and
note — already works and is tamper-verified.)
