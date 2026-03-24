"""Add divide_flow_path_geom column to stream_catchments.

The divide flow path is the path from the cell with maximum flow distance
on the subcatchment BOUNDARY (divide) to the outlet, as opposed to
longest_flow_path_geom which uses the farthest cell anywhere in the
subcatchment.

Revision ID: 024
Revises: d7af925de530
Create Date: 2026-03-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "024"
down_revision: str | None = "d7af925de530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add divide_flow_path_geom to stream_catchments."""
    op.execute(
        "ALTER TABLE stream_catchments "
        "ADD COLUMN divide_flow_path_geom GEOMETRY(LINESTRING, 2180)"
    )

    # Spatial index for divide flow path geometries
    op.execute(
        "CREATE INDEX idx_catchments_divide_flow_path_geom "
        "ON stream_catchments USING GIST (divide_flow_path_geom) "
        "WHERE divide_flow_path_geom IS NOT NULL"
    )


def downgrade() -> None:
    """Remove divide_flow_path_geom from stream_catchments."""
    op.execute("DROP INDEX IF EXISTS idx_catchments_divide_flow_path_geom")
    op.execute(
        "ALTER TABLE stream_catchments "
        "DROP COLUMN IF EXISTS divide_flow_path_geom"
    )
