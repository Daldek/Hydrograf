"""
Add filter indexes on depressions table.

Indexes on volume_m3, area_m2, and max_depth_m for efficient
filtering in the depressions API endpoint (e.g. min_volume, min_area).

Revision ID: 008
Revises: 007
Create Date: 2026-02-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add B-tree indexes for depressions filtering."""
    op.create_index(
        "idx_depressions_volume",
        "depressions",
        ["volume_m3"],
    )
    op.create_index(
        "idx_depressions_area",
        "depressions",
        ["area_m2"],
    )
    op.create_index(
        "idx_depressions_max_depth",
        "depressions",
        ["max_depth_m"],
    )


def downgrade() -> None:
    """Drop depressions filter indexes."""
    op.drop_index("idx_depressions_max_depth", table_name="depressions")
    op.drop_index("idx_depressions_area", table_name="depressions")
    op.drop_index("idx_depressions_volume", table_name="depressions")
