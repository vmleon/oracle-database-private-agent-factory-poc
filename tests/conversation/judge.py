"""The opt-in rubric judge.

Off by default, behind the `judge` marker, because it is non-deterministic and
costs a model call per exchange — exactly the cost the rest of the bench is
avoiding. The deterministic signals in `quality.py` come first and carry the
suite; this is for the reading a pattern cannot give.

It asks the deployment's own generation model, through the instance principal
the ops bastion already holds, so no key material is involved.
"""
from __future__ import annotations

import json
import os
import re

RUBRIC = (
    "answers_the_question",
    "moves_the_application_forward",
    "natural",
    "does_not_repeat",
)

PROMPT = """You are grading one exchange between a bank's loan assistant and a customer.

Customer said:
{customer}

Assistant replied:
{reply}

Score each of these from 1 (bad) to 5 (good):
- answers_the_question: does the reply address what the customer actually asked?
- moves_the_application_forward: does it get the application closer to a decision?
- natural: does it read like a person, not a form?
- does_not_repeat: does it say something new rather than restating the last turn?

Reply with JSON only, one key per criterion, integer values. No prose."""


def available() -> str | None:
    """The reason the judge cannot run, or None when it can."""
    try:
        import oci  # noqa: F401
    except ImportError:
        return ("the oci SDK is not installed in the bastion's test venv — add "
                "it to deploy/ansible/ops/roles/opstools and run "
                "`python manage.py cloud redeploy ops`")
    for key in ("GENAI_ENDPOINT", "GENAI_MODEL", "OCI_COMPARTMENT_OCID"):
        if not os.getenv(key):
            return f"{key} is not set"
    return None


def score(customer: str, reply: str) -> dict[str, int]:
    """One exchange, scored on the rubric. Raises if the model's answer is not
    JSON — a judge that silently returns nothing is worse than no judge."""
    import oci

    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    client = oci.generative_ai_inference.GenerativeAiInferenceClient(
        config={}, signer=signer,
        service_endpoint=os.environ["GENAI_ENDPOINT"],
    )
    content = oci.generative_ai_inference.models.TextContent(
        text=PROMPT.format(customer=customer, reply=reply))
    message = oci.generative_ai_inference.models.Message(role="USER", content=[content])
    request = oci.generative_ai_inference.models.ChatDetails(
        compartment_id=os.environ["OCI_COMPARTMENT_OCID"],
        serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
            model_id=os.environ["GENAI_MODEL"]),
        chat_request=oci.generative_ai_inference.models.GenericChatRequest(
            api_format="GENERIC", messages=[message],
            max_tokens=200, temperature=0, is_stream=False),
    )
    response = client.chat(request)
    text = _text_of(response)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"the judge did not return JSON: {text!r}")
    raw = json.loads(match.group(0))
    return {key: int(raw.get(key, 0)) for key in RUBRIC}


def _text_of(response) -> str:
    choices = response.data.chat_response.choices
    parts = choices[0].message.content
    return "".join(getattr(part, "text", "") for part in parts)
