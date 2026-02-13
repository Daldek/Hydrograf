"""
Extend stream_catchments with downstream link and pre-computed stats.

Adds columns for catchment graph traversal (downstream_segment_idx)
and pre-computed zonal statistics (elevation min/max, perimeter,
stream length, elevation histogram) to enable zero-raster runtime queries.

Revision ID: 012
Revises: 011
Create Date: 2026-02-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add downstream link and pre-computed stats to stream_catchments."""
    # Downstream connectivity for graph traversal
    op.execute(
        "ALTER TABLE stream_catchments ADD COLUMN downstream_segment_idx INTEGER"
    )

    # Elevation range (for aggregation without raster access)
    op.execute(
        "ALTER TABLE stream_catchments ADD COLUMN elevation_min_m DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE stream_catchments ADD COLUMN elevation_max_m DOUBLE PRECISION"
    )

    # Geometry-derived metrics
    op.execute("ALTER TABLE stream_catchments ADD COLUMN perimeter_km DOUBLE PRECISION")
    op.execute(
        "ALTER TABLE stream_catchments ADD COLUMN stream_length_km DOUBLE PRECISION"
    )

    # Elevation histogram for hypsometric curve aggregation
    op.execute("ALTER TABLE stream_catchments ADD COLUMN elev_histogram JSONB")

    # Index for graph traversal queries
    op.execute(
        "CREATE INDEX idx_catchments_downstream "
        "ON stream_catchments(threshold_m2, downstream_segment_idx)"
    )


def downgrade() -> None:
    """Remove downstream link and pre-computed stats columns."""
    op.execute("DROP INDEX IF EXISTS idx_catchments_downstream")
    op.execute("ALTER TABLE stream_catchments DROP COLUMN IF EXISTS elev_histogram")
    op.execute("ALTER TABLE stream_catchments DROP COLUMN IF EXISTS stream_length_km")
    op.execute("ALTER TABLE stream_catchments DROP COLUMN IF EXISTS perimeter_km")
    op.execute("ALTER TABLE stream_catchments DROP COLUMN IF EXISTS elevation_max_m")
    op.execute("ALTER TABLE stream_catchments DROP COLUMN IF EXISTS elevation_min_m")
    op.execute(
        "ALTER TABLE stream_catchments DROP COLUMN IF EXISTS downstream_segment_idx"
    )
