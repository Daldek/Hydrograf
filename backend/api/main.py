"""
FastAPI application entry point.

Configures the API with routers, middleware, and exception handlers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from api.endpoints import health, hydrograph, watershed

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Hydrograf API...")
    yield
    logger.info("Shutting down Hydrograf API...")


app = FastAPI(
    title="Hydrograf API",
    description="System analizy hydrologicznej - wyznaczanie zlewni i hydrogramów",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(watershed.router, prefix="/api", tags=["Watershed"])
app.include_router(hydrograph.router, prefix="/api", tags=["Hydrograph"])


@app.get("/")
async def root():
    """Root endpoint - redirect info."""
    return {
        "message": "Hydrograf API",
        "docs": "/docs",
        "health": "/health",
    }
