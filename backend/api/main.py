"""
FastAPI application entry point.

Configures the API with routers, middleware, and exception handlers.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from api.endpoints import (
    admin,
    depressions,
    feedback,
    health,
    hydrograph,
    identify,
    network,
    profile,
    tiles,
    watershed,
)
from api.errors import (
    install_error_handlers,
    install_openapi,
    operation_id,
    problem_responses,
)
from core.catchment_graph import loaded_catchment_graph
from core.config import get_settings
from core.database import get_db_session
from core.version import get_version

# Configure structured logging
settings = get_settings()
log_level = getattr(logging, settings.log_level)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
        if settings.log_level != "DEBUG"
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logging.basicConfig(
    format="%(message)s",
    level=log_level,
)
logger = logging.getLogger(__name__)
request_logger = structlog.get_logger("api.requests")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler — loads in-memory catchment graph."""
    logger.info("Starting Hydrograf API...")

    # Load the catchment graph now rather than at the first request; requests
    # load it again when the network in the database changes
    try:
        with get_db_session() as db:
            if loaded_catchment_graph(db) is None:
                logger.warning("Catchment graph not loaded at startup")
    except Exception as e:
        logger.warning(f"Catchment graph loading failed: {e}")

    yield
    logger.info("Shutting down Hydrograf API...")


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


@app.middleware("http")
async def add_request_id(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Correlate proxy and API logs with one request ID."""
    forwarded_id = request.headers.get("x-request-id", "")
    request_id = (
        forwarded_id.lower()
        if len(forwarded_id) == 32
        and all(char in "0123456789abcdefABCDEF" for char in forwarded_id)
        else uuid.uuid4().hex
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    log_fields = {"method": request.method, "path": request.url.path}
    try:
        response = await call_next(request)
    except Exception:
        request_logger.exception(
            "request_failed",
            **log_fields,
            status_code=500,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise
    response.headers["X-Request-ID"] = request_id
    request_logger.info(
        "request_completed",
        **log_fields,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return response


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
