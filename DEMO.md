# Demo

Prepared per [`CLOUD.md §12`](CLOUD.md#12-prepare-the-demo). Addresses:

```bash
python manage.py info
```

**Customer** `https://<lb_ip>/` · **Reviewer** `https://<lb_ip>/backoffice` · self-signed, accept once.

The queue is already busy: one case per scenario persona, two decisions in the
history. Three customers are fresh, no application, no task. A turn takes
20–60 s. Read the reply out loud: the model wrote the sentence, the database
computed the decision, and no number ever reaches the customer.

| | Customer | Lands as | Why |
| --- | --- | --- | --- |
| 1 | **Diana Marsh** | DECLINE | credit score below the floor |
| 2 | **Tom Whitfield** | REVIEW | employer dormant in the registry, you decide |
| 3 | **Grace Okafor** | APPROVE | clean file |

Same three lines for each, one per turn:

```
Hi, I'd like to apply for a personal loan.
```

```
12000 over 36 months, for a home renovation.
```

```
Yes, please submit it.
```

If the third line is answered with a question about the amount, paste the
second line again, then the third. Rehearsed: the second pass files it.

---

## 1. Diana Marsh → DECLINE

**Customer tab** → log in as **Diana Marsh** → the three lines.
Reads: cannot go ahead as it stands, a specialist will be in touch, credit
history named. No score, no floor.

**Reviewer tab** → new row **Diana Marsh**, red → open.
Recommendation, reasoning, `SCORE_BELOW_FLOOR`, employer record, required
documents, **Tools called**.
**Decline** (preselected) → comment → **Submit decision**.

---

## 2. Tom Whitfield → REVIEW, your call

**Customer tab** → log out → log in as **Tom Whitfield** → the three lines.
Reads: a reviewer is taking a closer look, employer named. The registry record
behind it is not.

**Reviewer tab** → new row **Tom Whitfield**, amber → open.
`EMPLOYER_DORMANT`, the registry record: dormant, last filed 2021.
**Approve** or **Decline** → comment → **Submit decision**. The human decides.

---

## 3. Grace Okafor → APPROVE

**Customer tab** → log out → log in as **Grace Okafor** → the three lines.
Reads: looks good, with the team for final checks.

**Reviewer tab** → new row **Grace Okafor**, green → open.
No deny, no warn, employer active. **Approve** (preselected) → comment →
**Submit decision**.

**Customer tab** → log out → log in as **Grace Okafor** again.
Last message on her thread: the reviewer's outcome. Fixed text, same
disclosure policy.

---

## Short on time: the backfill

**Reviewer tab**, queue as it stands. Rows worth opening:

- **Marlowe Loanshark**, red: `SANCTIONS_MATCH` and the matched entry. The
  customer was told nothing. Tipping off is an offence.
- **Nina FailedKyc**, red: `KYC_FAILED`. The customer was told, because it is
  the one thing they can act on.
- **Sam RoundNumbers**, amber: `AML_PATTERN`, six large round transfers out in
  thirty days.
- **Kyle DormantEmployer**, amber. **Eva LowScore**, red. **Mia Salaried**,
  green.

**Decisions**: Alice Salaried approved, David HighDti declined, each an
immutable row.

---

## Optional: the blockchain

An update is rejected:

```bash
python manage.py cloud sql "UPDATE BANK_CORE.decision SET human_outcome='DECLINE' WHERE decision_id = (SELECT MAX(decision_id) FROM BANK_CORE.decision)"
```

So is a delete:

```bash
python manage.py cloud sql "DELETE FROM BANK_CORE.decision WHERE decision_id = (SELECT MAX(decision_id) FROM BANK_CORE.decision)"
```

Both: `ORA-05715: operation not allowed on the blockchain or immutable table`.
Then the chain:

```bash
python manage.py cloud sql "DECLARE v NUMBER; BEGIN DBMS_BLOCKCHAIN_TABLE.VERIFY_ROWS(schema_name => 'BANK_CORE', table_name => 'DECISION', number_of_rows_verified => v, verify_signature => FALSE); DBMS_OUTPUT.PUT_LINE('rows cryptographically verified: ' || v); END;"
```

---

## If a turn fails

_"We couldn't get a response"_ → send the same line again. Thread intact.

> **Only if the bubble stays pending with no error** — reload the tab, then
> send the line again.

Not built, so not in the demo: the research agent, policy citations,
similar-case lookup.
