"""
Add B-tree index on stream_network.upstream_area_km2.

Needed for analytical queries. Keeps idx_stream_threshold for MVT
endpoint filtering (WHERE threshold_m2 = :threshold).

Revision ID: 006
Revises: 005
Create Date: 2026-02-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add upstream_area index (keep idx_stream_threshold)."""
    op.create_index(
        "idx_stream_upstream_area",
        "stream_network",
        ["upstream_area_km2"],
    )


def downgrade() -> None:
    """Drop upstream_area index."""
    op.drop_index("idx_stream_upstream_area", table_name="stream_network")
