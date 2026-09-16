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
data sources registered, and four MCP servers reporting connected.

## 9. Load `CHAT_FLOW`

Import `paf/flows/CHAT_FLOW.paf` (password `WelcomeAmigo123!`) through
Agent Builder → My Custom Flows → Import.

A bundle carries the MCP server ids of the install it came from, so rebind
every MCP node by server name:

```bash
python manage.py paf link-flow
```

Publish the flow in Agent Builder — the integration endpoint only serves the
published version, so publish after every edit. Then mint the key the backend
calls it with:

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

Expect: the happy-path tiers pass, each leaving one `hitl_task` row.

> **Not part of a deployment from scratch** — skip it and continue at §11.
>
> To attack the conversation rather than the pipeline, the adversarial bench
> holds whole conversations through the Spring backend. It clears the queue,
> both chat histories and the sessions before it starts, and takes 25–45
> minutes.
>
> ```bash
> python manage.py cloud bench
> ```
>
> The cases and what each one attacks are in
> [`docs/TEST-BENCH.md`](docs/TEST-BENCH.md).

## 11. `info`

```bash
python manage.py info
```

Expect the load balancer address and the paths `/`, `/backoffice`, `/v1` and
`/agentFactory`, all over HTTPS, followed by the readiness of all four tiers.
The certificate is self-signed, so a browser warns once.

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

The install sheet ends at PAF's UI; §9 onward — import, `link-flow`, publish,
`api-key` — closes the loop. `manage.py info` says how far it has got.

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
