# Tenancy-level IAM for the stack

Dynamic groups and the policies that reference them live in the **tenancy root
compartment**, which is a different permission scope from the workload stack in
`../app/`. They are applied once by a tenancy administrator and then left alone,
so they are a separate root module rather than part of an apply a
compartment-scoped operator runs.

What this grants, and why there are two groups: the PAF compute and the
Autonomous Database each call Generative AI as themselves, so each needs its own
principal. Neither ever holds an API key.

| Principal    | Authenticates as   | Used by                                            |
| ------------ | ------------------ | -------------------------------------------------- |
| `paf` compute | Instance principal | PAF's `oci_instance_principal` LLM and embedding connections |
| ADB          | Resource principal | The Select AI profiles' `OCI$RESOURCE_PRINCIPAL` credential  |

```bash
python manage.py tf          # renders this root's terraform.tfvars
python manage.py cloud iam   # init + apply, in the tenancy home region
```

Terraform is driven through `manage.py`, which invokes it with `-chdir`. Running
it here by hand is what leaves the root without its rendered tfvars.
