"""
Add threshold_m2 column to stream_network.

Allows storing multiple stream networks per flow accumulation threshold
in a single table, enabling multi-density display in the frontend.

Revision ID: 005
Revises: 004
Create Date: 2026-02-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add threshold_m2 column and composite index."""
    op.add_column(
        "stream_network",
        sa.Column(
            "threshold_m2",
            sa.Integer,
            nullable=False,
            server_default="100",
            comment="Flow accumulation threshold in m2 used to generate this segment",
        ),
    )

    # Composite index for MVT queries filtered by threshold
    op.create_index(
        "idx_stream_threshold",
        "stream_network",
        ["threshold_m2", "strahler_order"],
    )


def downgrade() -> None:
    """Remove threshold_m2 column and index."""
    op.drop_index("idx_stream_threshold", table_name="stream_network")
    op.drop_column("stream_network", "threshold_m2")
