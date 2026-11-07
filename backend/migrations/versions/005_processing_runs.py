"""Add the run and unit records of the PGW unit bootstrap.

``processing_runs`` has one row per run of ``process_dem --units``: the immutable
input fingerprint and configuration, the run's status and, through the partial
unique index, the one ``active`` run whose results ``stream_network`` and
``stream_catchments`` hold now. A run is ``staging`` while its units are computed,
``active`` once all of them are published in one transaction, ``superseded`` when a
later run replaces it and ``failed`` when it was given up.

``processing_units`` has one row per PGW owner of a run, keyed by
``(run_id, owner_code)``: ``pending`` until the unit's owned-cell rasters are final,
then ``complete`` with the unit's bounds on the shared grid (half-open cell indexes)
and the manifest of its raster files (path, size, SHA-256) that a publication checks
again.

Revision ID: 005
Create Date: 2026-11-07
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the run and unit tables and the one-active-run index."""
    op.execute("""
        CREATE TABLE processing_runs (
            id SERIAL PRIMARY KEY,
            status VARCHAR(16) NOT NULL DEFAULT 'staging',
            input_fingerprint TEXT NOT NULL,
            source_raster TEXT NOT NULL,
            pgw_path TEXT NOT NULL,
            config JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_at TIMESTAMPTZ,
            superseded_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            error TEXT,
            published_counts JSONB,
            CONSTRAINT chk_processing_runs_status CHECK (
                status IN ('staging', 'active', 'superseded', 'failed')
            ),
            CONSTRAINT chk_processing_runs_fingerprint CHECK (input_fingerprint <> ''),
            CONSTRAINT chk_processing_runs_config CHECK (
                jsonb_typeof(config) = 'object'
            ),
            CONSTRAINT chk_processing_runs_published CHECK (
                (status IN ('active', 'superseded'))
                = (activated_at IS NOT NULL AND published_counts IS NOT NULL)
            ),
            CONSTRAINT chk_processing_runs_superseded CHECK (
                (status = 'superseded') = (superseded_at IS NOT NULL)
            ),
            CONSTRAINT chk_processing_runs_failed CHECK (
                (status = 'failed')
                = (failed_at IS NOT NULL AND error IS NOT NULL AND error <> '')
            )
        )
    """)
    # At most one run is visible: a second activation fails instead of mixing two runs.
    op.execute(
        "CREATE UNIQUE INDEX idx_processing_runs_one_active "
        "ON processing_runs USING btree (status) WHERE status = 'active'"
    )

    op.execute("""
        CREATE TABLE processing_units (
            run_id INTEGER NOT NULL REFERENCES processing_runs(id) ON DELETE CASCADE,
            owner_code TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            row_start INTEGER,
            row_stop INTEGER,
            col_start INTEGER,
            col_stop INTEGER,
            outputs JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            PRIMARY KEY (run_id, owner_code),
            CONSTRAINT chk_processing_units_owner CHECK (owner_code <> ''),
            CONSTRAINT chk_processing_units_status CHECK (
                status IN ('pending', 'complete')
            ),
            CONSTRAINT chk_processing_units_bounds CHECK (
                row_start >= 0 AND row_stop >= row_start
                AND col_start >= 0 AND col_stop >= col_start
            ),
            CONSTRAINT chk_processing_units_manifest CHECK (
                outputs IS NULL
                OR (jsonb_typeof(outputs) = 'object' AND outputs <> '{}'::jsonb)
            ),
            CONSTRAINT chk_processing_units_complete CHECK (
                (status = 'complete') = (
                    row_start IS NOT NULL AND row_stop IS NOT NULL
                    AND col_start IS NOT NULL AND col_stop IS NOT NULL
                    AND outputs IS NOT NULL AND completed_at IS NOT NULL
                )
            )
        )
    """)


def downgrade() -> None:
    """Drop the unit and run tables (the index goes with its table)."""
    op.execute("DROP TABLE IF EXISTS processing_units")
    op.execute("DROP TABLE IF EXISTS processing_runs")
