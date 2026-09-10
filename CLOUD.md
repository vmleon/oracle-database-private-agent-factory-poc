# Cloud deployment (OCI) — the runbook

Stands the PoC up on OCI: four computes, an Autonomous Database, and a public
load balancer, with the models served by OCI Generative AI. The design behind it
is [`docs/DEPLOYMENT.md §4`](docs/DEPLOYMENT.md); this page is the steps.

Nothing in the deployment stores an API key. The `paf` compute calls Generative
AI as an **instance principal** and the database as a **resource principal**,
both through dynamic groups created in step 5.

For the local runbook, see [`LOCAL.md`](LOCAL.md).

## 1. Prerequisites

| Tool          | Install                                                                      |
| ------------- | ---------------------------------------------------------------------------- |
| `terraform`   | `brew install terraform`                                                     |
| `oci`         | `brew install oci-cli`, then `oci setup config`                              |
| `python` 3.11+ | with `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt` |

You also need:

- **A profile in `~/.oci/config`** for the workload compartment.
- **A tenancy-admin profile** for step 5. It can be the same one, if it has the rights.
- **The x86_64 PAF kit.** The cloud computes are `VM.Standard.E5.Flex` (AMD x86_64), so the ARM64 kit used locally will not run there. Download the x86_64 kit from Oracle Software Delivery into `paf/dist/` — see [`paf/dist/README.md`](paf/dist/README.md). It is gitignored.

## 2. `setup cloud`

```bash
python manage.py setup cloud
```

Picks the profile, then discovers rather than assumes: it lists your subscribed
regions, **probes each one for Generative AI** (the service runs in a minority of
them), lists compartments, and offers only chat and embedding models that are
`ACTIVE` **and** still served on demand.

The region and compartment prompts filter as you type. Compartments appear as
`Parent/Child` paths — a large tenancy holds hundreds, and the same leaf name
often appears on more than one branch.

The embedding choice is checked against the `VECTOR` width in the changelog. A
model of the wrong width is refused, because the mismatch would otherwise fail
at insert time deep in the RAG path. Regions differ in what they serve — some
offer no model with a native 1024-dimension output at all.

Expect: `.env` with `DEPLOYMENT_TARGET=cloud`, generated ADB admin and wallet
passwords, and the two model ids.

## 3. `build`

```bash
python manage.py build
```

Compiles both UI bundles and the Spring Boot jar, then stages each output — plus
the OPA bundle, the registry service and the changelog — into the Ansible role
that installs it.

Only the compiled outputs need this step. `cloud up` restages the copied ones
(changelog, policy bundle, registry) on every apply, so editing a changeset and
applying picks it up without a rebuild.

Expect: populated `files/` directories under `deploy/ansible/*/roles/*/`. They
are gitignored; `manage.py clean` removes them.

## 4. `tf`

```bash
python manage.py tf
```

Renders `terraform.tfvars` for **both** roots from `.env`, so the profile,
regions and compartment are never typed into Terraform by hand.

The two roots take different regions: the workload stack runs where you chose,
while the IAM root targets the **tenancy home region**, because identity
resources exist only there.

## 5. IAM — once per compartment, as a tenancy admin

```bash
python manage.py cloud iam
```

Creates one dynamic group per principal and the policy granting both
`use generative-ai-family`.

Expect: `3 to add` — two dynamic groups and one policy. Skip this and every
model call later fails with an authorization error.

## 6. The workload stack

```bash
python manage.py cloud plan   # optional, to see it first
python manage.py cloud up
```

Provisions the VCN, the ADB on a private endpoint, the four computes, the load
balancer, and the Object Storage bucket holding each tier's payload and the PAF
kit behind read-only pre-authenticated requests.

Expect: `lb_ip`, the per-path `urls`, `ops_public_ip`, and the wallet written to
`deploy/tf/app/generated/adb-wallet.zip`.

Terraform is always driven through `manage.py`, which runs it with `-chdir`
rather than changing directory. Running it by hand is what leaves a root without
its rendered tfvars.

## 7. Wait for the tiers to build themselves

Cloud-init hands each instance a bootstrap script that installs Ansible, fetches
that tier's payload, and runs its play. systemd owns the retry loop, so a
dependency that settles late costs one 60-second cycle rather than leaving the
tier half-built.

```bash
ssh opc@$(terraform output -raw ops_public_ip)
# on each tier:
sudo test -f /var/lib/$OCI_LABEL/bootstrap.ok && echo built
sudo tail -f /var/log/$OCI_LABEL-bootstrap.log
```

The sentinel is written only after the playbook returns success, so its presence
is trustworthy. The playbook's own output is at `/home/opc/ansible-playbook.log`.

The `ops` tier applies the changelog with `--contexts=adb,seed` as part of its
play, so the schema and the synthetic demo dataset are in place when it finishes.

## 8. `paf bootstrap`

```bash
python manage.py paf bootstrap
```

Prints the installer URL and every value to paste into it, read from `.env` and
the Terraform outputs: the ADB wallet and network alias, the two
instance-principal model configurations, the two Select AI profiles, and the four
agent tools. Driving these steps over the API is deliberately out of scope — it
has proven too fragile across PAF versions.

Work through it in the browser, then import the Agent Builder flows: `CHAT_FLOW`,
then `RESEARCH_WORKFLOW`.

## 9. `info`

```bash
python manage.py info
```

Expect the load balancer address and the paths: `/` (customer),
`/backoffice`, `/v1` (API) and `/agentFactory`.

## Teardown

```bash
python manage.py cloud down
python manage.py clean
```

`cloud down` makes up to three passes. The first often fails on the database's
network security group, which still reports attached VNICs for a few seconds
after the database itself is gone — the ordering is right, the API is just
behind.

`clean` refuses while Terraform state still holds resources, then removes the
rendered tfvars, the generated zips and every staged tier payload. The IAM root
is left alone — it is reused by the next deployment into the same compartment.

## When something does not come up

| Symptom                                     | Look at                                                                                     |
| ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| A tier never writes `bootstrap.ok`          | `/var/log/<label>-bootstrap.log`, then `/home/opc/ansible-playbook.log` on that instance       |
| Model calls fail in PAF's LLM Management    | Step 5 was skipped, or the compartment in the connection is not the one the policy names      |
| Select AI profiles are missing in PAF        | They belong to whoever created them — PAF creates them as `AGENT_FACTORY`, not Liquibase as `ADMIN` |
| The load balancer does not answer            | Backend health in the OCI console; the tiers listen only once their play has finished          |
| `cloud down` fails on a security group with "vnics attached" | Expected: the database's private endpoint VNIC detaches after the database is gone. `cloud down` retries by itself; a manual re-run is equally safe |
