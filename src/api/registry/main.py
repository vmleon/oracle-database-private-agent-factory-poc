"""Company Registry — synthetic employer / company lookup service.

Registered with PAF as an HTTP datasource for CHAT_WORKFLOW. One operation:
verify_employer(name) → CompanyRecord. Data is loaded from data.json on
startup; no real bureau dependency.

Names in data.json deliberately match the employers seeded by Liquibase
010-seed-synthetic so the test-bench scenarios resolve to the expected
responses:

  - Scenario  1 / smoke (Alice, Acme Tech Ltd)        → active
  - Scenario  2 (David, Acme Tech Ltd)                → active
  - Scenario  3 (Eva, Globex Inc)                     → active
  - Scenario  6 (Frank, Initech)                      → active
  - Scenario  7 (Grace, Stark Industries)             → active
  - Scenario  8 (Henry, Wayne Enterprises)            → active
  - Scenario  9 (Iris, Soylent Corp)                  → active
  - Scenario 27 (Jane, Atlantis Innovations Ltd)      → NOT in registry
  - Scenario 28 (Kyle, Phoenix Holdings Ltd)          → dormant
  - Scenario 29 / self-employed (Bob Consulting LLC)  → active

Unknown employers are returned as 200 OK with `registered=false` and
`trading_status='unknown'` rather than 404, so the agent folds the
signal into the recommendation packet as evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import os

from fastapi import FastAPI, Query
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field

DATA_PATH = Path(__file__).parent / "data.json"

app = FastAPI(
    title="Company Registry",
    description=(
        "Synthetic employer / company registry. PAF HTTP datasource for "
        "CHAT_WORKFLOW. One lookup per loan application."
    ),
    version="0.1.0",
    # PAF's OpenAPI importer rejects specs without a `servers` block ("Missing
    # servers"). The compose-internal URL is the only one PAF can reach from
    # the project network; cloud deployments will override the spec at import
    # time or run an out-of-band server. Hardcoded to keep the POC simple.
    # PAF reads this block to learn where to call the API, so it has to name a
    # host the caller can resolve. The compose service name only exists locally;
    # the cloud tier overrides it with its VCN address.
    servers=[{"url": os.getenv("REGISTRY_PUBLIC_URL", "http://registry-api:8600"),
              "description": "registry"}],
)


def _openapi_with_security() -> dict:
    """Inject a no-op security scheme so PAF's importer accepts the spec.

    PAF rejects specs without a `components.securitySchemes` block ("Could
    not find security definitions"), but the service itself has no auth.
    OpenAPI 3.x has no formal 'none' / 'anonymous' type, so we declare a
    placeholder apiKey scheme that the service ignores at runtime — when
    configuring the datasource in PAF pick `Direct` (or send any value as
    the header; the service drops it).
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        servers=app.servers,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "NoAuthApiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Stub registry has no real auth — placeholder for PAF's importer.",
        }
    }
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_security


TradingStatus = Literal["active", "dormant", "dissolved", "unknown"]


class CompanyRecord(BaseModel):
    name: str = Field(..., description="Company name as queried.")
    registered: bool = Field(
        ..., description="True if the company exists in the registry."
    )
    trading_status: TradingStatus = Field(
        ...,
        description="Trading status. 'unknown' is returned when not registered.",
    )
    sector: str | None = Field(None, description="Industry sector.")
    registered_address: str | None = Field(None, description="Registered office address.")
    last_filed_year: int | None = Field(
        None, description="Year of the most recent statutory filing."
    )


def _load_registry() -> dict[str, dict]:
    raw = json.loads(DATA_PATH.read_text())
    return {entry["name"].lower(): entry for entry in raw}


REGISTRY = _load_registry()


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/v1/companies/verify",
    response_model=CompanyRecord,
    summary="Verify a company by name",
    description=(
        "Case-insensitive exact-match lookup against the synthetic registry. "
        "If the name isn't present, responds 200 with registered=false and "
        "trading_status='unknown'."
    ),
    operation_id="verify_employer",
)
def verify_employer(
    name: str = Query(
        ...,
        min_length=1,
        description="Company name (case-insensitive exact match).",
        examples=["Acme Tech Ltd"],
    ),
) -> CompanyRecord:
    hit = REGISTRY.get(name.lower())
    if hit is None:
        return CompanyRecord(name=name, registered=False, trading_status="unknown")
    return CompanyRecord(
        name=name,
        registered=True,
        trading_status=hit["trading_status"],
        sector=hit.get("sector"),
        registered_address=hit.get("registered_address"),
        last_filed_year=hit.get("last_filed_year"),
    )
