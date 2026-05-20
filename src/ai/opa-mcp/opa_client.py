"""Thin httpx wrapper of OPA's data API.

OPA exposes every Rego rule under `/v1/data/<package>/<rule>`. We POST
the input wrapped in `{"input": ...}` and OPA returns
`{"result": <rule value>}`. This wrapper trims the envelope so the
MCP tools return the rule value directly.

Rules return `undefined` when no clause matches. By default the
result key is then absent — we map that to `None`.

OPA URL is `$OPA_URL` (default http://opa:8181) so the same client
works in compose (service-DNS) and ad-hoc local runs.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

OPA_URL = os.getenv("OPA_URL", "http://opa:8181").rstrip("/")
_TIMEOUT = float(os.getenv("OPA_TIMEOUT", "5"))


class OPAError(RuntimeError):
    """Raised when OPA returns a non-2xx response."""


def eval_rule(path: str, input_doc: dict[str, Any] | None = None) -> Any:
    """Evaluate one rule and return the unwrapped result.

    `path` is the dotted Rego path relative to `data`, e.g.
    `"decisioning.eligibility"` for `data.decisioning.eligibility`.
    A trailing rule (e.g. `"decisioning.pricing.quote"`) is fine too.
    """
    url = f"{OPA_URL}/v1/data/{path.replace('.', '/')}"
    body = {"input": input_doc or {}}
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, json=body)
    if resp.status_code >= 400:
        raise OPAError(f"OPA {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("result")


def policy_versions() -> list[dict[str, Any]]:
    """List the loaded Rego modules + their digests. Useful for audit."""
    url = f"{OPA_URL}/v1/policies"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url)
    if resp.status_code >= 400:
        raise OPAError(f"OPA {resp.status_code}: {resp.text[:200]}")
    payload = resp.json().get("result", [])
    return [
        {"id": entry.get("id"), "raw_bytes": len(entry.get("raw", "") or "")}
        for entry in payload
    ]
