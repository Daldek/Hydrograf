"""
The pages of the public service and what the front end needs to know of it (ADR-084).

nginx passes every page (`/`, `*.html`, `/admin`, `/instrukcja/`) to the API, so that
pages count against the request limit and in the day's totals like the API routes
(Nogat DEV-15.9, DEV-15.11; api/traffic.py). The API then lets nginx send the page's
file itself: the answer names it in `X-Accel-Redirect` under nginx's internal location
`/_site/`. The regulamin (DEV-15.7) is filled by the API (core/terms.py) and sent from
memory.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from core.attribution import CATCHMENT, LAYER_KINDS, PMAXTP, data_lines, merge
from core.config import get_settings
from core.data_sources import read_data_sources
from core.errors import NotFoundError
from core.terms import URL, current_terms
from models.schemas import LayerLines, TermsInfo

# nginx's internal location of the front end's files
SITE = "/_site/"

pages_router = APIRouter(include_in_schema=False)
router = APIRouter()


@pages_router.api_route("/index.html", methods=["GET", "HEAD"])
@pages_router.api_route("/admin.html", methods=["GET", "HEAD"])
@pages_router.api_route("/instrukcja/index.html", methods=["GET", "HEAD"])
def page(request: Request) -> Response:
    """Let nginx send the file of a page of the front end (X-Accel-Redirect)."""
    return Response(headers={"X-Accel-Redirect": SITE + request.url.path[1:]})


@pages_router.api_route(URL, methods=["GET", "HEAD"])
def regulamin() -> HTMLResponse:
    """Send the regulamin of the deployment; 404 without `[nogat.operator]`."""
    terms = current_terms()
    if terms is None:
        raise NotFoundError("terms_not_configured", reason="terms_not_configured")
    return HTMLResponse(terms.page, headers={"Cache-Control": "no-cache"})


@router.get("/terms", response_model=TermsInfo)
def terms_info() -> TermsInfo:
    """
    Return the address of the regulamin, the operator's e-mail and the service's lines.

    The address and the e-mail are null when the deployment names no operator
    (`[nogat.operator]` of the nogat.toml of NOGAT_CONFIG): the front end then shows no
    footer link and no e-mail under „Zgłoś uwagę”. `attribution` and `terms_notice`
    are every line of the service's data (core/attribution.py): those of the PMAXTP
    data every hydrograph is made with, then G and SG of the GUGiK and SoilGrids data
    of the instance, which the welcome window shows in full (Nogat DEV-20.5).
    `layers` gives the lines of each kind of data of the map's layers, which the strip
    of the view shows while a layer of the kind is on the map.
    """
    terms = current_terms()
    dates = read_data_sources(get_settings().frontend_data_dir)
    lines = merge([PMAXTP, data_lines(CATCHMENT, dates)])
    layers = {}
    for kind, uses in LAYER_KINDS.items():
        layer = data_lines(uses, dates)
        layers[kind] = LayerLines(
            attribution=list(layer.attribution), terms_notice=list(layer.terms_notice)
        )
    return TermsInfo(
        url=URL if terms else None,
        operator_email=terms.operator_email if terms else None,
        attribution=list(lines.attribution),
        terms_notice=list(lines.terms_notice),
        layers=layers,
    )


@router.post("/downloads", status_code=204)
def count_download() -> Response:
    """
    Count one file the interface saved (the daily total `downloads`, DEV-15.11).

    The interface builds its files (hietogram CSV and JSON, PMAXTP points, hand-off)
    in the browser and reports each one here; api/traffic.py adds the answer to the
    day's totals. Nothing else is stored.
    """
    return Response(status_code=204)
