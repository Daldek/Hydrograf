"""
Database connection and session management.

Provides SQLAlchemy engine and session factory with connection pooling.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from core.config import get_settings


def get_engine():
    """
    Create SQLAlchemy engine with connection pooling.

    Returns
    -------
    Engine
        SQLAlchemy engine instance
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=3600,
        echo=settings.log_level == "DEBUG",
    )


# Global engine instance (lazy initialization)
_engine = None


def get_db_engine():
    """
    Get or create the database engine.

    Returns
    -------
    Engine
        SQLAlchemy engine instance
    """
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI to get database session.

    Yields
    ------
    Session
        SQLAlchemy session

    Examples
    --------
    >>> @app.get("/items")
    ... def get_items(db: Session = Depends(get_db)):
    ...     return db.query(Item).all()
    """
    engine = get_db_engine()
    SessionLocal.configure(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database session.

    For use in scripts and non-FastAPI contexts.

    Yields
    ------
    Session
        SQLAlchemy session

    Examples
    --------
    >>> with get_db_session() as db:
    ...     db.execute(text("SELECT 1"))
    """
    engine = get_db_engine()
    SessionLocal.configure(bind=engine)
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
