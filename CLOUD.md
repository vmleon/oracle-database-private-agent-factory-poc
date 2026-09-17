# CLOUD — the runbook

Stands the PoC up on OCI: four computes, an Autonomous Database, a public load
balancer serving HTTPS, and a private one fronting the MCP wrappers. Models come
from the OCI Generative AI service.

Nothing in the deployment stores an API key: the `paf` compute calls Generative
AI as an **instance principal**, and the database as a **resource principal**.

The design behind it is [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## 1. Prerequisites

```bash
brew install terraform oci-cli
```

```bash
oci setup config
```

```bash
python3 -m venv venv
```

```bash
source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

Also required:

- A profile in `~/.oci/config` for the workload compartment, and one with
  tenancy-admin rights for step 5. They may be the same profile.
- The **x86_64** PAF kit in `paf/dist/`. See [`paf/dist/README.md`](paf/dist/README.md).

## 2. `setup`

```bash
python manage.py setup
```

Discovers rather than assumes: probes every subscribed region for Generative AI,
lists compartments as filterable paths, and offers only models that are `ACTIVE`
**and** still served on demand. It defaults to `openai.gpt-oss-120b` — the
generation model PAF's streaming parses end to end — and refuses an embedding
model whose width does not match the `VECTOR` width in the changelog.

Expect: `.env` with `DEPLOYMENT_TARGET=cloud`, generated ADB passwords, and both model ids.

> **Not part of a deployment from scratch** — skip it and continue at §3.
>
> To change the generation model on an **already running** install, re-run
> `setup` to pick the new model, then push its id to PAF's `gen-model`
> configuration:
>
> ```bash
> python manage.py paf gen-model
> ```
>
> PAF must already be installed for this to have anything to write to.

## 3. `build`

```bash
python manage.py build
```

Expect: populated `files/` directories under `deploy/ansible/*/roles/*/`.

## 4. `tf`

```bash
python manage.py tf
```

Expect: `terraform.tfvars` in both `deploy/tf/iam/` and `deploy/tf/app/`.

## 5. `cloud iam`

Needs the tenancy-admin profile. Runs once per compartment.

```bash
python manage.py cloud iam
```

Expect: `3 to add` — two dynamic groups and one policy.

These are tenancy-level identity resources, not part of the workload stack: they
live in their own Terraform root, are created in the tenancy's home region, and
`cloud down` deliberately leaves them behind. A second deployment into the same
compartment skips this step — the dynamic groups match by compartment, so new
computes and a new database are covered the moment they exist.

## 6. `cloud up`

```bash
python manage.py cloud plan
```

```bash
python manage.py cloud up
```

Expect: `lb_ip`, the per-path `urls`, `ops_public_ip`, and `mcp_server_urls`.

## 7. Wait for the tiers to build themselves

Cloud-init installs each tier from its own artifact and retries under systemd
until it succeeds. The sentinel is written only after the play passes.

```bash
python manage.py info
```

It reads every tier's sentinel over the bastion in one pass:

```
Tiers
  ✓ ops       ready
  ✓ paf       ready
  ✓ backend   ready
  ✓ frontend  ready

The stack is ready. Next: python manage.py paf bootstrap
```

Re-run it until all four are ready — cloud-init retries every 60 seconds, so a
dependency that settles late costs one cycle rather than the tier.

> **Only if a tier is still building after a few minutes** — otherwise keep
> re-running `info`. Diagnose it on the instance itself:
>
> ```bash
> ssh opc@$(terraform -chdir=deploy/tf/app output -raw ops_public_ip)
> ```
>
> ```bash
> sudo tail -f /var/log/paf-poc-bootstrap.log
> ```

The `ops` tier applies the changelog with `--contexts=adb,seed` as part of its
play, so the schema and the demo dataset are in place when it finishes.

## 8. `paf bootstrap`

```bash
python manage.py paf bootstrap
```

Prints the PAF install as one ordered sheet: the installer URL, every value to
paste into it, and the commands that sit between the browser steps. Follow
it top to bottom; its last line sends you back here to §9.

Expect: PAF installed, both model configurations answering a test call, the
data sources registered, and two MCP servers reporting connected.

## 9. Load `CHAT_FLOW`

Four steps, two in the browser and two on the command line. Each one is
required, and the integration endpoint answers only after the last.

### 9.1 Import

Agent Builder → **My Custom Flows** → **Import** → `paf/flows/CHAT_FLOW.paf`,
bundle password `WelcomeAmigo123!`.

### 9.2 `link-flow`

A bundle carries the MCP server ids of the install it came from, so rebind
every MCP node by server name:

```bash
python manage.py paf link-flow
```

### 9.3 Publish

Open `CHAT_FLOW` in Agent Builder and **Publish** it. An imported flow arrives
unpublished, and the integration endpoint serves only the published version, so
the next step has nothing to mint a key against until this is done. The same
holds after every later edit to the flow: publish, or the endpoint keeps
serving the version before it.

`info` shows the state under Agent: `published — serving through the
integration endpoint`.

### 9.4 `api-key`

Mint the key the backend calls the published flow with:

```bash
python manage.py paf api-key
```

Expect: `PAF_AGENT_ID` and `PAF_API_KEY` in `.env`, and a restarted
`paf-poc-backend` holding them.

The backend's unit reads the key from `/etc/paf-poc-backend.env`, which its
play creates empty: the flow is published long after the tier builds itself, so
the key cannot be rendered into the unit. The same delivery carries the
certificate PAF serves, which the backend verifies every turn against — until it
arrives, PAF calls fail on TLS. Minting and delivering are therefore one
command. `--no-push` mints without delivering, which only the harness can use.

Check where the sequence stands at any point:

```bash
python manage.py info
```

It reports the four tiers and then the agent: imported, published, MCP nodes
linked, key minted, key delivered.

## 10. `cloud test`

```bash
python manage.py cloud test
```

Runs the end-to-end harness from the bastion, which is the only host that can
reach both PAF and the database.

It clears the reviewer queue, both chat histories, the login sessions and the
tool traces first, so every scenario starts from the seeded state.

Expect 17 passed: twelve tier scenarios, five of them on the compliance bar,
four security cases covering the fail-secure error path, the token-to-customer
binding and prompt injection, and a reviewer closing two cases through the
backend, one approved and one declined.

> **Optional — not part of a deployment from scratch.** Skip it and continue at
> §11.
>
> `cloud test` proves the pipeline computes the right tier on one scripted turn.
> The **conversation bench** attacks the product instead: it signs in as a
> customer and holds whole conversations through the Spring backend, so
> `Envelope`, the disclosure filter, session resolution and `chat_message` are
> all on the path. Forty cases across four suites — the identity boundary,
> instruction override and disclosure, what gets written, and whether an
> ordinary conversation is worth the customer's time.
>
> ```bash
> python manage.py cloud bench             # the whole suite, about 20 minutes
> python manage.py cloud bench -k boundary # one suite
> python manage.py cloud bench -k zero_term # one case
> ```
>
> It is deliberately slow and strictly serial — one conversation at a time, with
> a pause between turns. Volume is not an attack it runs, and breaking a
> single-instance dev deployment by throughput proves nothing.
>
> Expect a green run with a handful of `xfail` lines at the end. Those are
> recorded defects, not failures: the attack still runs at full strength and the
> assertion is untouched, so a genuine `FAILED` means something new broke. The
> `xfail`/`XPASS` list printed at the end is the working agenda, and
> [`docs/TEST-BENCH.md`](docs/TEST-BENCH.md) explains every case.
>
> It clears the same tables as `cloud test`, plus the applications its intake
> personas created. It does not restore a seeded application an earlier run
> edited.

## 11. `info`

```bash
python manage.py info
```

Expect the load balancer address and the paths `/`, `/backoffice`, `/v1` and
`/agentFactory`, all over HTTPS, then the readiness of all four tiers, the
database answering over the bastion, and every agent line green. The
certificate is self-signed, so a browser warns once.

## 12. Prepare the demo

[`DEMO.md`](DEMO.md) assumes the stack has been through this, in this order:

```bash
python manage.py cloud test
```

```bash
python manage.py cloud bench
```

```bash
python manage.py cloud reset
```

```bash
python manage.py cloud test
```

The first two prove the stack: the scripted scenarios, then the conversation
bench's edge cases through the chat backend. The reset and the final test are
the backfill the demo opens on:

- one open case per scenario persona in the reviewer queue, twelve rows across
  all three tiers and the compliance bar;
- two closed cases in the decision history, Alice approved and David declined,
  each with the outcome on the customer's thread;
- every other chat thread empty, because the harness talks to PAF directly.

Three customers are never driven by the harness and start with no application:
**Diana Marsh**, **Tom Whitfield** and **Grace Okafor**. The live demo collects
an application for each in the chat and files a new row while the audience
watches. `cloud reset` drops the applications a rehearsal collected for them,
so a rehearsal is followed by the last two commands again.

`BANK_CORE.decision` is a blockchain table declared `NO DELETE LOCKED`: its rows
survive every reset, and the count growing across demos reads as history. An
empty decision table means `cloud down` then `cloud up`, and nothing less.

## Teardown

```bash
python manage.py cloud down
```

```bash
python manage.py clean
```

`cloud down` makes up to three passes: the first often fails on the database's
network security group, which still reports attached VNICs for a few seconds
after the database is gone. The IAM root is left alone for the next deployment.

### Removing the tenancy IAM as well

> **Only when you are finished with the compartment for good** — not between
> test runs. `cloud down` already leaves this root alone so the next deployment
> can reuse it.
>
> There is no `manage.py` command for it, because it is not part of a
> deployment's lifecycle — run Terraform against that root directly, with the
> tenancy-admin profile:
>
> ```bash
> terraform -chdir=deploy/tf/iam destroy
> ```
>
> Run it **before** `clean`, which deletes the rendered `terraform.tfvars` this
> root reads its profile and home region from. If you have already cleaned,
> `python manage.py tf` renders it again.
>
> It is a hard delete, and it reaches past this deployment:
>
> - Every stack in the same compartment loses Generative AI the moment the
>   policy goes — the `paf` compute's instance principal and the database's
>   resource principal are both granted through it, and neither holds an API key
>   to fall back on.
> - Putting it back needs tenancy-admin rights again. Without them the next
>   deployment stands up normally and then fails at PAF's model test call with a
>   permission error, which reads like a model problem rather than a missing
>   policy.
> - So the next deployment into this compartment starts at
>   [§5](#5-cloud-iam) again, before `cloud up`.

## Full rebuild in one paste

```bash
source venv/bin/activate
python manage.py setup
python manage.py build
python manage.py tf
python manage.py cloud iam
python manage.py cloud up
python manage.py paf bootstrap
```

The install sheet ends at PAF's UI; §9 — import, `link-flow`, **publish**,
`api-key`, each its own step — closes the loop. `manage.py info` says how far
it has got.

## When something does not come up

| Symptom                                                           | Look at                                                                                                                          |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| A tier never writes `bootstrap.ok`                                | `manage.py info` names which one; then `/var/log/<label>-bootstrap.log` and `/home/opc/ansible-playbook.log` on that instance    |
| Model calls fail in PAF's LLM Management                          | Step 5 was skipped or its IAM root was destroyed, or the connection names a different compartment from the one the policy grants |
| The manager never delegates, or every turn is a JSON decode error | The generation model is a `cohere.*` or `meta.*` one — see [`docs/TROUBLESHOOT.md`](docs/TROUBLESHOOT.md)                        |
| An MCP server will not connect                                    | `paf prepare` (bootstrap step 6) has to run before the first registration                                                        |
| The load balancer does not answer                                 | Backend health in the OCI console; a tier listens only once its play has finished                                                |
| The chat UI answers but never reaches the agent                   | The backend has no key: `manage.py info` shows it under Agent; `paf api-key` mints and delivers, `paf push-key` re-delivers      |
| `cloud down` fails on a security group                            | Expected — it retries by itself; a manual re-run is equally safe                                                                 |
