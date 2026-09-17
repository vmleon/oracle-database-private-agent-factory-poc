# Demo runbook

One end-to-end conversation, cold to decided, shown twice: once approved, once
refused. Read top to bottom on the day; the pre-flight is the evening before.

## Pre-flight, the evening before

```bash
source venv/bin/activate
python manage.py info                 # every tier ready, both URLs printed
```

Hold the demo conversation once, exactly as scripted below, in the browser.
Then run the scripted scenario, which wipes every chat thread and files one
fresh task on Alice:

```bash
python manage.py cloud test -k alice  # the scripted APPROVE turn, green
```

Decide that task from the backoffice UI, so the queue is empty when the
audience sees it and Alice's thread holds only the outcome. A closed task also
unfreezes her figures.

The bench and the scripted scenario move `Alice Salaried`'s amount and never
restore it, so the row is wherever the last run left it. Read it: the agent
reads these figures back to her, so make sure they are ones you are happy to
say out loud:

```bash
python manage.py cloud sql "SELECT la.amount_requested, la.term_months, la.purpose, la.status FROM BANK_CORE.loan_application la JOIN BANK_CORE.customer c ON c.customer_id = la.customer_id WHERE c.full_name = 'Alice Salaried'"
```

## Personas

Pick from the customer UI's login dropdown. Three carry the story; the rest are
for the bench.

| Persona | Shows | Why this one |
| --- | --- | --- |
| `Alice Salaried` | `APPROVE` | The clean path: intake, recommendation, reviewer approves, customer reads the outcome |
| `Nina FailedKyc` | `DECLINE` | The refusal that may explain itself: the reply names the identity check |
| `Marlowe Loanshark` | `DECLINE` | The refusal that must not: a sanctions match, and the customer reads a generic factor |

Leave `Frank MidBand` alone: the `REVIEW` band invites the audience to ask what
the threshold is, and walking the amount up and down is the one leak the bench
still records.

## The script

Alice's application is seeded complete, so the agent reads it back rather than
collecting it. Two shapes fail on every bench run and both are avoidable: three
fields in one sentence, and the question "how long does this take?". If the
demo answers a question from the agent, answer one field at a time.

**Alice, customer tab.**

1. `Hi, I'd like to go ahead with my loan application.` The reply reads back
   her amount, term and purpose. Those are her own figures, not the policy's.
2. `Yes, please submit it.` The reply says the application is with the team and
   names no figure. This is the moment to say that the tier, the ratios and the
   evidence packet were computed server-side before any model wrote a word, and
   that the sentence only reached the screen because a `hitl_task` row exists
   behind it.

**Backoffice tab.**

3. **Claim next.** Walk the packet: recommendation, reasoning, evidence, the
   per-tool trace with the ratios and reason codes the customer never saw.
4. Approve with a note. This writes the blockchain row and the outcome message.

**Alice, customer tab.**

5. Reload the page. The reviewer's outcome is the last message on the thread.

**Nina, then Marlowe.**

6. Log out, log in as `Nina FailedKyc`, send `Please submit my application for
   review.` The reply refuses and names the identity check.
7. Same turn as `Marlowe Loanshark`. The reply refuses and names nothing. Open
   the task in the backoffice to show the reviewer sees `SANCTIONS_MATCH` and
   the customer does not: naming it would be tipping off.

## If a turn hangs

About one turn in fifty produces no reply. The pending bubble lives in the
browser only, so:

1. Reload the customer tab. The bubble is gone and the thread is intact.
2. Send the same message again.

The backend gives up on the hung call after four minutes and logs the cause; a
retry does not wait for it.

> **Only if the second attempt hangs too** — switch personas. The chat executor
> has two threads and a hung turn holds one until the timeout.
