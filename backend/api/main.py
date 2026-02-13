"""
FastAPI application entry point.

Configures the API with routers, middleware, and exception handlers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api.endpoints import (
    depressions,
    health,
    hydrograph,
    profile,
    select_stream,
    tiles,
    watershed,
)
from core.catchment_graph import get_catchment_graph
from core.config import get_settings
from core.database import get_db_session
from core.flow_graph import get_flow_graph

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — loads in-memory flow graph."""
    logger.info("Starting Hydrograf API...")

    # Load flow graph for fast upstream traversal
    graph = get_flow_graph()
    try:
        with get_db_session() as db:
            graph.load(db)
    except Exception as e:
        logger.warning(f"Flow graph loading failed, using SQL fallback: {e}")

    # Load catchment graph (~8 MB, ~100ms)
    cg = get_catchment_graph()
    try:
        with get_db_session() as db:
            cg.load(db)
    except Exception as e:
        logger.warning(f"Catchment graph loading failed: {e}")

    yield
    logger.info("Shutting down Hydrograf API...")


app = FastAPI(
    title="Hydrograf API",
    description="System analizy hydrologicznej - wyznaczanie zlewni i hydrogramów",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware - origins from environment variable
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(watershed.router, prefix="/api", tags=["Watershed"])
app.include_router(hydrograph.router, prefix="/api", tags=["Hydrograph"])
app.include_router(tiles.router, prefix="/api", tags=["Tiles"])
app.include_router(profile.router, prefix="/api", tags=["Profile"])
app.include_router(depressions.router, prefix="/api", tags=["Depressions"])
app.include_router(select_stream.router, prefix="/api", tags=["Selection"])


@app.get("/")
async def root():
    """Root endpoint - redirect info."""
    return {
        "message": "Hydrograf API",
        "docs": "/docs",
        "health": "/health",
    }
