# Cloud deployment (OCI)

The cloud topology — 4 workload computes + **ADB** + **LB**, with models served by **OCI Generative AI** — is described in [`docs/DEPLOYMENT.md §4`](docs/DEPLOYMENT.md). Terraform lives in `deploy/tf/`.

```bash
python manage.py setup cloud      # region + model discovery, writes .env
python manage.py build            # compiles the UIs and jar, stages tier payloads
python manage.py tf               # renders tfvars for both Terraform roots

cd deploy/tf/iam                  # tenancy admin, once per compartment
terraform init && terraform apply # dynamic groups + Generative AI policy

cd ../app
terraform init && terraform plan -out=tfplan && terraform apply tfplan

python manage.py paf bootstrap    # instance-principal LLM/embedding, tools, flows
python manage.py info             # LB address and per-path URLs
```

Models are called with an instance principal and the database with a resource
principal, so no API key is stored anywhere in the deployment.

Tear down with `terraform destroy`, then `python manage.py clean`.

For the local runbook, see [`LOCAL.md`](LOCAL.md).
