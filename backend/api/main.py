"""
FastAPI application entry point.

The API is ``/api/v1`` (ADR-091): one route per command of the catalog
(``api.endpoints.commands``), the server document, the jobs of the long commands, the
OpenAPI document and the GUI's own routes (regulamin, feedback, downloads, the
deployment's GUIs and base maps) and admin routes. The map tiles stay at
``/api/tiles/`` (nginx's tile proxy of the GUI), the pages and ``/health`` at the root.
"""

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api import API_BASE
from api.endpoints import (
    admin,
    basemaps,
    commands,
    feedback,
    gui,
    health,
    jobs,
    server,
    site,
    tiles,
)
from api.errors import (
    install_error_handlers,
    install_openapi,
    operation_id,
    problem_responses,
)
from api.jobs import JobStore
from api.traffic import Traffic, keep_traffic, limit_and_count
from core import hydrolog_notices
from core.basemaps import current_basemaps
from core.catchment_graph import loaded_catchment_graph
from core.config import get_settings, state_dir
from core.database import get_db_session
from core.errors import HydrografError
from core.nogat_logging import AccessLog, ServerLog
from core.terms import current_terms
from core.version import get_version

settings = get_settings()
logger = logging.getLogger(__name__)

# The access, application and lifecycle logs of Nogat DEV-12.4 to DEV-12.9, files of
# <state_dir>/hydrograf/logs deleted after 14 days; standard error gets only the
# lifecycle records and the errors reduced to their type
log = ServerLog("hydrograf", get_version(), state_dir(settings) / "hydrograf" / "logs")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    Starts the logs with a summary of the settings (scalars only: no secret, admin
    key, database URL or operator's details), then reads the base maps of the
    deployment (ADR-089): a wrong setting stops the start, its error document, which
    names the option and the value, the last line of standard error. It installs the
    hook that turns Hydrolog's warnings into the hydrograph's notices, ends the jobs a
    previous process left active (``interrupted``, ADR-091), starts loading the
    in-memory catchment graph, fills the regulamin of the deployment and keeps the
    request limit and the daily totals (ADR-084), whose last totals it stores at
    shutdown, before the logs stop.
    """
    # First: from here the warnings and errors of the process go to the app log. The
    # summary reads no file, so that nothing is printed before the log starts
    log.start(
        {
            "request_limit": settings.hydrograf_request_limit,
            "request_window_s": settings.hydrograf_request_window,
            "data_dir": settings.hydrograf_data_dir,
            "dem_dir": settings.dem_dir,
            "cors_origins": settings.cors_origins,
            "nogat_config": bool(settings.nogat_config),
        }
    )
    try:
        current_basemaps()
    except HydrografError as error:
        log.stop()
        document = json.dumps(
            error.document(), ensure_ascii=False, separators=(",", ":")
        )
        print(document, file=sys.stderr, flush=True)
        raise
    # Hydrolog's warnings of a hydrograph also become the notices of its response
    # (E5b-06): the hook goes in after the log, whose captureWarnings replaces
    # warnings.showwarning, and passes every warning on to it
    hydrolog_notices.install()
    app.state.jobs.interrupt_previous()

    # Start loading the catchment graph now rather than at the first request. It
    # loads in a thread of its own, and until it is loaded the requests that need it
    # answer 503 catchment_graph_unavailable at once (E5b-01); requests start a load
    # again when the network in the database changes
    try:
        with get_db_session() as db:
            loaded_catchment_graph(db)
    except Exception as e:
        logger.warning("Catchment graph load not started: %s", e)

    current_terms()
    traffic: Traffic = app.state.traffic
    keeper = asyncio.create_task(keep_traffic(traffic))
    yield
    keeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await keeper
    traffic.store()
    log.stop()


app = FastAPI(
    title="Hydrograf API",
    description=(
        "Hydrological analysis system: watershed delineation, catchment parameters, "
        "design depths and design hydrographs in Poland. Every command answers the "
        "envelope `hydrograf-result/1`; a long one runs as a job (`POST /jobs`, "
        "`nogat-job/1`). The catalog is `GET /commands/list` and `GET "
        "/commands/schema`, the server's description `GET /server`. Errors are "
        "`application/problem+json` with a code of the shared Nogat error registry; "
        "texts follow `Accept-Language` (English by default, `pl` for Polish)."
    ),
    version=get_version(),
    lifespan=lifespan,
    openapi_url=f"{API_BASE}/openapi.json",
    generate_unique_id_function=operation_id,
)
install_error_handlers(app)
install_openapi(app)

# CORS middleware - origins from environment variable
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Accept-Language", "X-Admin-Key"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

# The request limit and the daily totals of this process (ADR-084)
app.state.traffic = Traffic(settings)
app.middleware("http")(limit_and_count)
# The jobs of the long commands, the active ones listed in the state directory
app.state.jobs = JobStore(state_dir(settings) / "hydrograf" / "jobs.json")
# Outermost, so the refusals of the limit are logged too (DEV-12.8); map tiles, the
# same for every client, only when they fail (DEV-12.5)
app.add_middleware(AccessLog, log=log, quiet=r"^/api/tiles/")


# The commands at their catalog routes; the rest of the API below API_BASE; the map
# tiles, the pages and the health check outside the API
app.include_router(health.router, include_in_schema=False)
app.include_router(commands.router)
app.include_router(server.router, prefix=API_BASE, tags=["server"])
app.include_router(jobs.router, prefix=API_BASE, tags=["jobs"])
app.include_router(tiles.router, prefix="/api", include_in_schema=False)
app.include_router(feedback.router, prefix=API_BASE, tags=["Feedback"])
app.include_router(gui.router, prefix=API_BASE, tags=["Ecosystem"])
app.include_router(basemaps.router, prefix=API_BASE, tags=["Ecosystem"])
app.include_router(site.router, prefix=API_BASE, tags=["Public service"])
app.include_router(site.pages_router)
app.include_router(
    feedback.admin_router,
    prefix=f"{API_BASE}/admin",
    tags=["Admin"],
    responses=problem_responses(401),
)
app.include_router(
    admin.router,
    prefix=f"{API_BASE}/admin",
    tags=["Admin"],
    responses=problem_responses(401),
)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Root endpoint: where the API and its description are."""
    return {
        "message": "Hydrograf API",
        "api": API_BASE,
        "openapi": f"{API_BASE}/openapi.json",
        "health": "/health",
    }
