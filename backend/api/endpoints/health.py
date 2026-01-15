"""
Health check endpoint.

Provides system health status including database connectivity.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    database: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Check system health.

    Returns
    -------
    HealthResponse
        System health status including database connectivity
    """
    # Check database connection
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    status = "healthy" if db_status == "connected" else "unhealthy"

    return HealthResponse(
        status=status,
        database=db_status,
        version="1.0.0",
    )
