"""
FastAPI application entry point.

Configures the API with routers, middleware, and exception handlers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from api.endpoints import health, watershed

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
    logger.info("Starting HydroLOG API...")
    yield
    logger.info("Shutting down HydroLOG API...")


app = FastAPI(
    title="HydroLOG API",
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


@app.get("/")
async def root():
    """Root endpoint - redirect info."""
    return {
        "message": "HydroLOG API",
        "docs": "/docs",
        "health": "/health",
    }
