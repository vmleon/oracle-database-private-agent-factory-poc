# Demo — Governed Loan Decisioning Walk-through

A schematic, copy-paste walk-through of the end-to-end PoC: a **customer chats**
to apply, the **agent produces a recommendation**, a **human reviewer decides**,
and the decision is written as an **immutable, tamper-evident row** in an Oracle
Blockchain Table.

The single source of truth is the **human's** call — the AI only recommends.

---

## 0. Before you start

Stack must be running (`python manage.py local up`; `podman ps` shows
`application-backend`, `customer-ui`, `backoffice-ui`, `paf-proxy`, `paf-*`,
`paf-oracle-free-26ai`).

URLs (same host, path-routed for now):

- **Chat UI (customer):** http://localhost:5173/
- **Backoffice (reviewer):** http://localhost:5173/backoffice

Open a DB shell for the verify steps (run any query after the `ALTER SESSION`):

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
ALTER SESSION SET CONTAINER=FREEPDB1;
SELECT 'db ok' FROM dual;
SQL
```

Good to know:

- A full agent turn takes **~3–4 minutes** (4-agent path). Be patient.
- If a turn returns _"Sorry — we couldn't process your application right now"_
  in ~20s, that's the known streaming `session_token` bug — just send the
  message again (the backend also auto-retries).
- `decision_audit` (the per-tool agent trace) is populated live: the
  token-bearing CHAT_WORKFLOW tools (`get_context`, `upsert_application`) POST to
  the Application Service after they run; it resolves the application from the
  session token (never a caller-supplied id) and writes one row keyed by
  `application_id`. It surfaces in the backoffice decision-history detail under
  "Tools called". Retries log repeat rows (each attempt is real audit signal).

---

## 1. Customer applies (Chat UI)

1. Open http://localhost:5173/ .
2. Pick a customer from the login list — start with **Frank MidBand** (see the
   scenario menu in §4 for the others).
3. In the chat box, send:

   ```
   I'd like to proceed with my personal loan application — please review my eligibility.
   ```

4. Answer any follow-up questions naturally. Wait **~3–4 min** for the turn that
   evaluates the application; it ends with an _"under review"_-style reply. Behind
   the scenes the agent pulls your context (income, bureau, debt), runs policy
   (eligibility / AML / KYC / fair-lending), verifies your employer, and writes a
   **recommendation** to the review queue.
5. (Optional) confirm the task was created:

   ```bash
   podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
   ALTER SESSION SET CONTAINER=FREEPDB1;
   SET LINESIZE 140
   SELECT task_id, application_id, agent_recommendation, state
     FROM APP.hitl_task ORDER BY task_id DESC FETCH FIRST 3 ROWS ONLY;
   SQL
   ```

6. (Optional) Log out from the chat to switch hats.

---

## 2. Reviewer decides (Backoffice)

1. Open http://localhost:5173/backoffice .
2. Find the request in the queue. The **Agent Recommendation** tag is
   colour-coded for triage — **green APPROVE / amber REVIEW / red DECLINE**.
   Click the row.
3. Review the **evidence panel**. Highlights to call out during the demo:
   - **Credit score / DTI / PTI** stat tiles — colour-coded against the policy
     caps (score 600/670, DTI 0.45, PTI 0.25).
   - **KYC / Employer / Income** status badges.
   - The agent's **reasoning** and **recommendation** at the top.
4. Make the call: click **Approve** (green) or **Reject** (red), type a reviewer
   **note** (required — Submit stays disabled until you do), then click
   **Submit decision**. The task drops off the queue.

---

## 3. Verify the audit trail (the point of the PoC)

The human decision is now an immutable Blockchain Table row.

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
ALTER SESSION SET CONTAINER=FREEPDB1;
SET LINESIZE 180 PAGESIZE 40
COLUMN human_user FORMAT A22
COLUMN human_note FORMAT A35

-- the task is closed with the human's call
SELECT task_id, state, human_outcome, human_user, human_note
  FROM APP.hitl_task WHERE state='CLOSED'
 ORDER BY task_id DESC FETCH FIRST 3 ROWS ONLY;

-- one immutable decision row per closed case
SELECT decision_id, application_id, agent_recommendation,
       human_outcome, human_user,
       TO_CHAR(decided_at,'YYYY-MM-DD HH24:MI:SS') AS decided_at
  FROM APP.decision ORDER BY decision_id DESC FETCH FIRST 3 ROWS ONLY;
SQL
```

Prove it's tamper-evident (optional — the big "wow"):

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
ALTER SESSION SET CONTAINER=FREEPDB1;
SET SERVEROUTPUT ON

-- both are rejected: ORA-05715 operation not allowed on the blockchain table
UPDATE APP.decision SET human_outcome='REJECT'
 WHERE decision_id = (SELECT MAX(decision_id) FROM APP.decision);
DELETE FROM APP.decision
 WHERE decision_id = (SELECT MAX(decision_id) FROM APP.decision);

-- cryptographic chain verification of every row
DECLARE v NUMBER; BEGIN
  DBMS_BLOCKCHAIN_TABLE.VERIFY_ROWS(schema_name => 'APP', table_name => 'DECISION',
    number_of_rows_verified => v, verify_signature => FALSE);
  DBMS_OUTPUT.PUT_LINE('rows cryptographically verified: ' || v);
END;
/
SQL
```

You should see two `ORA-05715` rejections (the record can't be altered or
deleted) followed by `rows cryptographically verified: N`.

---

## 4. Scenario menu

Repeat §1–§3 with any of these. Each lands in a different tier for a different
reason, so you can show the full decisioning surface. Numbers come from seed
changesets `002` + `010` and the OPA config.

| Customer (login)         | Expected recommendation | Why it lands there                                   |
| ------------------------ | ----------------------- | ---------------------------------------------------- |
| **Frank MidBand**        | **REVIEW**              | credit score 660, inside the 600–670 caution band    |
| **David HighDti**        | **DECLINE**             | DTI ≈ 0.48 > 0.45 hard cap (computed from his debts) |
| **Jane UnknownEmployer** | **REVIEW**              | employer not found in the Company Registry           |
| **Alice Salaried**       | **APPROVE**             | clean profile (score 742, DTI 0.10, employer active) |

Alternatives for variety: **Eva LowScore** → DECLINE (score below floor),
**Iris UnusableDocs** → DECLINE (document quality), **Kyle DormantEmployer** →
REVIEW (employer dormant).

### Optional: Alice "from-scratch intake" variant

By default every demo customer already has a submitted application, so the agent
evaluates an existing one. To instead show the **intake-from-nothing** path (the
agent collects the loan amount/term/purpose before evaluating), clear Alice's
seeded application first:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s -L / as sysdba <<'SQL'
ALTER SESSION SET CONTAINER=FREEPDB1;
DELETE FROM APP.loan_application_document WHERE application_id IN
  (SELECT la.application_id FROM APP.loan_application la
     JOIN APP.customer c ON c.customer_id = la.customer_id
    WHERE c.full_name = 'Alice Salaried');
DELETE FROM APP.loan_application WHERE customer_id =
  (SELECT customer_id FROM APP.customer WHERE full_name = 'Alice Salaried');
COMMIT;
SQL
```

Then log in as **Alice Salaried** and open with:

```
I'd like a $10,000 personal loan over 24 months for home renovation.
```

The agent records the new application, then evaluates it → **APPROVE**.

---

## Notes / current limits

- **Scope of the demo:** the full loop now closes — customer chat → agent
  recommendation → human review → immutable decision. (The Case Research Agent /
  `RESEARCH_WORKFLOW` is not built yet.)
- **Not wired into the agent flow:** RAG policy citations (`search_policy`) and
  similar-case lookup (`search_similar_cases`) — don't expect them in replies.
- **Frontends:** customer chat and backoffice currently share one site under
  path prefixes; splitting them into separate apps is a planned follow-up (see
  `BACKLOG.md` → Platform follow-ups).
