# Local deployment

End-to-end local deployment of the Decisioning Engine PoC using rootless podman.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the design; this file is the runbook.

## Status

This is **D1** of the v0 milestone. Only the database tier is up. PAF, Ollama, OPA, OCR, the Spring Boot backend, and the Angular UIs land in subsequent PRs.

After running the commands below, you have:

- Oracle Database Free 26ai running on `localhost:1521` (service `FREEPDB1`).
- Four schema users created: `APP`, `REPORTING`, `AGENT_TOOLS`, `AGENT_FACTORY`.

## Prerequisites

Install these on the host once.

| Tool               | macOS                                                                | Oracle Linux 8                                     |
| ------------------ | -------------------------------------------------------------------- | -------------------------------------------------- |
| `podman`           | `brew install podman && podman machine init && podman machine start` | `dnf install -y podman`                            |
| `podman-compose`   | `brew install podman-compose`                                        | `pip install podman-compose`                       |
| `python` 3.11+     | `brew install python@3.12`                                           | `dnf install -y python3.12`                        |
| `ansible-playbook` | `brew install ansible`                                               | `dnf install -y ansible-core`                      |
| `liquibase`        | `brew install liquibase`                                             | Download from <https://www.liquibase.org/download> |

`manage.py setup local` checks for all of these and prints install hints if any are missing.

You also need network access to pull:

- `container-registry.oracle.com/database/free:latest` (Oracle Database Free 26ai image; ~9 GB).
- `ojdbc11` JDBC driver from Maven Central (the Ansible role caches it to `~/.cache/paf-poc/liquibase-libs/`).

## Quickstart

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python manage.py setup local       # writes .env
python manage.py local up          # podman compose up + ansible → liquibase
python manage.py info              # prints JDBC URL + service users
```

## Day-2

| Command                                        | What it does                                                                          |
| ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| `python manage.py local up`                    | Idempotent: starts containers if down, runs Liquibase if any pending changesets.      |
| `python manage.py local provision`             | Re-runs Liquibase + grants only (no podman restart). Use after editing the changelog. |
| `python manage.py local logs oracle-free-26ai` | Tails the Oracle DB container logs.                                                   |
| `python manage.py local down`                  | Stops and removes containers. State persists in the `paf-oradata` volume.             |
| `python manage.py local down --purge`          | Also removes the volume. Next `local up` starts with a fresh DB.                      |

## Verifying

Connect with `sqlcl` (or any JDBC client):

```bash
sql SYSTEM/<password>@localhost:1521/FREEPDB1
```

Inside SQLcl:

```sql
SELECT username
  FROM dba_users
 WHERE username IN ('APP', 'REPORTING', 'AGENT_TOOLS', 'AGENT_FACTORY')
 ORDER BY username;
```

Expected: four rows.

## Troubleshooting

**Podman: "no space left on device" during image pull.**
Re-point `TMPDIR` to a partition with at least 15 GB free, then `podman system reset` and retry:

```bash
export TMPDIR=/var/tmp
mkdir -p "$TMPDIR"
```

**Oracle container never becomes healthy.**
The Oracle Database Free image initialises on first boot and can take 3–5 minutes. Tail the logs:

```bash
python manage.py local logs oracle-free-26ai
```

Look for `DATABASE IS READY TO USE!`.

**`liquibase: command not found` when running `local up`.**
Re-run `python manage.py setup local` to surface the prereq check, then install Liquibase per the table above.

**Liquibase update fails with `ORA-01017: invalid username/password`.**
Your `.env`'s `DB_PASSWORD` no longer matches the password baked into the running container. Either edit `.env` to match the running container, or `local down --purge` and re-`local up` to start fresh.

**Port 1521 already in use.**
Stop any existing Oracle client on the host, or edit `deploy/podman/compose.local.yml` to remap the port (e.g. `15210:1521`) and update `DB_PORT` in `.env`.
