"""
Fix unique index on stream_network to include threshold_m2.

The original idx_stream_unique (migration 002) used only
COALESCE(name, '') + ST_GeoHash(geom, 12), which silently dropped
segments from higher FA thresholds that shared the same geohash
as segments from lower thresholds (all DEM-derived streams have
name=NULL → COALESCE='').

Adding threshold_m2 to the index allows segments from different
FA thresholds to coexist. See ADR-019.

Revision ID: 010
Revises: 009
Create Date: 2026-02-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace idx_stream_unique with threshold-aware version."""
    op.drop_index("idx_stream_unique", table_name="stream_network")
    op.execute(
        "CREATE UNIQUE INDEX idx_stream_unique ON stream_network ("
        "    COALESCE(name, ''),"
        "    threshold_m2,"
        "    ST_GeoHash(ST_Transform(geom, 4326), 12)"
        ")"
    )


def downgrade() -> None:
    """Restore original idx_stream_unique without threshold_m2."""
    op.drop_index("idx_stream_unique", table_name="stream_network")
    op.execute(
        "CREATE UNIQUE INDEX idx_stream_unique ON stream_network ("
        "    COALESCE(name, ''),"
        "    ST_GeoHash(ST_Transform(geom, 4326), 12)"
        ")"
    )
