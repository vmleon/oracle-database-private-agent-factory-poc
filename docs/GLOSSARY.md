# Banking & Compliance Glossary

A non-technical glossary of the banking, credit, and compliance terms used across this PoC's docs. Each entry is one short definition plus one small example.

---

## Loan basics

- **Loan origination** — the end-to-end process from a customer applying for a loan to a final decision. _Example: you fill out an application, upload your ID and payslip, the bank checks them, and either approves or declines you — all of that is origination._
- **Principal** — the amount of money you actually borrow, before interest or fees. _Example: ask for a $10,000 loan, and $10,000 is the principal._
- **Tenor** (or **term**) — how long you have to pay the loan back. _Example: 36 months means three years of monthly repayments._
- **Rate card** — the bank's price list, defining the rate (or fee) charged for each combination of product and risk bucket. _Example: same product, same amount — a low-risk applicant might pay 4.5%, a higher-risk one 9%._
- **Risk band** (`LOW` / `MID` / `HIGH`) — a coarse bucketing of how risky a borrower looks; drives which rate from the rate card applies. _Example: clean profile + high credit score → LOW band → cheapest rate._

## Affordability — can the customer actually repay?

- **`min_age`** — youngest age at which the bank will lend. _Example: `min_age = 18` rejects a 17-year-old applicant outright._
- **DTI (Debt-to-Income)** — total monthly debt payments divided by monthly income, as a percentage. _Example: $1,200/month in debt payments on $3,000/month income = 40% DTI._
- **`dti_hard_cap`** — the absolute DTI ceiling; cross it and you're declined regardless of how clean the rest of your profile is. _Example: `dti_hard_cap = 45%`. A 46% applicant is rejected even with an 800 credit score._
- **PTI (Payment-to-Income)** — the _new_ loan's monthly payment alone divided by monthly income. _Example: a $350/month car loan on $3,000/month income = ~12% PTI. Used to catch cases where one expensive payment alone would dominate the budget._
- **`pti_hard_cap`** — the absolute PTI ceiling for the new loan in isolation. _Example: `pti_hard_cap = 25%`. A loan whose payment alone would eat over a quarter of monthly income is rejected._
- **Credit score** — a number from a credit bureau (Experian, Equifax, etc.) summarising your borrowing history; higher = lower risk. _Example: a long record of on-time payments → high score; missed payments last year → lower score._
- **`score_floor`** — the minimum credit score the bank will accept. _Example: `score_floor = 600`. A 580 applicant is declined; a 601 applicant continues._
- **`score_caution_band_upper`** — the top of a "be careful" zone just above the floor; in this PoC, applicants in this band drive the chat agent's recommendation toward `REVIEW` rather than `APPROVE`. _Example: floor = 600, caution upper = 670 → a 640 applicant produces a `REVIEW`-tier recommendation with the score-in-caution-band signal called out in the reasoning._
- **Cashflow** — the money flowing in and out of a customer's bank accounts over recent months. _Example: salary credits in, rent/utilities/card-minimums out — used to verify the income claim and spot stressed accounts._
- **NSF (Non-Sufficient Funds)** — a transaction that bounced because the account was empty; the count of recent NSF events is a red flag. _Example: 5 NSF events in the last 6 months suggests the applicant routinely runs out of money before payday._

## Identity & screening

- **KYC (Know Your Customer)** — verifying who the customer actually is: valid ID, address, date of birth, sometimes employer. _Example: the bank checks your passport hasn't expired and your stated address matches a utility bill._
- **AML (Anti-Money Laundering)** — checks designed to catch attempts to launder money or fund terrorism through the bank. _Example: an applicant whose name matches a public terrorism sanctions list is rejected before any credit check runs._
- **PEP (Politically Exposed Person)** — a senior public figure (or close associate) who needs extra scrutiny because they're a higher corruption-risk profile. _Example: a finance minister applying for a personal loan triggers enhanced review — not denial, but more checks._
- **Sanctions list** — a public list of individuals/entities the bank is legally barred from doing business with (e.g. OFAC SDN in the US, HMT in the UK). _Example: a name match → reject, no exceptions._
- **MRZ (Machine Readable Zone)** — the two lines of letters and numbers at the bottom of a passport's photo page. _Example: OCR extracts the MRZ and verifies its checksum so a photoshopped passport fails the check._
- **Document requirements matrix** — a lookup table that says _which_ documents are required for _this_ applicant, keyed by product type, employment type, residency status, and amount band. Drives the agent-to-customer conversation about uploads. _Example: salaried + resident + small loan → ID + payslip + statement; self-employed + resident + small loan → ID + tax return + statement instead._

## Decision outcomes

- **APPROVE / REJECT** — the two **final** outcomes the bank delivers; always chosen by the human reviewer, never by the AI. _Example: reviewer reads the recommendation packet, accepts the indicative offer, closes the task → APPROVE; or finds an inconsistency the agent missed, closes the task → REJECT._
- **Recommendation tier** — the customer-facing chat agent's output is one of three tiers, attached to every HITL task: **APPROVE** (high confidence, no inconsistencies — reviewer typically confirms), **REVIEW** (minor flags — reviewer reads evidence, optionally asks the Case Research Agent, may ask the customer for more), **DECLINE** (inconsistencies, missing data, compliance hits — reviewer typically confirms reject). Always accompanied by **reasoning** (LLM-composed, grounded in OPA + cited policy) and — for REVIEW — **explore-hints** (areas the reviewer should look at or follow-up data to request from the customer). _Example: DTI 0.41, expat self-employed, payslip OCR marginal → tier = REVIEW, reasoning enumerates each signal, explore-hints suggest "check 12-month NSF pattern, compare against similar expat self-employed profiles"._
- **HITL task** — a human-in-the-loop work item. **Every** application produces exactly one HITL task; there is no auto-decision path. _Example: 1,000 applications submitted → 1,000 HITL tasks in the queue, distributed across the three recommendation tiers._
- **Case Research Agent** — a backoffice-only AI assistant invoked from the HITL task detail screen. It has **broader read scope** than the customer-facing chat agent (full transaction history, decision audit, parameter history, deeper case similarity) but **no side-effect tools** — it can read, analyse, and explain, but cannot create tasks, write decisions, or change state. _Example: reviewer asks "show me similar self-employed expat cases in the last 12 months with PTI > 0.4" → agent answers with three anchor case_ids and reviewer outcomes, cited from `case_history` + `decision`._
- **Reason code** — a short, standardised label explaining a signal driving the recommendation or the final decision. _Example: `DTI_OVER_CAP`, `EXPIRED_ID`, `SCORE_BELOW_FLOOR` — so two declines for "the customer was too indebted" appear identically in audit and customer notices._
- **Counter-offer** — instead of declining outright, the bank offers a smaller, shorter, or pricier loan the applicant might still afford. _Example: you ask for $20,000, the bank offers $12,000 at a higher rate. (Out of scope for this PoC.)_
- **Adverse action** — regulator term for any negative outcome the bank delivers to a customer (decline, smaller amount, worse rate). Most regimes require the bank to tell the customer the specific reasons. _Example: US Reg B / ECOA requires a written adverse-action notice within 30 days listing at least four reasons._

## Fairness & compliance

- **Fair lending** — the obligation not to discriminate against borrowers based on protected attributes (age band, gender, ethnicity, nationality, etc.). _Example: if approval rates are systematically lower for one age band than another among similar profiles, that's a fair-lending concern._
- **Disparate impact** — a rule that looks neutral on its face but produces unequal outcomes across protected groups. _Example: "must own property" sounds neutral but blocks renters disproportionately — disparate impact even with no intent to discriminate._
- **Protected attribute** — a customer characteristic that fair-lending rules say can't drive different decisions; most regimes include age band, gender, ethnicity/race, nationality. _Example: the application may collect "year of birth" for KYC, but the decision logic must not key off age band._
- **4/5 rule** (a.k.a. **80% rule**) — US regulatory rule of thumb: if a protected group's approval rate is below 80% of the highest-approved group's rate, that's a flag. _Example: men 80% approved, women 60% → 60/80 = 75% → below 80% → review._
- **ECOA (Equal Credit Opportunity Act)** — US federal law barring credit discrimination based on race, religion, sex, age, marital status, etc. Other regions have analogues (EU equal-treatment directives, UK Equality Act). _Example: a bank cannot decline because the applicant is over 65 — age is protected._
- **Right of explanation** — the customer's right to be told, in understandable language, why they were declined. _Example: "Declined because your credit score was 540, below our floor of 600" — not just "we said no."_

## Portfolio & risk management

- **Exposure** — total money the bank has currently lent out and is therefore "at risk." _Example: 10,000 personal loans averaging $8,000 = $80M exposure._
- **Stress scenario / stress test** — re-running the portfolio's numbers under bad-but-plausible conditions to see how many customers would struggle to pay. _Example: "if interest rates jump 2 percentage points, how many of our borrowers cross the DTI cap?"_
- **Rate shock** (e.g. **+200 bps**) — a hypothetical jump in interest rates applied in a stress test. _Example: +200 bps = +2 percentage points; a 5% mortgage becomes 7%._
- **bps (basis points)** — one bp = 0.01% (one hundredth of a percentage point); used because rates move in small increments. _Example: rates rising "25 bps" = rates rising 0.25 percentage points._
- **Income shock** (e.g. **−10%**) — a hypothetical drop in customer incomes used in stress tests, simulating layoffs or recession. _Example: assume every customer earns 10% less and recompute who can still afford their loan._
- **Decision drift** — when approval rate, average rate, average DTI, or other portfolio metrics shift over time without an explicit policy change — usually a sign that something upstream changed silently. _Example: approval rate drifts from 62% → 51% over three months despite no policy edit; data or model behaviour has shifted._
- **Delinquency** — a payment that's overdue but not yet written off, usually bucketed as 30 / 60 / 90 days past due. _Example: a 45-day-late payment is "60-day delinquent" in most banks' bucketing._
- **Charge-off / write-off** — declaring a loan unrecoverable and removing it from the active book. (Out of scope for this PoC; mentioned because the term appears in industry materials.) _Example: after 180 days delinquent with no contact, the bank charges off the loan and pursues recovery separately._
