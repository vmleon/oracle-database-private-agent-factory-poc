#!/bin/bash
#
# Agent iteration budget.
#
# PAF builds every Agent node with a 5-iteration executor budget, and the last
# iteration is reserved for the reply — four tool calls per turn, with no
# setting to change it. This raises the budget to 8 inside the running
# container, so a four-call recipe survives one failed call.
#
# Idempotent. Run after every image build; the change lives in the container
# filesystem, not the image.

set -euo pipefail

CONTAINER_NAME="paf-agent-factory"
INSTALL_BASE="/home/aaiuser/install/agent_factory"
PYTHON_BIN="$INSTALL_BASE/third_party/python3/bin/python3"
TARGET_FILE="$INSTALL_BASE/app/models/agentBuilder/steps/customSteps/AgentStep.py"
MANAGE_SCRIPT="$INSTALL_BASE/manage_app.sh"
ITERATIONS=8

echo "Setting MAX_AGENT_ITERATIONS=$ITERATIONS in $CONTAINER_NAME..."

podman exec -i "$CONTAINER_NAME" \
  env TARGET_FILE="$TARGET_FILE" ITERATIONS="$ITERATIONS" "$PYTHON_BIN" - <<'PY'
import os
import re
import shutil
import time
from pathlib import Path

target = Path(os.environ["TARGET_FILE"])
if not target.exists():
    raise SystemExit(f"Target file not found: {target}")

wanted = int(os.environ["ITERATIONS"])
content = target.read_text()
pattern = re.compile(r"^(\s*MAX_AGENT_ITERATIONS\s*=\s*)(\d+)\s*$", re.MULTILINE)
match = pattern.search(content)
if match is None:
    raise SystemExit("MAX_AGENT_ITERATIONS assignment not found in AgentStep.py")

current = int(match.group(2))
if current == wanted:
    print(f"MAX_AGENT_ITERATIONS is {wanted}.")
else:
    backup = target.with_name(f"{target.name}.bak.{int(time.time())}")
    shutil.copy2(target, backup)
    target.write_text(pattern.sub(match.group(1) + str(wanted), content, count=1))
    print(f"MAX_AGENT_ITERATIONS set to {wanted}. Backup: {backup}")
PY

echo "Validating the patched file..."
podman exec "$CONTAINER_NAME" "$PYTHON_BIN" -m py_compile "$TARGET_FILE"

echo "Restarting the PAF application..."
podman exec "$CONTAINER_NAME" /bin/bash "$MANAGE_SCRIPT"

echo "Done."
