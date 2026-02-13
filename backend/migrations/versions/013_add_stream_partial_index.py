"""
Add partial GiST index on flow_network for stream cells.

Speeds up find_nearest_stream() by indexing only ~87k stream cells
instead of scanning the full 19.7M-row GiST index.

Revision ID: 013
Revises: 012
Create Date: 2026-02-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add partial GiST index for stream cells."""
    op.execute(
        "CREATE INDEX idx_flow_network_stream_geom "
        "ON flow_network USING gist(geom) "
        "WHERE is_stream = TRUE"
    )


def downgrade() -> None:
    """Drop partial GiST index for stream cells."""
    op.execute("DROP INDEX IF EXISTS idx_flow_network_stream_geom")
