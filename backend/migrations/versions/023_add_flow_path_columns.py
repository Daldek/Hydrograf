"""Add flow path columns to stream_catchments.

Adds max_flow_dist_m (distance of farthest cell to global outlet)
and longest_flow_path_geom (LINESTRING geometry of longest flow path
within each sub-catchment) for time-of-concentration calculations.

Revision ID: 023
Revises: 020
Create Date: 2026-03-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "023"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add flow path columns to stream_catchments."""
    op.execute(
        "ALTER TABLE stream_catchments "
        "ADD COLUMN max_flow_dist_m DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE stream_catchments "
        "ADD COLUMN longest_flow_path_geom GEOMETRY(LINESTRING, 2180)"
    )

    # Spatial index for flow path geometries (useful for map display)
    op.execute(
        "CREATE INDEX idx_catchments_flow_path_geom "
        "ON stream_catchments USING GIST (longest_flow_path_geom) "
        "WHERE longest_flow_path_geom IS NOT NULL"
    )


def downgrade() -> None:
    """Remove flow path columns from stream_catchments."""
    op.execute("DROP INDEX IF EXISTS idx_catchments_flow_path_geom")
    op.execute(
        "ALTER TABLE stream_catchments "
        "DROP COLUMN IF EXISTS longest_flow_path_geom"
    )
    op.execute(
        "ALTER TABLE stream_catchments "
        "DROP COLUMN IF EXISTS max_flow_dist_m"
    )
