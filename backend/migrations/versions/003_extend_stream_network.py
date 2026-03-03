"""
Extend stream_network and flow_network schema.

Add upstream_area_km2 and mean_slope_percent to stream_network.
Add strahler_order to flow_network for runtime queries.

Revision ID: 003
Revises: 002
Create Date: 2026-02-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add new columns and indexes."""
    # stream_network: upstream area at segment end
    op.add_column(
        "stream_network",
        sa.Column(
            "upstream_area_km2",
            sa.Float,
            nullable=True,
            comment="Upstream catchment area at segment end [km2]",
        ),
    )

    # stream_network: mean slope along segment
    op.add_column(
        "stream_network",
        sa.Column(
            "mean_slope_percent",
            sa.Float,
            nullable=True,
            comment="Mean slope along stream segment [%]",
        ),
    )

    # flow_network: Strahler stream order
    op.add_column(
        "flow_network",
        sa.Column(
            "strahler_order",
            sa.SmallInteger,
            nullable=True,
            comment="Strahler stream order (NULL for non-stream cells)",
        ),
    )

    # Partial index on strahler_order (only for stream cells)
    op.create_index(
        "idx_strahler",
        "flow_network",
        ["strahler_order"],
        postgresql_where=sa.text("strahler_order IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove added columns and indexes."""
    op.drop_index("idx_strahler", table_name="flow_network")
    op.drop_column("flow_network", "strahler_order")
    op.drop_column("stream_network", "mean_slope_percent")
    op.drop_column("stream_network", "upstream_area_km2")
