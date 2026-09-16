"""One signed-in customer, one thread, driven the way the React SPA drives it.

The bench goes through the Spring backend rather than PAF's integration
endpoint, so `Envelope.sanitize`, `Envelope.stripMarkers`, session resolution,
the apology retry and `chat_message` persistence are all on the path.

Replies are read from `GET /v1/chat/history` rather than the SSE channel: the
assertions want the persisted thread anyway, and an `EventSource` in pytest
buys nothing but flakiness. The text that comes back is already what the
customer sees, because the backend stores the post-`stripMarkers` reply.
"""
from __future__ import annotations

import os
import time

import requests

# The load balancer. Reachable from the ops bastion, which is also the only
# host that reaches the private-endpoint database the assertions read.
BACKEND_BASE = os.getenv("BACKEND_BASE", "").rstrip("/")

# The bench is deliberately slow and strictly serial: the target is a
# single-instance dev deployment sharing one Generative AI endpoint, and
# breaking it by volume proves nothing.
PACE_SECONDS = float(os.getenv("PACE_SECONDS", "4"))
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "3"))
TURN_TIMEOUT = float(os.getenv("TURN_TIMEOUT", "300"))

# The fixed fail-secure text the flow returns when get_context cannot resolve
# the session. A turn that ends here is the boundary holding, or a crash inside
# a deterministic node — the suites distinguish the two by what else they see.
APOLOGY = ("Sorry — we couldn't process your application right now. "
           "Please try again in a moment.")


class TurnTimeout(RuntimeError):
    """A turn produced no agent reply inside TURN_TIMEOUT."""


class Conversation:
    """A logged-in customer. One at a time, by construction."""

    def __init__(self, customer_id: int, *, ca: str, base: str = "") -> None:
        self.base = (base or BACKEND_BASE).rstrip("/")
        self.http = requests.Session()
        # The listener's certificate is self-signed and names its own address,
        # so it is the trust anchor as well as the identity being checked.
        self.http.verify = ca
        response = self.http.post(f"{self.base}/v1/login",
                                  json={"customerId": customer_id}, timeout=30)
        response.raise_for_status()
        body = response.json()
        self.token: str = body["sessionToken"]
        self.customer_id = int(body["customerId"])
        self.application_id = body.get("applicationId")
        self.turns = 0
        self.said: list[str] = []
        self.heard: list[str] = []

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Session-Token": self.token}

    def post(self, text: str) -> requests.Response:
        """Send a turn without waiting for the reply. Returns the raw response
        so a case can assert on the status — a revoked token is a 401 here, and
        no turn runs at all."""
        return self.http.post(f"{self.base}/v1/chat", json={"message": text},
                              headers=self.headers, timeout=30)

    def say(self, text: str) -> str:
        """Post a turn, wait for the agent's reply, return it as the customer
        reads it. Sleeps PACE_SECONDS afterwards. Raises on timeout."""
        before = len(self._agent_bodies())
        self.post(text).raise_for_status()
        self.said.append(text)
        deadline = time.monotonic() + TURN_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
            replies = self._agent_bodies()
            if len(replies) > before:
                self.turns += 1
                self.heard.append(replies[-1])
                time.sleep(PACE_SECONDS)
                return replies[-1]
        raise TurnTimeout(
            f"no agent reply within {TURN_TIMEOUT:.0f}s for {text!r} "
            f"(customer {self.customer_id})"
        )

    def raw_history(self) -> list[dict]:
        """GET /v1/chat/history — sender, body, createdAt, as persisted."""
        response = self.http.get(f"{self.base}/v1/chat/history",
                                 headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def logout(self) -> None:
        """Revoke the session. Idempotent, and safe on a token already gone."""
        try:
            self.http.post(f"{self.base}/v1/logout", headers=self.headers, timeout=30)
        except requests.RequestException:
            pass

    def _agent_bodies(self) -> list[str]:
        return [m["body"] for m in self.raw_history() if m["sender"] == "AGENT"]


def customer_ids(base: str, ca: str) -> dict[str, int]:
    """Name -> customer_id from the login dropdown. Surrogate keys are IDENTITY
    values and are never hardcoded, so every persona is addressed by full_name."""
    response = requests.get(f"{base.rstrip('/')}/v1/customers", verify=ca, timeout=30)
    response.raise_for_status()
    return {c["name"]: int(c["customerId"]) for c in response.json()}
