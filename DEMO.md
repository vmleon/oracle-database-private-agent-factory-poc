# Demo

Prepared per [`CLOUD.md §13`](CLOUD.md#13-prepare-the-demo). One command
before opening a browser, every line green:

```bash
python manage.py info
```

**Customer** `https://<lb_ip>/` · **Reviewer** `https://<lb_ip>/backoffice` · self-signed, accept once.

The reviewer queue is already busy. Three customers are fresh: no application,
no task. Each holds a different conversation, the agent collects the
application, files it, and the row appears in the queue. A turn takes 20–60 s.
The fourth is reviewer-side only: a case already in the queue, researched on
demand.

Say it out loud once: the model writes every sentence, the database computes
every decision, and no number ever reaches the customer.

---

## 1. Diana Marsh → DECLINE

**Customer tab** → log in as **Diana Marsh**. One line per turn, answer what it
asks:

```
Hi, I'm looking to borrow some money for a home renovation.
```

```
Around 12000.
```

```
36 months would suit me.
```

```
The purpose is a home renovation
```

```
Yes, please go ahead and submit it.
```

Reads: cannot go ahead as it stands, a specialist will be in touch, credit
history named. No score, no floor.

**Reviewer tab** → **Diana Marsh**, red, `SCORE_BELOW_FLOOR`. Decline.

---

## 2. Tom Whitfield → REVIEW

**Customer tab** → log out → log in as **Tom Whitfield**:

```
Hello. I'd like a personal loan of 15000 over 48 months to buy a car.
```

```
Yes, submit it.
```

Reads: a reviewer is taking a closer look at the employer. The registry record
behind it is not named.

**Reviewer tab** → **Tom Whitfield**, amber, `EMPLOYER_DORMANT`, the registry
record dormant since 2021. Your call.

---

## 3. Grace Okafor → APPROVE

**Customer tab** → log out → log in as **Grace Okafor**:

```
Hi! What do you need from me to apply for a loan?
```

```
10000.
```

```
24 months.
```

```
To consolidate two credit cards.
```

```
Yes, please submit it.
```

Reads: looks good, with the team for final checks.

**Reviewer tab** → **Grace Okafor**, green, no deny, no warn. Approve.

**Customer tab** → log out → log in as **Grace Okafor** again. Last message on
her thread: the reviewer's outcome.

---

## 4. Sam RoundNumbers → research the case

Already in the queue. No customer tab for this one.

**Reviewer tab** → **Sam RoundNumbers**, amber, `AML_PATTERN`. The evidence
panel says what the policy found. It does not say what the account looks like.

Scroll to **Case research** → **Run research**. 10–30 s.

Four sections come back: the case, what supports approving, what argues
against, and what is not established. The transfers are in it, because a tool
read the full ledger — the customer's agent cannot see that table at all, and a
second database identity is what makes the difference.

Say it out loud: it named no outcome. It is not allowed to. A summary that
states one is refused before it reaches this screen, and the reviewer still
decides.

**Approve** or **Decline** — your call.

---

## If it wanders

- Asks for the amount again after the submit line: paste the amount line
  again, then the submit line. Rehearsed; the second pass files it.
- _"We couldn't get a response"_: send the same line again.
- _"Research could not be completed for this case"_: the agent stated an
  outcome and the screen refused it. Press **Run research** again. Worth
  naming out loud — a refusal is the rule holding, not the demo breaking.

> **Only if the bubble stays pending with no error** — reload the tab, then
> send the line again.

---

## Reference: who lands where

| Customer                     | Tier    | Why                                               |
| ---------------------------- | ------- | ------------------------------------------------- |
| **Diana Marsh**              | DECLINE | credit score below the floor                      |
| **Tom Whitfield**            | REVIEW  | employer dormant in the registry                  |
| **Grace Okafor**             | APPROVE | clean file                                        |
| Alice Salaried, Mia Salaried | APPROVE | clean file                                        |
| Frank MidBand                | REVIEW  | credit score in the caution band                  |
| Kyle DormantEmployer         | REVIEW  | employer dormant in the registry                  |
| David HighDti                | DECLINE | debt-to-income above the cap                      |
| Eva LowScore                 | DECLINE | credit score below the floor                      |
| Jane UnknownEmployer         | DECLINE | employer not in the registry                      |
| Iris UnusableDocs            | DECLINE | document quality unusable                         |
| Nina FailedKyc               | DECLINE | identity checks failed, the check is named to her |
| Marlowe Loanshark            | DECLINE | on the sanctions list, nothing is named to him    |
| Omar PendingKyc              | REVIEW  | identity checks pending, the check is named       |
| Paula Statesman              | REVIEW  | politically exposed person, nothing is named      |
| Sam RoundNumbers             | REVIEW  | six large round transfers out in thirty days      |

The first three are the live demo and Sam RoundNumbers is the fourth: his
transfers are what the research agent reads, and his case carries no research
until you run it. The rest are the backfill: one open case each in the queue,
and Alice and David also in the decision history, approved and declined.
