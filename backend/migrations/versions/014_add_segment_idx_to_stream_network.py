"""
Add segment_idx column to stream_network.

Enables lookup by (threshold_m2, segment_idx) instead of auto-increment id,
which diverges from stream_catchments.segment_idx at coarse thresholds.

Revision ID: 014
Revises: 013
Create Date: 2026-02-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stream_network ADD COLUMN segment_idx INTEGER")
    op.execute(
        "CREATE INDEX idx_stream_threshold_segidx "
        "ON stream_network (threshold_m2, segment_idx)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stream_threshold_segidx")
    op.execute("ALTER TABLE stream_network DROP COLUMN IF EXISTS segment_idx")
