# Oracle Database Private Agent Factory — Decisioning Engine PoC

A bank-agnostic proof of concept showing **Oracle AI Database 26ai + Private Agent Factory** running an end-to-end retail loan decisioning flow with full observability (per-tool audit, Blockchain Tables, parameter history).

Two deployment options, same source tree:

- **Local** — rootless podman on a laptop or LAN. See [`LOCAL.md`](LOCAL.md).
- **Cloud** — OCI Terraform + Ansible (5 computes + ADB + LB). See [`CLOUD.md`](CLOUD.md) _(not yet implemented)_.

## Documentation

- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture, components, PAF Hybrid runtime mapping, source layout, locked decisions.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — deployment plan, `manage.py` command surface, Liquibase strategy, v0 milestone.
- [`docs/PAF.md`](docs/PAF.md) — Oracle PAF practical study guide (in-repo reference).
- [`docs/decisioning-engine-use-case.md`](docs/decisioning-engine-use-case.md) — the credit-decisioning use case the PoC implements.

## Quickstart (local)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py setup local
python manage.py local up
python manage.py info
```

Detailed prerequisites, day-2 commands, and troubleshooting in [`LOCAL.md`](LOCAL.md).

## Current status

**D1 (database tier only)** of the v0 milestone is in place: Oracle Database Free 26ai running locally with the four-schema layout (`APP`, `REPORTING`, `AGENT_TOOLS`, `AGENT_FACTORY`). PAF, Ollama, OPA, OCR, the Spring Boot backend, and the Angular UIs are queued for subsequent PRs.
