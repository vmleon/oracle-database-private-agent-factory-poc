# Demo Runbook — Governed Loan Decisioning

Step-by-step runbook for the end-to-end PoC: a **customer chats** to apply, the
**agent produces a recommendation**, a **human reviewer decides**, and the
decision is written as an **immutable, tamper-evident row** in an Oracle
Blockchain Table. The human makes the call — the AI only recommends.

Run it in order: **§1 smoke test** (automated sanity check, three requests),
**§2 view them in the backoffice**, **§3 live customer chat** (three more
requests), **§4 reviewer decides**, **§5 verify the immutable audit trail**.

---

## 0. Before you start

The stack runs on OCI ([`CLOUD.md`](CLOUD.md)). Print its addresses:

```bash
python manage.py info
```

URLs (same load balancer, path-routed; the certificate is self-signed, so the
browser warns once):

- **Chat UI (customer):** `https://<lb_ip>/`
- **Backoffice (reviewer):** `https://<lb_ip>/backoffice`

The verify steps run SQL through the bastion, one statement per command:

```bash
python manage.py cloud sql "SELECT 'db ok' FROM dual"
```

The customer chat reaches the flow through the application backend, which needs
CHAT_FLOW's integration key. It is handed over once per deployment, after the
flow is published:

```bash
python manage.py paf push-key
```

Good to know:

- A full agent turn takes **~20–60 seconds**. Be patient.
- **The agent writes each customer reply itself**, so the wording differs run to
  run. What is fixed is the policy behind it: it may name the factor a decision
  turned on — affordability, credit history, the employer's registration — and
  never a number, score, threshold or internal code. Worth saying out loud during
  the demo: the decision is computed in the database, the sentence is the model's.
- `decision_audit` (the per-tool trace) is populated live and surfaces in the
  backoffice decision detail under **Tools called**.

---

## 1. Sanity check — run the smoke test

Drives three requests end to end — one per recommendation tier — and asserts
each lands where it should. This is your "the system works" gate before the
live demo.

1. Run:

   ```bash
   python manage.py cloud test -k "alice or frank or david"
   ```

2. Wait **~1–2 min**. Expect all three to pass:

   | Customer           | Recommendation |
   | ------------------ | -------------- |
   | **Alice Salaried** | **APPROVE**    |
   | **Frank MidBand**  | **REVIEW**     |
   | **David HighDti**  | **DECLINE**    |

   A green `3 passed` from pytest means the agent path, OPA policy, MCP tools,
   and the HITL write are all healthy. The three requests stay in the backoffice
   queue.

3. (Optional) confirm the three rows:

   ```bash
   python manage.py cloud sql "SELECT task_id, application_id, agent_recommendation, state FROM BANK_CORE.hitl_task ORDER BY task_id DESC FETCH FIRST 3 ROWS ONLY"
   ```

---

## 2. See the smoke results in the backoffice

1. Open `https://<lb_ip>/backoffice`.
2. You see the three smoke requests in the queue. The **Agent Recommendation**
   tag is colour-coded — **green APPROVE / amber REVIEW / red DECLINE** — so
   Alice, Frank and David read green / amber / red at a glance.
3. Click any row to open the **evidence panel** — three columns: **Employer**
   (registry status), **Required documents** (per amount band), and **Reasons**
   (the agent's reason codes); the agent's **reasoning** and **recommendation**
   show at the top, and **Tools called** lists each tool call with its parsed
   input/output.

Leave these three for now — you'll process the live ones in §4.

---

## 3. Live demo — customer chat (three more requests)

Now generate three fresh requests by hand, one per tier, to show the live
customer experience. Repeat the same five clicks for each customer below.

The message to send is always:

```
Please review my loan application and submit it for processing.
```

### 3a. Mia Salaried → APPROVE

1. Open `https://<lb_ip>/`.
2. Pick **Mia Salaried** from the login list.
3. Paste the message above into the chat box and send.
4. Wait **~20–60 s**. She gets one warm sentence in the agent's own words — along
   the lines of _"Your application looks good and is now with the team for final
   checks."_ Behind the scenes the workflow pulls her context, computes policy
   (eligibility / AML / KYC / fair-lending) deterministically, verifies her
   employer, and writes an **APPROVE** recommendation to the queue.
5. Log out.

### 3b. Kyle DormantEmployer → REVIEW

1. Open `https://<lb_ip>/`.
2. Pick **Kyle DormantEmployer**.
3. Send the same message; wait **~20–60 s**.
4. His employer is **dormant** in the Company Registry → the agent writes a
   **REVIEW** recommendation. He reads that a reviewer is taking a closer look at
   his employer's trading status: the factor is named, the registry record behind
   it is not.
5. Log out.

### 3c. Eva LowScore → DECLINE

1. Open `https://<lb_ip>/`.
2. Pick **Eva LowScore**.
3. Send the same message; wait **~20–60 s**.
4. Her credit score is **below the floor** → the agent writes a **DECLINE**
   recommendation. She reads that it cannot go ahead as it stands and a specialist
   will be in touch, with her credit history named as the factor — no score, no
   floor, no policy threshold reaches her. The reviewer sees all of it.
5. Log out.

(Optional) confirm the three new tasks:

```bash
python manage.py cloud sql "SELECT t.task_id, c.full_name, t.agent_recommendation, t.state FROM BANK_CORE.hitl_task t JOIN BANK_CORE.loan_application la ON la.application_id = t.application_id JOIN BANK_CORE.customer c ON c.customer_id = la.customer_id WHERE c.full_name IN ('Mia Salaried','Kyle DormantEmployer','Eva LowScore') ORDER BY t.task_id DESC"
```

---

## 4. Live demo — reviewer decides (backoffice)

Process the three requests you just created — one Approve, one Review-then-Decline,
one Decline. For each: open the queue, click the row, read the evidence, pick the
button, type a mandatory comment, submit.

1. Open `https://<lb_ip>/backoffice`.

### 4a. Mia (APPROVE) → **Approve**

2. Click **Mia Salaried**'s row (green tag).
3. The **Approve** button is preselected to match the agent. Type a **Comment**
   (mandatory — Submit stays disabled until you do), e.g. _"Clean profile, agree
   with recommendation."_
4. Press **Enter** or click **Submit decision**. The task drops off the queue.

### 4b. Kyle (REVIEW) → **Decline**

5. Click **Kyle DormantEmployer**'s row (amber tag). This is the human-judgement
   case: the agent flagged it for **REVIEW**, and you decide.
6. Click **Decline** (overriding the amber recommendation), type a **Comment**,
   e.g. _"Employer dormant in registry; insufficient assurance — declining."_
7. **Submit decision**. The task drops off the queue.

### 4c. Eva (DECLINE) → **Decline**

8. Click **Eva LowScore**'s row (red tag).
9. **Decline** is preselected. Type a **Comment**, e.g. _"Score below floor,
   agree with recommendation."_
10. **Submit decision**. The task drops off the queue.

---

## 5. Verify the immutable audit trail (the point of the PoC)

Each human decision is now an immutable Blockchain Table row.

The three tasks closed with the human's call:

```bash
python manage.py cloud sql "SELECT task_id, state, human_outcome, human_user, human_note FROM BANK_CORE.hitl_task WHERE state='CLOSED' ORDER BY task_id DESC FETCH FIRST 3 ROWS ONLY"
```

One immutable decision row per closed case:

```bash
python manage.py cloud sql "SELECT decision_id, application_id, agent_recommendation, human_outcome, human_user, TO_CHAR(decided_at,'YYYY-MM-DD HH24:MI:SS') AS decided_at FROM BANK_CORE.decision ORDER BY decision_id DESC FETCH FIRST 3 ROWS ONLY"
```

Prove it's tamper-evident (the big "wow"). An update is rejected:

```bash
python manage.py cloud sql "UPDATE BANK_CORE.decision SET human_outcome='DECLINE' WHERE decision_id = (SELECT MAX(decision_id) FROM BANK_CORE.decision)"
```

So is a delete:

```bash
python manage.py cloud sql "DELETE FROM BANK_CORE.decision WHERE decision_id = (SELECT MAX(decision_id) FROM BANK_CORE.decision)"
```

Both print `ORA-05715: operation not allowed on the blockchain or immutable
table`. Then verify the cryptographic chain of every row:

```bash
python manage.py cloud sql "DECLARE v NUMBER; BEGIN DBMS_BLOCKCHAIN_TABLE.VERIFY_ROWS(schema_name => 'BANK_CORE', table_name => 'DECISION', number_of_rows_verified => v, verify_signature => FALSE); DBMS_OUTPUT.PUT_LINE('rows cryptographically verified: ' || v); END;"
```

Expect `rows cryptographically verified: N`.

---

## Reference

### Scenario menu

Each customer lands in a tier for a different reason, so you can show the full
decisioning surface. Smoke uses Alice / Frank / David; the live demo uses Mia /
Kyle / Eva. Numbers come from seed changesets `002`, `010`, `016` and the OPA
config (DECLINE if score < 600 / DTI > 0.45; REVIEW if score 600–669; APPROVE
if score ≥ 670 and clean).

| Customer (login)         | Recommendation | Why it lands there                                  |
| ------------------------ | -------------- | --------------------------------------------------- |
| **Alice Salaried**       | **APPROVE**    | clean profile (score 742, DTI low, employer active) |
| **Mia Salaried**         | **APPROVE**    | clean profile (score 742, DTI low, employer active) |
| **Frank MidBand**        | **REVIEW**     | credit score 660, inside the 600–670 caution band   |
| **Kyle DormantEmployer** | **REVIEW**     | employer dormant in the Company Registry            |
| **David HighDti**        | **DECLINE**    | DTI above the 0.45 hard cap                         |
| **Eva LowScore**         | **DECLINE**    | credit score 540, below the floor                   |
| **Jane UnknownEmployer** | **DECLINE**    | employer not found in the Company Registry          |
| **Iris UnusableDocs**    | **DECLINE**    | document quality unusable                           |

### Reset between demos

A run leaves four things behind: one `hitl_task` row per request (the reviewer
queue), the chat transcripts both UIs render, a login session per customer you
signed in as, and the per-tool trace rows behind **Tools called**. Clearing them
hands the next demo an empty queue and empty chats:

```bash
python manage.py cloud reset
```

```
  reviewer queue   42 removed
  chat messages    4 removed
  login sessions   8 removed
  tool traces      395 removed
```

The seeded customers and their applications are untouched — §1 runs again
straight away, and a customer you already processed can be demoed again because
a fresh chat writes a new task.

**`BANK_CORE.decision` cannot be cleared, and that is the point.** It is declared:

```sql
NO DROP UNTIL 2555 DAYS IDLE
NO DELETE LOCKED
```

Its rows outlive every reset short of destroying the database — exactly the
property §5 demonstrates. Leave it alone: §5 reads the newest rows, and
`VERIFY_ROWS` walks the whole chain, so a count that grows across demos reads as
history rather than clutter. An empty `decision` table means `cloud down` then
`cloud up`, and nothing less.

One thing the reset does not undo: the from-scratch intake variant below deletes
a customer's seeded application and lets the agent rebuild it from the
conversation, so its amount, term and purpose are whatever that chat supplied.
Only a rebuild restores the seeded values.

### Optional: "from-scratch intake" variant

By default every demo customer already has a submitted application, so the agent
evaluates an existing one. To instead show the **intake-from-nothing** path (the
agent collects amount/term/purpose before evaluating), clear a clean customer's
seeded application first — here, Mia:

```bash
python manage.py cloud sql "DELETE FROM BANK_CORE.loan_application_document WHERE application_id IN (SELECT la.application_id FROM BANK_CORE.loan_application la JOIN BANK_CORE.customer c ON c.customer_id = la.customer_id WHERE c.full_name = 'Mia Salaried')"
```

```bash
python manage.py cloud sql "DELETE FROM BANK_CORE.loan_application WHERE customer_id = (SELECT customer_id FROM BANK_CORE.customer WHERE full_name = 'Mia Salaried')"
```

Then log in as **Mia Salaried** and open with:

```
I'd like a $10,000 personal loan over 24 months for home renovation.
```

The agent records the new application, then evaluates it → **APPROVE**.

### Notes / current limits

- **Scope:** the full loop closes — customer chat → agent recommendation → human
  review → immutable decision. (The Case Research Agent / `RESEARCH_WORKFLOW` is
  not built.)
- **Not wired into the agent flow:** RAG policy citations (`search_policy`) and
  similar-case lookup (`search_similar_cases`) — don't expect them in replies.
- **Frontends:** customer chat and backoffice are separate SPAs (`customer-ui`,
  `backoffice-ui`), served by nginx behind the load balancer — `/backoffice` to
  the reviewer app, everything else to the customer app.
