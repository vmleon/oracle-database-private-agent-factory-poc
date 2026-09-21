# Demo

Prepared per [`CLOUD.md §12`](CLOUD.md#12-prepare-the-demo). One command
before opening a browser, every line green:

```bash
python manage.py info
```

**Customer** `https://<lb_ip>/` · **Reviewer** `https://<lb_ip>/backoffice` · self-signed, accept once.

The reviewer queue is already busy. Three customers are fresh: no application,
no task. Each holds a different conversation, the agent collects the
application, files it, and the row appears in the queue. A turn takes 20–60 s.

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

## If it wanders

- Asks for the amount again after the submit line: paste the amount line
  again, then the submit line. Rehearsed; the second pass files it.
- _"We couldn't get a response"_: send the same line again.

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

The first three are the live demo. The rest are the backfill: one open case
each in the queue, and Alice and David also in the decision history, approved
and declined.
