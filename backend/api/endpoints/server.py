"""
What this server serves, ``GET /api/v1/server`` (``nogat-server/1``, AGI-6.7, ADR-091).

One entry for Hydrograf: its version, its API's major and base (``{"1": "/api/v1"}``),
its capabilities in its own words (the groups of its catalog, the catalog itself and
the jobs), the address of its GUI (the deployment's ``[nogat] gui`` table names it,
else ``/`` on this host), its regulamin with its version where the deployment names
an operator, and the lines of the providers of its data. Latarnik and Goniec read it
to find the API; a GUI finds its own API base here.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import API_BASE
from api.catalog import COMMANDS
from api.endpoints.site import service_lines
from api.envelope import TOOL
from core.config import deployment_gui, get_settings
from core.database import get_db
from core.terms import URL, current_terms
from core.version import get_version

router = APIRouter()

SERVER_SCHEMA = "nogat-server/1"


def capabilities() -> list[str]:
    """Return what the server serves, in its own words.

    The groups of the catalog's commands, in the catalog's order, but the catalog's
    own (``commands``), then ``catalog`` and ``jobs``.
    """
    groups = dict.fromkeys(command.name.split()[0] for command in COMMANDS)
    groups.pop("commands", None)
    return [*groups, "catalog", "jobs"]


class ServerTerms(BaseModel):
    """The regulamin the service serves and its version."""

    url: str = Field(..., description="Its address on this host")
    version: str = Field(..., description="Its version, e.g. 1.1")


class ServerService(BaseModel):
    """Hydrograf's entry in ``nogat-server/1``."""

    tool: str = Field(TOOL, description="`hydrograf`")
    version: str = Field(..., description="The version of Hydrograf")
    api: dict[str, str] = Field(..., description='`{"1": "/api/v1"}`')
    capabilities: list[str] = Field(..., description="What the server serves")
    gui: str = Field(..., description="The address of its GUI")
    terms: ServerTerms | None = Field(
        None, description="Its regulamin, where the deployment names an operator"
    )
    attribution: list[str] = Field(
        ..., description="The attribution lines of its data's providers (DEV-20.6)"
    )
    terms_notice: list[str] = Field(
        ..., description="The terms lines of the same providers (DEV-20.7)"
    )


class ServerDocument(BaseModel):
    """What this server serves, ``nogat-server/1`` (AGI-6.7)."""

    schema_: str = Field(SERVER_SCHEMA, alias="schema", description="`nogat-server/1`")
    services: list[ServerService] = Field(..., description="Hydrograf alone")


def server_document(db: Session) -> dict[str, Any]:
    """Return the document ``nogat-server/1`` of this server."""
    lines = service_lines(db)
    service: dict[str, Any] = {
        "tool": TOOL,
        "version": get_version(),
        "api": {"1": API_BASE},
        "capabilities": capabilities(),
        "gui": deployment_gui(get_settings()).get(TOOL) or "/",
    }
    terms = current_terms()
    if terms is not None:
        service["terms"] = {"url": URL, "version": terms.version}
    service["attribution"] = list(lines.attribution)
    service["terms_notice"] = list(lines.terms_notice)
    return {"schema": SERVER_SCHEMA, "services": [service]}


@router.get(
    "/server",
    response_model=ServerDocument,
    response_model_exclude_none=True,
    summary="Describe what this server serves.",
    description=(
        "`nogat-server/1`: Hydrograf's version, its API's base, its capabilities, its "
        "GUI, its regulamin and its providers' lines. The first request of a client "
        "or a proxy that does not know this server."
    ),
)
def server(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Answer ``nogat-server/1`` (see the module)."""
    return server_document(db)
