"""A private, migrated PostGIS database for tests that publish whole runs.

``publish_run`` replaces *all* DEM-derived streams and sub-catchments, so a test of it
must not run on the shared test database, whose rows other tests rely on.
``scratch_database`` creates a database of its own on the server of ``DATABASE_URL``
(the role needs CREATEDB, and superuser rights for the PostGIS extension of migration
001: the role of the `db` job of CI has both), runs the migrations to a revision and
drops the database again.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.conftest_db import _get_db_url

_BACKEND = Path(__file__).resolve().parent.parent


def migrate(url: str, command: str, revision: str) -> None:
    """Run ``alembic <command> <revision>`` of the backend on the database ``url``.

    ``command`` is ``upgrade`` or ``downgrade``. Alembic runs in a process of its own:
    its ``env.py`` reads the database from ``DATABASE_URL`` and configures logging,
    which must not leak into the test session.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=_BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )


@contextmanager
def scratch_database(revision: str = "head") -> Iterator[str]:
    """Create a database migrated to ``revision``; yield its URL; drop it afterwards."""
    base = make_url(_get_db_url())
    name = f"hydro_scratch_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = base.set(database=name).render_as_string(hide_password=False)
        try:
            migrate(url, "upgrade", revision)
            yield url
        finally:
            with admin.connect() as connection:
                connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                )
    finally:
        admin.dispose()
