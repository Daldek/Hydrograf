"""
Create depressions table for blue spots.

Stores terrain depression polygons with volume, area, and depth metrics.

Revision ID: 004
Revises: 003
Create Date: 2026-02-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create depressions table with spatial index."""
    op.create_table(
        "depressions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "geom",
            Geometry("POLYGON", srid=2180),
            nullable=False,
        ),
        sa.Column("volume_m3", sa.Float, nullable=False),
        sa.Column("area_m2", sa.Float, nullable=False),
        sa.Column("max_depth_m", sa.Float, nullable=False),
        sa.Column("mean_depth_m", sa.Float, nullable=True),
    )
    op.create_index(
        "idx_depressions_geom",
        "depressions",
        ["geom"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    """Drop depressions table."""
    op.drop_index("idx_depressions_geom", table_name="depressions")
    op.drop_table("depressions")
