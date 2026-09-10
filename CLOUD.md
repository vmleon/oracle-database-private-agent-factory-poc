# CLOUD — the runbook

Stands the PoC up on OCI: four computes, an Autonomous Database, a public load
balancer serving HTTPS, and a private one fronting the MCP wrappers. Models come
from the OCI Generative AI service.

Nothing in the deployment stores an API key: the `paf` compute calls Generative
AI as an **instance principal**, and the database as a **resource principal**.

The design behind it is [`docs/DEPLOYMENT.md §4`](docs/DEPLOYMENT.md). For the
local runbook, see [`LOCAL.md`](LOCAL.md).

## 1. Prerequisites

```bash
brew install terraform oci-cli
oci setup config
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

Also required:

- A profile in `~/.oci/config` for the workload compartment, and one with
  tenancy-admin rights for step 5. They may be the same profile.
- The **x86_64** PAF kit in `paf/dist/` — the cloud computes are AMD, so the
  ARM64 kit used locally will not run. See [`paf/dist/README.md`](paf/dist/README.md).

## 2. `setup cloud`

```bash
python manage.py setup cloud
```

Discovers rather than assumes: probes every subscribed region for Generative AI,
lists compartments as filterable paths, and offers only models that are `ACTIVE`
**and** still served on demand. It defaults to a Cohere chat model — PAF can only
parse Cohere-format streaming — and refuses an embedding model whose width does
not match the `VECTOR` width in the changelog.

Expect: `.env` with `DEPLOYMENT_TARGET=cloud`, generated ADB passwords, and both model ids.

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

## 6. `cloud up`

```bash
python manage.py cloud plan
python manage.py cloud up
```

Expect: `lb_ip`, the per-path `urls`, `ops_public_ip`, and `mcp_server_urls`.

## 7. Wait for the tiers to build themselves

Cloud-init installs each tier from its own artifact and retries under systemd
until it succeeds. The sentinel is written only after the play passes.

```bash
ssh opc@$(terraform -chdir=deploy/tf/app output -raw ops_public_ip)
sudo test -f /var/lib/paf-poc/bootstrap.ok && echo built
sudo tail -f /var/log/paf-poc-bootstrap.log
```

The `ops` tier applies the changelog with `--contexts=adb,seed` as part of its
play, so the schema and the demo dataset are in place when it finishes.

## 8. `paf bootstrap`

```bash
python manage.py paf bootstrap
```

Prints the installer URL and every value to paste into it. Work through the
seven steps in a browser; the sheet tells you where these fit:

```bash
python manage.py paf admin
python manage.py paf trust-ca
python manage.py paf allow-internal-mcp
```

Expect: PAF installed, both model configurations answering a test call, the
data sources registered, and four MCP servers reporting connected.

## 9. Load `CHAT_FLOW`

Import `paf/flows/CHAT_FLOW.paf` (password `WelcomeAmigo123!`) through
Agent Builder → My Custom Flows → Import, then:

```bash
python manage.py paf link-flow
python manage.py paf api-key
```

`link-flow` rebinds every MCP node by server name — a bundle carries the ids of
the install it came from. Publish the flow, then mint the key.

Expect: `PAF_AGENT_ID` and `PAF_API_KEY` in `.env`.

## 10. `cloud test`

```bash
python manage.py cloud test
```

Runs the end-to-end harness from the bastion, which is the only host that can
reach both PAF and the database.

Expect: the happy-path tiers pass, each leaving one `hitl_task` row.

## 11. `info`

```bash
python manage.py info
```

Expect the load balancer address and the paths `/`, `/backoffice`, `/v1` and
`/agentFactory`, all over HTTPS. The certificate is self-signed, so a browser
warns once.

## Teardown

```bash
python manage.py cloud down
python manage.py clean
```

`cloud down` makes up to three passes: the first often fails on the database's
network security group, which still reports attached VNICs for a few seconds
after the database is gone. The IAM root is left alone for the next deployment.

## Full rebuild in one paste

```bash
source venv/bin/activate
python manage.py setup cloud
python manage.py build
python manage.py tf
python manage.py cloud iam
python manage.py cloud up
python manage.py paf bootstrap
```

## When something does not come up

| Symptom                                            | Look at                                                                                              |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| A tier never writes `bootstrap.ok`                 | `/var/log/<label>-bootstrap.log`, then `/home/opc/ansible-playbook.log` on that instance                |
| Model calls fail in PAF's LLM Management           | Step 5 was skipped, or the connection names a different compartment from the one the policy grants      |
| Every agent turn returns a JSON decode error       | The generation model is not a `cohere.*` one — see [`docs/TROUBLESHOOT.md`](docs/TROUBLESHOOT.md)        |
| An MCP server will not connect                     | `paf trust-ca` and `paf allow-internal-mcp` both have to run before the first registration              |
| The load balancer does not answer                  | Backend health in the OCI console; a tier listens only once its play has finished                       |
| `cloud down` fails on a security group             | Expected — it retries by itself; a manual re-run is equally safe                                        |
