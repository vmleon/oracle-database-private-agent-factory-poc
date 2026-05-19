# Local deployment

End-to-end local deployment of the Decisioning Engine PoC using rootless podman.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the design; this file is the runbook.

## Status

Only the database tier is currently up. PAF, Ollama, OPA, OCR, the Spring Boot backend, and the Angular UIs land in subsequent PRs.

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

## Optional: Ollama on a LAN GPU host (e.g. NVIDIA DGX Spark)

If your laptop can't run `llama3.3:70b-instruct-q4_K_M` (~55–60 GB resident with `bge-m3`), offload Ollama to a LAN-reachable GPU box and point `.env` at it. Steps below target a DGX Spark but apply to any NVIDIA host with a container runtime.

### On the GPU host

Prereqs:

- NVIDIA driver installed (`nvidia-smi` works).
- `podman` (or `docker`) with the NVIDIA Container Toolkit configured.

Start Ollama as a container, bound to all interfaces so the laptop can reach it:

```bash
podman run -d --name ollama \
  --device nvidia.com/gpu=all \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  --restart unless-stopped \
  docker.io/ollama/ollama:latest
```

(For `docker`, swap `--device nvidia.com/gpu=all` for `--gpus all`.)

Pull both models inside the running container:

```bash
podman exec -it ollama ollama pull llama3.3:70b-instruct-q4_K_M
podman exec -it ollama ollama pull bge-m3
```

First pull is ~40 GB (llama3.3) + ~1.2 GB (bge-m3); allow time and disk.

Open port `11434` only to the laptop's IP — Ollama has no auth:

```bash
# Oracle Linux 8 example
firewall-cmd --add-rich-rule="rule family=ipv4 source address=<LAPTOP_IP> port port=11434 protocol=tcp accept" --permanent
firewall-cmd --reload
```

### From the laptop

Verify reachability:

```bash
curl http://<GPU_HOST>:11434/api/tags
```

Should list both `llama3.3:70b-instruct-q4_K_M` and `bge-m3`.

Re-run setup and pick the LAN host when prompted:

```bash
python manage.py setup local
# Ollama host: <GPU_HOST>
# Ollama port: 11434
```

Or edit `.env` directly:

```
OLLAMA_HOST=<GPU_HOST>
OLLAMA_PORT=11434
```

Then `python manage.py local up` as usual — PAF and Select AI will resolve `OLLAMA_HOST` to the GPU box.

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
