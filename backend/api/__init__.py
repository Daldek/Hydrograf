"""REST API of Hydrograf: ``/api/v1`` (ADR-091)."""

from typing import Final

# The base of the API's first major: every route of a command, the server document,
# the jobs, the OpenAPI document and the GUI's own routes are below it
API_BASE: Final = "/api/v1"
