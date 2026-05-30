# Loan Origination — Plan 1: Data + Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the database changes and two MCP tools (`get_context`, `upsert_application`) that let a chat agent read a customer's full context by session token and create/patch their DRAFT loan application — the foundation for conversational intake.

**Architecture:** Schema changes go in a new additive Liquibase changeset `012` (plus runOnChange edits to the package and the customer-safe view). `get_context` extends the existing read-only `banking-mcp` (REPORTING user). `upsert_application` is a new write MCP server `application-mcp` (AGENT_FACTORY user) calling a new PL/SQL function, mirroring `hitl-mcp`. Both resolve `customer_id` from the token with bind variables — the conversation never supplies an id.

**Tech Stack:** Oracle 26ai, Liquibase (YAML changesets), Python 3 + `fastmcp` + `oracledb`, Podman Compose, `manage.py`.

**Verification style:** these are thin DB wrappers; this repo verifies them with scripted smoke calls against the live local stack (as in `docs/TROUBLESHOOT.md` and the prior `SMOKE_TEST`), not mocked unit tests. Each task ends with a concrete smoke check + expected output, then a commit.

This is **Plan 1 of 3** (Data + Tools). Plan 2 = backend (Java); Plan 3 = PAF flow. Spec: `docs/superpowers/specs/2026-05-30-loan-origination-chat-design.md`.

---

## File Structure

- Create: `database/liquibase/oracle/012-origination-intake.yaml` — nullable FKs + nullable draft fields + no-app seed customer. Registered in the master changelog.
- Modify: `database/liquibase/oracle/db.changelog-master.yaml` — include `012`.
- Modify: `database/liquibase/oracle/006-reporting-views.yaml` — add `kyc_updated_at` to `chat_v_applicant_profile` (runOnChange).
- Modify: `database/liquibase/oracle/007-agent-tools.yaml` — add `upsert_draft_application` to the package spec (runOnChange).
- Modify: `database/liquibase/oracle/009-tx-event-queues.yaml` — add `upsert_draft_application` to the package body (runOnChange).
- Modify: `src/ai/banking-mcp/server.py` — add the `get_context` tool.
- Create: `src/ai/application-mcp/server.py`, `src/ai/application-mcp/requirements.txt`, `src/ai/application-mcp/Dockerfile` — the write MCP server (copy the `hitl-mcp` layout).
- Modify: `deploy/podman/compose.local.yml` — add the `application-mcp` service.
- Modify: `manage.py` — add `application-mcp` to the services list.

---

## Task 1: Changeset 012 — nullable FKs and nullable draft fields

A pre-application session has no `application_id`; a DRAFT being filled in over several turns has no amount/term yet. Relax those NOT NULLs.

**Files:**

- Create: `database/liquibase/oracle/012-origination-intake.yaml`
- Modify: `database/liquibase/oracle/db.changelog-master.yaml`

- [ ] **Step 1: Create the changeset file with the four column relaxations**

```yaml
databaseChangeLog:
  # 012 — conversational origination intake.
  # A customer can now log in and chat WITHOUT an existing application:
  #  - auth_session.application_id becomes optional (the session binds to the
  #    customer; the application is resolved as the customer's open one).
  #  - chat_message.application_id becomes optional (a pre-application turn has
  #    no application yet; the room is keyed by customer).
  #  - loan_application.amount_requested / term_months become optional so the
  #    Concierge agent can create a DRAFT and patch fields as the conversation
  #    collects them. get_context.missing[] reports which are still null.

  - changeSet:
      id: 012-auth-session-application-id-nullable
      author: paf-poc
      changes:
        - sql:
            sql: ALTER TABLE APP.auth_session MODIFY (application_id NULL)

  - changeSet:
      id: 012-chat-message-application-id-nullable
      author: paf-poc
      changes:
        - sql:
            sql: ALTER TABLE APP.chat_message MODIFY (application_id NULL)

  - changeSet:
      id: 012-loan-application-amount-term-nullable
      author: paf-poc
      changes:
        - sql:
            sql: |-
              ALTER TABLE APP.loan_application
                MODIFY (amount_requested NULL, term_months NULL)
```

- [ ] **Step 2: Register 012 in the master changelog**

In `database/liquibase/oracle/db.changelog-master.yaml`, add the include after the `011` line (match the existing `include:` style in that file):

```yaml
- include:
    file: 012-origination-intake.yaml
    relativeToChangelogFile: true
```

- [ ] **Step 3: Apply and verify**

Run: `python manage.py local up`
Then verify the columns are nullable:

Run:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
set heading off feedback off
SELECT table_name||'.'||column_name||' '||nullable
  FROM all_tab_columns
 WHERE owner='APP'
   AND ((table_name='AUTH_SESSION' AND column_name='APPLICATION_ID')
     OR (table_name='CHAT_MESSAGE' AND column_name='APPLICATION_ID')
     OR (table_name='LOAN_APPLICATION' AND column_name IN ('AMOUNT_REQUESTED','TERM_MONTHS')))
 ORDER BY 1;
SQL
```

Expected: every line ends in `Y` (nullable).

- [ ] **Step 4: Commit**

```bash
git add database/liquibase/oracle/012-origination-intake.yaml database/liquibase/oracle/db.changelog-master.yaml
git commit -m "feat(db): make session/draft fields nullable for chat intake"
```

---

## Task 2: Expose `kyc_updated_at` on the customer-safe profile view

`get_context` computes KYC staleness; the view must surface the timestamp. `006` uses runOnChange, so editing the view in place is the intended pattern.

**Files:**

- Modify: `database/liquibase/oracle/006-reporting-views.yaml`

- [ ] **Step 1: Add `kyc_updated_at` to `chat_v_applicant_profile`**

In the `CREATE OR REPLACE VIEW REPORTING.chat_v_applicant_profile` select list, add `c.kyc_updated_at` immediately after the existing `c.kyc_status` line:

```sql
                c.kyc_status,
                c.kyc_updated_at,
```

- [ ] **Step 2: Apply and verify the column is exposed**

Run: `python manage.py local up`
Run:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
set heading off feedback off
SELECT column_name FROM all_tab_columns
 WHERE owner='REPORTING' AND table_name='CHAT_V_APPLICANT_PROFILE'
   AND column_name='KYC_UPDATED_AT';
SQL
```

Expected: prints `KYC_UPDATED_AT`.

- [ ] **Step 3: Commit**

```bash
git add database/liquibase/oracle/006-reporting-views.yaml
git commit -m "feat(db): expose kyc_updated_at on chat_v_applicant_profile"
```

---

## Task 3: Seed a no-application demo customer

The fixture that exercises intake: full profile + employment + credit + fresh KYC, but **no** `loan_application` row.

**Files:**

- Modify: `database/liquibase/oracle/012-origination-intake.yaml`

- [ ] **Step 1: Append the seed changeset**

Add to `012-origination-intake.yaml` (after the column changesets). The inserts mirror the patterns already in `002`/`010` (customer via column list; child rows joined by `full_name`):

```yaml
- changeSet:
    id: 012-seed-no-application-customer
    author: paf-poc
    changes:
      - sql:
          sql: |-
            INSERT INTO APP.customer
              (full_name, date_of_birth, residency, email, phone, kyc_status, kyc_updated_at)
            VALUES ('Liam NoApplication', DATE '1989-04-12', 'RESIDENT',
                    'liam@example.com', '+10000000011', 'PASSED', SYSTIMESTAMP)
      - sql:
          sql: |-
            INSERT INTO APP.employment
              (customer_id, employer_name, employment_type, monthly_salary, is_current)
            SELECT customer_id, 'Globex Corporation', 'SALARIED', 5200, 'Y'
              FROM APP.customer WHERE full_name = 'Liam NoApplication'
      - sql:
          sql: |-
            INSERT INTO APP.credit_bureau_snapshot
              (customer_id, snapshot_date, score, score_scale_min, score_scale_max)
            SELECT customer_id, SYSDATE, 705, 300, 850
              FROM APP.customer WHERE full_name = 'Liam NoApplication'
```

- [ ] **Step 2: Apply and verify the customer exists with no application**

Run: `python manage.py local up`
Run:

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
set heading off feedback off
SELECT c.customer_id||' apps='||
       (SELECT COUNT(*) FROM APP.loan_application la WHERE la.customer_id=c.customer_id)
  FROM APP.customer c WHERE c.full_name='Liam NoApplication';
SQL
```

Expected: one line like `12 apps=0` (id may differ; `apps=0` is the point).

- [ ] **Step 3: Commit**

```bash
git add database/liquibase/oracle/012-origination-intake.yaml
git commit -m "feat(db): seed a no-application demo customer for intake"
```

---

## Task 4: `upsert_draft_application` PL/SQL function

Resolves the customer from the token, creates the DRAFT on first call, patches supplied fields after. Spec in `007` (runOnChange), body in `009` (runOnChange) — both are CREATE OR REPLACE by design.

**Files:**

- Modify: `database/liquibase/oracle/007-agent-tools.yaml`
- Modify: `database/liquibase/oracle/009-tx-event-queues.yaml`

- [ ] **Step 1: Add the function to the package SPEC**

In `007-agent-tools.yaml`, inside `CREATE OR REPLACE PACKAGE AGENT_TOOLS.PKG_AGENT_TOOLS AS`, add this declaration before `END PKG_AGENT_TOOLS;`:

```sql
                -- upsert_draft_application: resolve the customer from the
                -- opaque session token, create their DRAFT loan application on
                -- first call, then patch any supplied field. Returns the
                -- application_id. NULL args leave existing values untouched.
                FUNCTION upsert_draft_application(
                  p_session_token IN VARCHAR2,
                  p_amount        IN NUMBER,
                  p_term_months   IN NUMBER,
                  p_purpose       IN VARCHAR2
                ) RETURN NUMBER;
```

- [ ] **Step 2: Add the function BODY**

In `009-tx-event-queues.yaml`, inside the `CREATE OR REPLACE PACKAGE BODY AGENT_TOOLS.PKG_AGENT_TOOLS AS` changeset, add this function before `END PKG_AGENT_TOOLS;`:

```sql
                FUNCTION upsert_draft_application(
                  p_session_token IN VARCHAR2,
                  p_amount        IN NUMBER,
                  p_term_months   IN NUMBER,
                  p_purpose       IN VARCHAR2
                ) RETURN NUMBER AS
                  l_customer_id    APP.loan_application.customer_id%TYPE;
                  l_application_id APP.loan_application.application_id%TYPE;
                  l_product_id     APP.product_catalog.product_id%TYPE;
                BEGIN
                  -- Fail-secure: unknown/expired token raises NO_DATA_FOUND,
                  -- which the MCP wrapper maps to invalid_or_expired_session.
                  SELECT customer_id INTO l_customer_id
                    FROM APP.auth_session
                   WHERE session_token = p_session_token
                     AND (expires_at IS NULL OR expires_at > SYSTIMESTAMP);

                  SELECT product_id INTO l_product_id
                    FROM APP.product_catalog
                   WHERE product_type = 'PERSONAL_LOAN'
                   FETCH FIRST 1 ROW ONLY;

                  BEGIN
                    SELECT application_id INTO l_application_id
                      FROM APP.loan_application
                     WHERE customer_id = l_customer_id
                       AND status IN ('DRAFT','SUBMITTED','IN_REVIEW')
                     ORDER BY application_id DESC
                     FETCH FIRST 1 ROW ONLY;
                  EXCEPTION WHEN NO_DATA_FOUND THEN
                    l_application_id := NULL;
                  END;

                  IF l_application_id IS NULL THEN
                    INSERT INTO APP.loan_application
                      (customer_id, product_id, amount_requested, term_months,
                       purpose, channel, status)
                    VALUES
                      (l_customer_id, l_product_id, p_amount, p_term_months,
                       p_purpose, 'CHAT', 'DRAFT')
                    RETURNING application_id INTO l_application_id;
                  ELSE
                    UPDATE APP.loan_application
                       SET amount_requested = NVL(p_amount, amount_requested),
                           term_months      = NVL(p_term_months, term_months),
                           purpose          = NVL(p_purpose, purpose)
                     WHERE application_id = l_application_id;
                  END IF;

                  RETURN l_application_id;
                END upsert_draft_application;
```

- [ ] **Step 3: Grant INSERT/UPDATE on loan_application to AGENT_TOOLS**

The package runs with definer's rights, so `AGENT_TOOLS` needs write on the table. Add a new changeset to `012-origination-intake.yaml`:

```yaml
- changeSet:
    id: 012-grant-loan-application-write-to-agent-tools
    author: paf-poc
    changes:
      - sql:
          sql: GRANT INSERT, UPDATE ON APP.loan_application TO AGENT_TOOLS
```

- [ ] **Step 4: Apply and verify the function compiles and works**

Run: `python manage.py local up`
Run (mints a token for the seeded no-app customer, calls the function, expects a new application id, then confirms a DRAFT row exists):

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
set serveroutput on heading off feedback off
DECLARE
  l_cust NUMBER; l_app NUMBER;
BEGIN
  SELECT customer_id INTO l_cust FROM APP.customer WHERE full_name='Liam NoApplication';
  INSERT INTO APP.auth_session (session_token, customer_id, scenario_label)
    VALUES ('plan1-smoke-token', l_cust, 'plan1 smoke');
  l_app := AGENT_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application('plan1-smoke-token', 18000, 36, 'Car purchase');
  DBMS_OUTPUT.PUT_LINE('created application_id='||l_app);
  l_app := AGENT_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application('plan1-smoke-token', NULL, 48, NULL);
  DBMS_OUTPUT.PUT_LINE('after patch term -> '||
    (SELECT term_months||'/'||amount_requested FROM APP.loan_application WHERE application_id=l_app));
  ROLLBACK;
END;
/
SQL
```

Expected: `created application_id=<n>` then `after patch term -> 48/18000` (idempotent: same id, term patched, amount preserved). `ROLLBACK` leaves no test data.

- [ ] **Step 5: Commit**

```bash
git add database/liquibase/oracle/007-agent-tools.yaml database/liquibase/oracle/009-tx-event-queues.yaml database/liquibase/oracle/012-origination-intake.yaml
git commit -m "feat(db): add upsert_draft_application package function"
```

---

## Task 5: `get_context` tool on banking-mcp

One token-keyed read returning customer + profile + credit + open application (or null) + `missing[]` + staleness, so any agent is self-sufficient.

**Files:**

- Modify: `src/ai/banking-mcp/server.py`

- [ ] **Step 1: Add the SQL constants** (after the existing `_APPLICATION_CONTEXT_SQL`)

```python
_CUSTOMER_BY_TOKEN_SQL = """
    SELECT customer_id
      FROM APP.auth_session
     WHERE session_token = :token
       AND (expires_at IS NULL OR expires_at > SYSTIMESTAMP)
"""

_PROFILE_SQL = """
    SELECT p.customer_id,
           p.age_years,
           LOWER(p.residency)        AS residency,
           p.kyc_status,
           p.kyc_updated_at,
           LOWER(p.employment_type)  AS employment_type,
           p.monthly_salary,
           p.employer_name,
           b.score                   AS credit_score,
           NVL((SELECT SUM(f.monthly_payment)
                  FROM REPORTING.chat_v_existing_facilities f
                 WHERE f.customer_id = p.customer_id), 0) AS existing_monthly_debt
      FROM REPORTING.chat_v_applicant_profile p
      LEFT JOIN REPORTING.chat_v_credit_bureau b ON b.customer_id = p.customer_id
     WHERE p.customer_id = :customer_id
"""

_OPEN_APPLICATION_SQL = """
    SELECT application_id, amount_requested, term_months,
           product_type, purpose, status
      FROM REPORTING.chat_v_loan_application
     WHERE customer_id = :customer_id
       AND status IN ('DRAFT','SUBMITTED','IN_REVIEW')
     ORDER BY application_id DESC
     FETCH FIRST 1 ROW ONLY
"""

_KYC_STALE_DAYS = 180
_REQUIRED_APPLICATION_FIELDS = ("amount_requested", "term_months", "purpose")
```

- [ ] **Step 2: Add the `get_context` tool** (after the `lookup_application` function)

```python
@mcp.tool()
def get_context(session_token: str) -> dict:
    """Resolve an opaque session token to the customer's full origination
    context in one call: identity + KYC freshness, profile/income, credit,
    existing debt, and their open application (or null) with the list of
    still-missing loan-request fields. Every origination agent calls this
    first so its facts come from the database, never from another agent's text.

    Returns a dict shaped:
      { customer:{...}, application:{...}|None with missing[], profile:{...},
        credit:{...}, facilities:{...}, derived:{dti,pti}|None }
    or {"error": "invalid_or_expired_session"} for a bad/expired token.
    """
    print(f"[get_context] called session_token={session_token!r}", flush=True)
    with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(_CUSTOMER_BY_TOKEN_SQL, token=session_token)
            row = cur.fetchone()
            if row is None:
                print("[get_context] -> invalid_or_expired_session", flush=True)
                return {"error": "invalid_or_expired_session"}
            customer_id = int(row[0])

            cur.execute(_PROFILE_SQL, customer_id=customer_id)
            p = dict(zip([d[0].lower() for d in cur.description], cur.fetchone()))

            cur.execute(_OPEN_APPLICATION_SQL, customer_id=customer_id)
            app_row = cur.fetchone()
            application = None
            derived = None
            if app_row is not None:
                a = dict(zip([d[0].lower() for d in cur.description], app_row))
                missing = [f for f in _REQUIRED_APPLICATION_FIELDS if a.get(f) is None]
                application = {
                    "id": int(a["application_id"]),
                    "status": a["status"],
                    "amount_requested": _f(a["amount_requested"]),
                    "term_months": _i(a["term_months"]),
                    "purpose": a["purpose"],
                    "missing": missing,
                }
                if not missing:
                    monthly_payment = round(float(a["amount_requested"]) / int(a["term_months"]), 2)
                    salary = float(p["monthly_salary"])
                    debt = float(p["existing_monthly_debt"])
                    derived = {
                        "monthly_payment": monthly_payment,
                        "pti": round(monthly_payment / salary, 2),
                        "dti": round((debt + monthly_payment) / salary, 2),
                    }

            kyc_updated_at = p.get("kyc_updated_at")
            kyc_age_days = None
            kyc_stale = True
            if kyc_updated_at is not None:
                kyc_age_days = (_now_utc() - kyc_updated_at).days
                kyc_stale = kyc_age_days > _KYC_STALE_DAYS

            result = {
                "customer": {
                    "id": customer_id,
                    "age_years": _i(p["age_years"]),
                    "residency": p["residency"],
                    "kyc_status": p["kyc_status"],
                    "kyc_age_days": kyc_age_days,
                    "kyc_stale": kyc_stale,
                },
                "application": application,
                "profile": {
                    "employment_type": p["employment_type"],
                    "employer_name": p["employer_name"],
                    "monthly_salary": _f(p["monthly_salary"]),
                    "income_stale": False,  # Phase 2: wire real income recency
                },
                "credit": {"score": _i(p["credit_score"])},
                "facilities": {"existing_monthly_debt": _f(p["existing_monthly_debt"])},
                "derived": derived,
            }
            print(f"[get_context] -> customer_id={customer_id} has_app={application is not None} "
                  f"missing={application['missing'] if application else None} kyc_stale={kyc_stale}", flush=True)
            return result
```

- [ ] **Step 3: Add the small helpers** (near the top of the module, after the imports)

```python
from datetime import datetime, timezone


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _f(v):
    return None if v is None else float(v)


def _i(v):
    return None if v is None else int(v)
```

Note: `kyc_updated_at` comes back as a naive datetime from oracledb; `(_now_utc() - kyc_updated_at)` would raise on naive/aware mix. Make the subtraction tolerant by normalizing in `_now_utc` usage:

In Step 2 replace `kyc_age_days = (_now_utc() - kyc_updated_at).days` with:

```python
                ref = kyc_updated_at if kyc_updated_at.tzinfo else kyc_updated_at.replace(tzinfo=timezone.utc)
                kyc_age_days = (_now_utc() - ref).days
```

- [ ] **Step 4: Rebuild banking-mcp and smoke-test all three cases**

Run: `podman compose -f deploy/podman/compose.local.yml up -d --build banking-mcp`
Wait ~5s, then exercise the tool over its streamable-http endpoint. Use the seeded no-app customer (mint a token first):

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
INSERT INTO APP.auth_session (session_token, customer_id, scenario_label)
SELECT 'plan1-getctx-token', customer_id, 'plan1 getctx' FROM APP.customer WHERE full_name='Liam NoApplication';
COMMIT;
SQL
podman exec paf-banking-mcp python -c "
import asyncio
from fastmcp import Client
async def main():
    async with Client('http://localhost:8503/mcp/') as c:
        r = await c.call_tool('get_context', {'session_token':'plan1-getctx-token'})
        print(r.data)
        r2 = await c.call_tool('get_context', {'session_token':'bogus'})
        print(r2.data)
asyncio.run(main())
"
```

Expected: first line shows `customer` populated, `application: None`, `kyc_stale: False`; second line shows `{'error': 'invalid_or_expired_session'}`.

- [ ] **Step 5: Clean up the smoke token and commit**

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
DELETE FROM APP.auth_session WHERE session_token IN ('plan1-getctx-token');
COMMIT;
SQL
git add src/ai/banking-mcp/server.py
git commit -m "feat(banking-mcp): add get_context token-keyed read with missing[]/staleness"
```

---

## Task 6: `application-mcp` write server with `upsert_application`

A new side-effect MCP server (AGENT_FACTORY user) that calls `upsert_draft_application`. Mirrors `hitl-mcp` exactly.

**Files:**

- Create: `src/ai/application-mcp/server.py`, `requirements.txt`, `Dockerfile`
- Modify: `deploy/podman/compose.local.yml`, `manage.py`

- [ ] **Step 1: Copy the hitl-mcp scaffolding**

Run:

```bash
mkdir -p src/ai/application-mcp
cp src/ai/hitl-mcp/requirements.txt src/ai/application-mcp/requirements.txt
cp src/ai/hitl-mcp/Dockerfile src/ai/application-mcp/Dockerfile
```

- [ ] **Step 2: Write `src/ai/application-mcp/server.py`**

```python
"""application-mcp — the write surface for conversational intake.

Single tool: upsert_application(session_token, amount?, term_months?, purpose?)
creates the customer's DRAFT loan application on first call and patches
supplied fields after. customer_id is resolved from the opaque token inside
the PL/SQL function (bind variables) — never from the chat message, so this
cannot be steered to another customer's application (IDOR-safe, same boundary
as banking-mcp.lookup_application / get_context).

Connects as AGENT_FACTORY, which has EXECUTE on AGENT_TOOLS.PKG_AGENT_TOOLS;
the package runs with definer's rights (AGENT_TOOLS has INSERT/UPDATE on
APP.loan_application via changeset 012). Mirrors hitl-mcp.
"""

from __future__ import annotations

import os

import oracledb
from fastmcp import FastMCP

mcp = FastMCP("application-mcp")

DB_DSN = f"{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_SERVICE']}"
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


@mcp.tool()
def upsert_application(
    session_token: str,
    amount: float | None = None,
    term_months: int | None = None,
    purpose: str | None = None,
) -> dict:
    """Create or patch the customer's DRAFT loan application.

    The Concierge agent calls this as it collects the loan request. Pass only
    the fields you just learned; omitted/None fields are left unchanged. Safe
    to call repeatedly — it never creates a second application for a customer
    who already has an open one.

    Parameters
    ----------
    session_token : str
        Opaque login token. The customer is resolved from it server-side.
        Never pass an id taken from the chat message.
    amount : float, optional
        Requested loan amount.
    term_months : int, optional
        Repayment term in months.
    purpose : str, optional
        Free-text loan purpose.

    Returns
    -------
    dict
        { "application_id": int } on success, or
        { "error": "invalid_or_expired_session" } for a bad/expired token.
    """
    print(f"[upsert_application] token={session_token!r} amount={amount} term={term_months} purpose={purpose!r}", flush=True)
    try:
        with oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN) as conn:
            with conn.cursor() as cur:
                application_id = cur.callfunc(
                    "AGENT_TOOLS.PKG_AGENT_TOOLS.upsert_draft_application",
                    int,
                    [session_token, amount, term_months, purpose],
                )
            conn.commit()
    except oracledb.DatabaseError as e:
        # NO_DATA_FOUND from the token lookup surfaces as ORA-01403.
        (err,) = e.args
        if getattr(err, "code", None) == 1403:
            print("[upsert_application] -> invalid_or_expired_session", flush=True)
            return {"error": "invalid_or_expired_session"}
        raise
    print(f"[upsert_application] -> application_id={application_id}", flush=True)
    return {"application_id": application_id}


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8504"))
    mcp.run(transport="streamable-http", host=host, port=port)
```

- [ ] **Step 3: Add the compose service**

In `deploy/podman/compose.local.yml`, copy the `hitl-mcp` service block to an `application-mcp` block: same `build`/`environment`/network, container_name `paf-application-mcp`, and map its port (host `8504:8504`). Match the `hitl-mcp` env keys exactly (`DB_HOST`, `DB_PORT`, `DB_SERVICE`, `DB_USER`, `DB_PASSWORD`), with `DB_USER`/`DB_PASSWORD` pointing at the AGENT_FACTORY credentials used by `hitl-mcp`.

- [ ] **Step 4: Register the service in manage.py**

In `manage.py`, add `"application-mcp"` to the `services = [...]` list (the array near line 997, alongside `"hitl-mcp"`).

- [ ] **Step 5: Build, start, and smoke-test**

Run: `python manage.py local up`
Then (reuse the seeded no-app customer; mint a token, call create then patch):

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
INSERT INTO APP.auth_session (session_token, customer_id, scenario_label)
SELECT 'plan1-upsert-token', customer_id, 'plan1 upsert' FROM APP.customer WHERE full_name='Liam NoApplication';
COMMIT;
SQL
podman exec paf-application-mcp python -c "
import asyncio
from fastmcp import Client
async def main():
    async with Client('http://localhost:8504/mcp/') as c:
        print((await c.call_tool('upsert_application', {'session_token':'plan1-upsert-token','amount':18000,'term_months':36})).data)
        print((await c.call_tool('upsert_application', {'session_token':'plan1-upsert-token','purpose':'Car purchase'})).data)
        print((await c.call_tool('upsert_application', {'session_token':'bogus','amount':1})).data)
asyncio.run(main())
"
```

Expected: first two lines show the **same** `{'application_id': <n>}` (idempotent patch); third shows `{'error': 'invalid_or_expired_session'}`.

- [ ] **Step 6: Clean up and commit**

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
DELETE FROM APP.loan_application WHERE customer_id=(SELECT customer_id FROM APP.customer WHERE full_name='Liam NoApplication');
DELETE FROM APP.auth_session WHERE session_token='plan1-upsert-token';
COMMIT;
SQL
git add src/ai/application-mcp deploy/podman/compose.local.yml manage.py
git commit -m "feat(application-mcp): add upsert_application write tool"
```

---

## Task 7: Integration smoke — token → get_context → upsert → get_context

Confirms the two tools agree on a real intake sequence end to end.

**Files:** none (verification only).

- [ ] **Step 1: Run the combined smoke**

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
INSERT INTO APP.auth_session (session_token, customer_id, scenario_label)
SELECT 'plan1-e2e', customer_id, 'plan1 e2e' FROM APP.customer WHERE full_name='Liam NoApplication';
COMMIT;
SQL
podman exec paf-banking-mcp python -c "
import asyncio
from fastmcp import Client
async def main():
    async with Client('http://localhost:8503/mcp/') as c:
        print('before:', (await c.call_tool('get_context', {'session_token':'plan1-e2e'})).data['application'])
asyncio.run(main())
"
podman exec paf-application-mcp python -c "
import asyncio
from fastmcp import Client
async def main():
    async with Client('http://localhost:8504/mcp/') as c:
        await c.call_tool('upsert_application', {'session_token':'plan1-e2e','amount':18000,'term_months':36,'purpose':'Car purchase'})
asyncio.run(main())
"
podman exec paf-banking-mcp python -c "
import asyncio
from fastmcp import Client
async def main():
    async with Client('http://localhost:8503/mcp/') as c:
        print('after:', (await c.call_tool('get_context', {'session_token':'plan1-e2e'})).data['application'])
asyncio.run(main())
"
```

Expected: `before: None`; `after:` shows the application with `amount_requested: 18000.0`, `term_months: 36`, `purpose: 'Car purchase'`, `missing: []`.

- [ ] **Step 2: Clean up**

```bash
podman exec -i paf-oracle-free-26ai sqlplus -s APP/"$DB_PASSWORD"@localhost:1521/FREEPDB1 <<'SQL'
DELETE FROM APP.loan_application WHERE customer_id=(SELECT customer_id FROM APP.customer WHERE full_name='Liam NoApplication');
DELETE FROM APP.auth_session WHERE session_token='plan1-e2e';
COMMIT;
SQL
```

- [ ] **Step 3: Nothing to commit** (verification only). Plan 1 complete.

---

## Done criteria

- `git log` shows the per-task commits; `python manage.py local up` is clean.
- A no-application customer can be read (`get_context` → `application: None`), have a DRAFT created and patched idempotently (`upsert_application`), and be re-read showing the populated application with `missing: []`.
- Bad tokens fail-secure on both tools.
- Next: **Plan 2 — backend** (no-app login, `/v1/customers` flag, marker stripping, `room-cust-{id}`).
