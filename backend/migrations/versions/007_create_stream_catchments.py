"""
Create stream_catchments table for sub-catchment polygons.

Each sub-catchment is a MULTIPOLYGON draining directly to a single
stream segment (identified by segment_idx within a given threshold).
Used for MVT tile serving and hydrological analysis.

Revision ID: 007
Revises: 006
Create Date: 2026-02-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create stream_catchments table with spatial and composite indexes."""
    op.execute("""
        CREATE TABLE stream_catchments (
            id SERIAL PRIMARY KEY,
            geom GEOMETRY(MULTIPOLYGON, 2180) NOT NULL,
            segment_idx INTEGER NOT NULL,
            threshold_m2 INTEGER NOT NULL,
            area_km2 DOUBLE PRECISION NOT NULL,
            mean_elevation_m DOUBLE PRECISION,
            mean_slope_percent DOUBLE PRECISION,
            strahler_order INTEGER
        )
    """)

    # Spatial index (critical for MVT tile queries)
    op.execute(
        "CREATE INDEX idx_catchments_geom "
        "ON stream_catchments USING GIST (geom)"
    )

    # Composite index for MVT filtering (threshold + strahler)
    op.execute(
        "CREATE INDEX idx_catchments_threshold "
        "ON stream_catchments (threshold_m2, strahler_order)"
    )

    # B-tree index on area for analytical queries
    op.execute(
        "CREATE INDEX idx_catchments_area "
        "ON stream_catchments (area_km2)"
    )


def downgrade() -> None:
    """Drop stream_catchments table and all indexes."""
    op.drop_table("stream_catchments")
