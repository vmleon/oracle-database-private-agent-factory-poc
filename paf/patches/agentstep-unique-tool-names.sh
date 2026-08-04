#!/bin/bash
#
# PAF 26.4 hot-patch — per-node Agent tool names.
#
# Every Agent node's executable is named `agent_step`, and PAF's tool registry is
# name-keyed first-write-wins, so in a multi-agent flow every agent runs with the
# FIRST agent's tools (issues/01-multi-agent-tool-binding-collapses-to-first-agent.md).
# This rewrites AgentStep.py inside the running container so each node registers a
# unique tool name (and a distinguishable worker display name), then restarts the app.
#
# Idempotent — re-run after every fresh PAF install or image rebuild; the patch lives
# in the container filesystem, not in the image.

set -euo pipefail

CONTAINER_NAME="paf-agent-factory"
INSTALL_BASE="/home/aaiuser/install/agent_factory"
PYTHON_BIN="$INSTALL_BASE/third_party/python3/bin/python3"
TARGET_FILE="$INSTALL_BASE/app/models/agentBuilder/steps/customSteps/AgentStep.py"
MANAGE_SCRIPT="$INSTALL_BASE/manage_app.sh"

echo "Patching AgentStep per-node runtime tool and worker names inside $CONTAINER_NAME..."

podman exec -i "$CONTAINER_NAME" \
  env TARGET_FILE="$TARGET_FILE" "$PYTHON_BIN" - <<'PY'
import os
import shutil
import time
from pathlib import Path


def backup_and_write(target, original, content):
    if content == original:
        return False

    backup = target.with_name(f"{target.name}.bak.{int(time.time())}")
    shutil.copy2(target, backup)
    target.write_text(content)
    print(f"Patched {target}")
    print(f"Backup saved to {backup}")
    return True


target = Path(os.environ["TARGET_FILE"])
if not target.exists():
    raise SystemExit(f"Target file not found: {target}")

content = target.read_text()
original = content

if "import hashlib\n" not in content:
    import_anchor = "import logging\n"
    if import_anchor not in content:
        raise SystemExit("Could not find logging import anchor in AgentStep.py")
    content = content.replace(import_anchor, import_anchor + "import hashlib\n", 1)

method = (
    "    def _runtime_tool_name(self) -> str:\n"
    "        node_id = str(self.node.get(\"id\") or \"agent\").strip()\n"
    "        safe_node_id = \"\".join(\n"
    "            ch if ch.isalnum() else \"_\"\n"
    "            for ch in node_id\n"
    "        ).strip(\"_\") or \"agent\"\n"
    "        node_hash = hashlib.sha256(node_id.encode(\"utf-8\")).hexdigest()[:10]\n"
    "        return f\"agent_step_{safe_node_id[:40]}_{node_hash}\"\n"
    "\n"
)

if "def _runtime_tool_name(self) -> str:" not in content:
    class_anchor = (
        "class AgentStep(CustomStep):\n"
        "    category: NodeCategories = NodeCategories.Agents\n"
        "\n"
    )
    if class_anchor not in content:
        raise SystemExit("Could not find AgentStep class anchor")
    content = content.replace(class_anchor, class_anchor + method, 1)
else:
    content = content.replace(
        "hashlib.sha1(node_id.encode(\"utf-8\")).hexdigest()[:10]",
        "hashlib.sha256(node_id.encode(\"utf-8\")).hexdigest()[:10]",
        1,
    )

display_helpers = (
    "    def _node_hash_suffix(self) -> str:\n"
    "        node_id = str(self.node.get(\"id\") or \"agent\").strip()\n"
    "        return hashlib.sha256(node_id.encode(\"utf-8\")).hexdigest()[:6]\n"
    "\n"
    "    def _template_value(self, field_name: str, default: Any = None) -> Any:\n"
    "        try:\n"
    "            field = self.node[\"data\"][\"template\"].get(field_name, {})\n"
    "            if isinstance(field, dict):\n"
    "                return field.get(\"value\", default)\n"
    "        except Exception:\n"
    "            pass\n"
    "        return default\n"
    "\n"
    "    def _mcp_tool_context_label(self) -> str:\n"
    "        tools_nodes_ids = self._template_value(\"tools\", [])\n"
    "        if isinstance(tools_nodes_ids, str):\n"
    "            tools_nodes_ids = [tools_nodes_ids]\n"
    "        if not tools_nodes_ids:\n"
    "            return \"\"\n"
    "\n"
    "        labels = []\n"
    "        steps_classes = self.global_variables.get(\"steps_classes\", {})\n"
    "        for tool_node_id in tools_nodes_ids:\n"
    "            try:\n"
    "                step = steps_classes.get(tool_node_id)\n"
    "                tool_node = getattr(step, \"node\", None)\n"
    "                template = tool_node.get(\"data\", {}).get(\"template\", {})\n"
    "                server_source = template.get(\"serverSource\", {})\n"
    "                if not isinstance(server_source, dict):\n"
    "                    continue\n"
    "\n"
    "                selected_value = server_source.get(\"value\")\n"
    "                selected_label = \"\"\n"
    "                options = (\n"
    "                    server_source\n"
    "                    .get(\"componentProps\", {})\n"
    "                    .get(\"options\", [])\n"
    "                )\n"
    "                for option in options or []:\n"
    "                    if str(option.get(\"value\")) == str(selected_value):\n"
    "                        selected_label = str(option.get(\"label\") or \"\").strip()\n"
    "                        break\n"
    "                if not selected_label and selected_value not in (None, \"\"):\n"
    "                    selected_label = f\"MCP {selected_value}\"\n"
    "                if selected_label:\n"
    "                    labels.append(selected_label)\n"
    "            except Exception:\n"
    "                logging.debug(\n"
    "                    \"AgentStep: failed resolving MCP context for tool node %s\",\n"
    "                    tool_node_id,\n"
    "                    exc_info=True,\n"
    "                )\n"
    "\n"
    "        return \", \".join(dict.fromkeys(labels))\n"
    "\n"
    "    def _agent_display_name(self) -> str:\n"
    "        agent_description = str(\n"
    "            self._template_value(\"agent_description\", \"Agent\") or \"Agent\"\n"
    "        ).strip() or \"Agent\"\n"
    "        if agent_description != \"Agent\":\n"
    "            return agent_description\n"
    "\n"
    "        node_suffix = self._node_hash_suffix()\n"
    "        tool_context = self._mcp_tool_context_label()\n"
    "        if tool_context:\n"
    "            return f\"Agent {tool_context} ({node_suffix})\"\n"
    "        return f\"Agent ({node_suffix})\"\n"
    "\n"
)

if "def _agent_display_name(self) -> str:" not in content:
    runtime_method_end = method
    if runtime_method_end not in content:
        raise SystemExit("Could not find AgentStep runtime tool-name method")
    content = content.replace(runtime_method_end, runtime_method_end + display_helpers, 1)

create_tool_anchor = "    def _create_tool(self):\n"
if create_tool_anchor not in content:
    raise SystemExit("Could not find AgentStep._create_tool")

if "        tool_name = self._runtime_tool_name()\n" not in content:
    content = content.replace(
        create_tool_anchor,
        create_tool_anchor + "        tool_name = self._runtime_tool_name()\n",
        1,
    )

content = content.replace(
    "        @tool(description_mode=\"only_docstring\")\n"
    "        def agent_step(prompt: str, custom_instruction: str) -> str:\n",
    "        def agent_step(prompt: str, custom_instruction: str) -> str:\n",
    1,
)

if "        return tool(tool_name, description_mode=\"only_docstring\")(agent_step)\n" not in content:
    old_return = "        return agent_step\n"
    new_return = "        return tool(tool_name, description_mode=\"only_docstring\")(agent_step)\n"
    if old_return not in content:
        raise SystemExit("Could not find AgentStep tool return")
    content = content.replace(old_return, new_return, 1)

content = content.replace(
    "        try:\n"
    "            agent_description = self.node[\"data\"][\"template\"][\"agent_description\"][\"value\"]\n"
    "        except Exception:\n"
    "            agent_description = \"Agent\"\n",
    "        agent_description = self._agent_display_name()\n",
    1,
)

content = content.replace(
    "                agent_description = self.node[\"data\"][\"template\"][\"agent_description\"][\"value\"]\n",
    "                agent_description = self._agent_display_name()\n",
    1,
)

content = content.replace(
    "                            node_name = node.node[\"data\"][\"template\"][\"agent_description\"][\"value\"]\n",
    "                            node_name = node._agent_display_name()\n",
    1,
)

content = content.replace(
    "                                    while candidate in used_names:\n"
    "                                        candidate = f\"{base_name} ({uuid4().hex[:6]})\"\n",
    "                                    suffix = getattr(node, \"_node_hash_suffix\", lambda: uuid4().hex[:6])()\n"
    "                                    while candidate in used_names:\n"
    "                                        next_candidate = f\"{base_name} ({suffix})\"\n"
    "                                        if next_candidate == candidate:\n"
    "                                            next_candidate = (\n"
    "                                                f\"{base_name} ({suffix}-{len(used_names)})\"\n"
    "                                            )\n"
    "                                        candidate = next_candidate\n",
    1,
)

old_response_selection = '''            if sub_agents:
                # For manager/worker orchestration, prefer the latest worker tool_result content
                # so downstream flow nodes (Parser/TypeConvert/etc.) receive delegated output.
                try:
                    for message in reversed(conversation.get_messages()):
                        tool_result = getattr(message, "tool_result", None)
                        tool_content = getattr(tool_result, "content", None) if tool_result else None
                        if isinstance(tool_content, str) and tool_content.strip():
                            reply_content = tool_content
                            break
                except Exception:
                    logging.exception("AgentStep: failed to extract delegated sub-agent tool_result content")
'''

new_response_selection = '''            if sub_agents:
                # For manager/worker orchestration, preserve the manager's final
                # user-facing response instead of returning the last worker result.
                try:
                    manager_user_content = None
                    for message in reversed(conversation.get_messages()):
                        for tool_request in getattr(message, "tool_requests", None) or []:
                            if getattr(tool_request, "name", None) != "talk_to_user":
                                continue
                            tool_args = getattr(tool_request, "args", {}) or {}
                            tool_text = (
                                tool_args.get("text")
                                if isinstance(tool_args, dict)
                                else None
                            )
                            if isinstance(tool_text, str) and tool_text.strip():
                                manager_user_content = tool_text
                                break
                        if manager_user_content:
                            break

                    if manager_user_content:
                        reply_content = manager_user_content

                    if not isinstance(reply_content, str) or not reply_content.strip():
                        # Fallback for non-chat agent flows that only produce a
                        # delegated worker tool result.
                        for message in reversed(conversation.get_messages()):
                            tool_result = getattr(message, "tool_result", None)
                            tool_content = (
                                getattr(tool_result, "content", None)
                                if tool_result
                                else None
                            )
                            if isinstance(tool_content, str) and tool_content.strip():
                                reply_content = tool_content
                                break
                except Exception:
                    logging.exception("AgentStep: failed to select manager/worker response")
'''

if old_response_selection in content:
    content = content.replace(old_response_selection, new_response_selection, 1)
elif "manager_user_content = None" not in content:
    raise SystemExit("Could not find AgentStep manager/worker response selection block")

if backup_and_write(target, original, content):
    print("AgentStep runtime tool-name and worker-name patch applied.")
else:
    print("AgentStep runtime tool-name and worker-name patch already applied.")
PY

echo "Validating patched Python file..."
podman exec "$CONTAINER_NAME" "$PYTHON_BIN" -m py_compile "$TARGET_FILE"

echo "Running manage_app.sh..."
podman exec "$CONTAINER_NAME" /bin/bash "$MANAGE_SCRIPT"

echo "Done!"
