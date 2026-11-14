"""
FastAPI application entry point.

Configures the API with routers, middleware, and exception handlers.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api.endpoints import (
    admin,
    depressions,
    feedback,
    gui,
    health,
    hydrograph,
    identify,
    network,
    profile,
    site,
    tiles,
    watershed,
)
from api.errors import (
    install_error_handlers,
    install_openapi,
    operation_id,
    problem_responses,
)
from api.traffic import Traffic, keep_traffic, limit_and_count
from core.catchment_graph import loaded_catchment_graph
from core.config import get_settings, state_dir
from core.database import get_db_session
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
    key, database URL or operator's details), loads the in-memory catchment graph,
    fills the regulamin of the deployment and keeps the request limit and the daily
    totals (ADR-084), whose last totals it stores at shutdown, before the logs stop.
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

    # Load the catchment graph now rather than at the first request; requests
    # load it again when the network in the database changes
    try:
        with get_db_session() as db:
            if loaded_catchment_graph(db) is None:
                logger.warning("Catchment graph not loaded at startup")
    except Exception as e:
        logger.warning(f"Catchment graph loading failed: {e}")

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
        "Hydrological analysis system: watershed delineation, catchment parameters "
        "and design hydrographs in Poland. Errors are `application/problem+json` "
        "with a code of the shared Nogat error registry; texts follow "
        "`Accept-Language` (English by default, `pl` for Polish)."
    ),
    version=get_version(),
    lifespan=lifespan,
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
# Outermost, so the refusals of the limit are logged too (DEV-12.8); map tiles, the
# same for every client, only when they fail (DEV-12.5)
app.add_middleware(AccessLog, log=log, quiet=r"^/api/tiles/")


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(
    watershed.router,
    prefix="/api",
    tags=["Watershed"],
    responses=problem_responses(404, 422, 503),
)
app.include_router(
    network.router,
    prefix="/api",
    tags=["Network"],
    # The window cap (422) is the full run's alone: the route documents it
    responses=problem_responses(404, 503),
)
app.include_router(hydrograph.router, prefix="/api", tags=["Hydrograph"])
app.include_router(tiles.router, prefix="/api", tags=["Tiles"])
app.include_router(
    profile.router,
    prefix="/api",
    tags=["Profile"],
    responses=problem_responses(404, 503),
)
app.include_router(
    identify.router,
    prefix="/api",
    tags=["Identify"],
    responses=problem_responses(404, 503),
)
app.include_router(depressions.router, prefix="/api", tags=["Depressions"])
app.include_router(feedback.router, prefix="/api", tags=["Feedback"])
app.include_router(gui.router, prefix="/api", tags=["Ecosystem"])
app.include_router(site.router, prefix="/api", tags=["Public service"])
app.include_router(site.pages_router)
app.include_router(
    feedback.admin_router,
    prefix="/api/admin",
    tags=["Admin"],
    responses=problem_responses(401),
)
app.include_router(
    admin.router,
    prefix="/api/admin",
    tags=["Admin"],
    responses=problem_responses(401),
)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint - redirect info."""
    return {
        "message": "Hydrograf API",
        "docs": "/docs",
        "health": "/health",
    }
