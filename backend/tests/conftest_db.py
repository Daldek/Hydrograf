"""
Database fixtures for integration and performance tests.

These fixtures connect to a real PostGIS database and load
synthetic test data. Tests using these fixtures are skipped
when PostGIS is not available.
"""
import os
import pathlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _get_db_url() -> str:
    """Get database URL from environment or default."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db",
    )


def _db_available() -> bool:
    """Check if PostGIS database is available."""
    try:
        engine = create_engine(_get_db_url())
        with engine.connect() as conn:
            conn.execute(text("SELECT PostGIS_Version()"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_available(), reason="PostGIS not available"
)


@pytest.fixture(scope="session")
def db_engine():
    """Create SQLAlchemy engine for test database."""
    engine = create_engine(_get_db_url())
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def setup_test_data(db_engine):
    """Load synthetic test data from SQL fixture. Clean up after all tests."""
    sql_path = pathlib.Path(__file__).parent / "fixtures" / "test_catchments.sql"
    sql = sql_path.read_text()

    # Use raw DBAPI connection for multi-statement SQL
    raw_conn = db_engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.execute(sql)
        raw_conn.commit()
        cursor.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    yield

    # Cleanup: remove test data (segment_idx >= 9000)
    with db_engine.connect() as conn:
        conn.execute(text(
            "DELETE FROM stream_catchments WHERE segment_idx >= 9000"
        ))
        conn.execute(text(
            "DELETE FROM stream_network WHERE segment_idx >= 9000"
        ))
        conn.commit()


@pytest.fixture
def db_session(db_engine, setup_test_data):
    """Per-test database session with rollback."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
