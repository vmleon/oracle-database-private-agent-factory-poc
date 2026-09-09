# PAF 26.7 Cloud Delivery Plan

**Goal:** Install Private Agent Factory 26.7 onto the OCI `paf` compute under full control — an Ansible role we own, not a Marketplace image — with the kit tarball held in the repository, ignored by git, and delivered to the instance through Object Storage behind a pre-authenticated request.

**Architecture:** The kit is a 2.3 GB vendor tarball that cannot be committed and cannot be fetched by the instance from Oracle Software Delivery (that download is interactive and licence-gated). It therefore travels the same path as every other tier payload: the operator drops it into `paf/dist/`, Terraform publishes it as a managed Object Storage object, and the `pafstack` role fetches it through a read-only PAR, unpacks it, builds the image with the kit's own `build-image.sh`, and runs it under a systemd unit. The instance holds no OCI credentials at any point.

**Architecture is per-target.** The kit ships one tarball per CPU architecture and the two deployment targets do not share one: local development runs `ARM64` under Apple Silicon podman, and the cloud tiers run `VM.Standard.E5.Flex`, which is AMD x86_64. Both tarballs live side by side in `paf/dist/`, and each target's `.env` points `PAF_TARBALL` at the one that matches it.

## Authentication

PAF ships `oci_instance_principal` as a provider for both LLM and embedding connections, and its sensitive-property list is empty — the connection carries `model_id`, `service_endpoint` and `compartment_id`, and no key material. The Select AI profiles authenticate the same way from the database side, as `OCI$RESOURCE_PRINCIPAL`. Nothing in the deployment stores an API key.

Two principals, because the compute and the database each call Generative AI as themselves:

| Principal     | Matching rule                                                                       |
| ------------- | ------------------------------------------------------------------------------------- |
| `paf` compute | `ALL {instance.compartment.id = '<compartment>'}`                                     |
| ADB           | `ALL {resource.type = 'autonomousdatabase', resource.compartment.id = '<compartment>'}` |

Both are granted `use generative-ai-family` in the workload compartment. Dynamic groups and the policies that name them live in the tenancy root, which is a different permission scope from the workload stack, so they are a separate root module in `deploy/tf/iam/` applied once by an administrator.

## Model selection

Generative AI runs in a minority of regions, and the catalogue differs between the ones that have it, so `setup cloud` discovers rather than assumes: it probes every subscribed region, offers only those where the service answers, and lists only models that are `ACTIVE` **and** still served on demand. A model whose on-demand serving has retired stays `ACTIVE` and is reachable only through a paid dedicated cluster, so filtering on lifecycle state alone selects a model that cannot be called.

**Embedding width is the binding constraint.** The changelog declares `VECTOR(1024, FLOAT32)`, and a mismatch fails on insert rather than at deploy. The service does not report a model's output width through its API, so the mapping is curated in `manage.py` and checked against the width parsed out of `008-vector-rag.yaml`. `cohere.embed-english-v3.0` and `cohere.embed-multilingual-v3.0` are natively 1024; `cohere.embed-v4.0` has no fixed width and cannot be pinned, because PAF's instance-principal connection has no `output_dimension` field. Regions that serve only `embed-v4.0` therefore cannot satisfy the schema without changing it.

## Constraints

- `paf/dist/` is gitignored. No kit tarball, and no version derived from one, is ever committed.
- The version is read from the kit's `version.json` at install time. No version string is hardcoded.
- The image is built on the instance from the tarball. Pushing a prebuilt image to OCIR is rejected: it would require registry credentials on the instance and break the credential-free PAR design.
- Object Storage objects stay Terraform-managed, so `terraform destroy` empties the bucket rather than failing on a bucket the CLI filled behind Terraform's back.
- Models come from the OCI Generative AI service. No inference container runs beside PAF.

---

### Task 1: The kit lands in the repository

`paf/dist/` is where the operator puts each tarball after downloading it from Oracle Software Delivery. `setup local` and `setup cloud` both resolve `PAF_TARBALL` against that directory, defaulting to the architecture their target runs.

**Files:**

- Create: `paf/dist/README.md` — which file to download and where to put it
- Modify: `.gitignore` — ignore `paf/dist/*` except the README
- Modify: `manage.py` — `_resolve_kit_tarball()`, used by both setup commands

**Steps:**

- [x] Ignore the tarballs, keep the README tracked.
- [x] `_resolve_kit_tarball(arch)` lists `paf/dist/*.tar.gz`, and prefers a name containing the target architecture.
- [x] `setup cloud` resolves `X86_64`; `setup local` resolves the host's own architecture.
- [x] Fail with a readable message, naming the expected filename, when no matching tarball is present.

### Task 2: Terraform publishes the kit

The tarball is already an archive, so it is uploaded as-is rather than zipped again, and gets its own PAR alongside the per-tier role zips.

**Files:**

- Modify: `deploy/tf/app/artifacts.tf` — `oci_objectstorage_object.paf_tarball` + its PAR
- Modify: `deploy/tf/app/variables.tf` — `paf_tarball_path`
- Modify: `deploy/tf/app/main.tf` — `paf_tarball_par_url` into the `paf` tier's Ansible parameters

**Steps:**

- [x] `content_hash` comes from `filemd5(var.paf_tarball_path)`, so a new kit re-uploads on the next apply.
- [x] Validate that `paf_tarball_path` exists at plan time, so a missing kit fails before any resource is touched.

### Task 3: The `pafstack` role installs it

**Files:**

- Modify: `deploy/ansible/paf/roles/pafstack/tasks/main.yaml`
- Modify: `deploy/ansible/paf/roles/pafstack/templates/paf.service.j2`

**Steps:**

- [x] Install podman.
- [x] Fetch the tarball through its PAR with a timeout sized for 2.3 GB.
- [x] Unpack it, guarded by `creates:` so a retry cycle does not re-extract.
- [x] Read `app_version` from `applied-ai/kit/agent_factory/internal/version.json`.
- [x] Build the image with `./build-image.sh aai`, guarded so a retry does not rebuild.
- [x] Run PAF under a systemd unit with the ADB wallet mounted, `TNS_ADMIN` set, and the OCI Generative AI endpoint in its environment.

### Task 4: Tenancy-level IAM

**Files:**

- Create: `deploy/tf/iam/` — dynamic groups, the Generative AI policy, and its own tfvars template
- Modify: `manage.py` — `tf` renders both roots

**Steps:**

- [x] One dynamic group per principal, scoped to the workload compartment.
- [x] One policy granting both `use generative-ai-family`.
- [ ] Apply it with a tenancy-admin profile, before the workload stack.

### Task 5: Verification

- [x] `terraform validate` passes for both roots, and every declared variable is provided.
- [ ] `terraform plan` shows the object and PAR.
- [ ] PAF's LLM Management shows an `oci_instance_principal` connection that answers without a config file.
- [ ] The instance reaches `/var/lib/<project>/bootstrap.ok`.
- [ ] `podman images` on the instance shows `localhost/applied-ai-label:<app_version>`.
- [ ] The PAF console answers through the load balancer at `/agentFactory`.
