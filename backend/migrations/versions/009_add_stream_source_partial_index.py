"""
Add partial spatial index on stream_network for DEM-derived streams.

Speeds up get_stream_stats_in_watershed() which filters by
source = 'DEM_DERIVED' and ST_Intersects(geom, boundary).

Revision ID: 009
Revises: 008
Create Date: 2026-02-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create partial GIST index for DEM-derived stream lookup."""
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stream_geom_dem_derived "
        "ON stream_network USING gist (geom) "
        "WHERE source = 'DEM_DERIVED'"
    )


def downgrade() -> None:
    """Drop partial index."""
    op.drop_index(
        "idx_stream_geom_dem_derived",
        table_name="stream_network",
    )
