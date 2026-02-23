"""Create soil_hsg table.

Revision ID: 016
Revises: 015
Create Date: 2026-02-22
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soil_hsg",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("geom", Geometry("MULTIPOLYGON", srid=2180), nullable=False),
        sa.Column(
            "hsg_group",
            sa.String(1),
            sa.CheckConstraint("hsg_group IN ('A', 'B', 'C', 'D')", name="valid_hsg_group"),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Float, nullable=False),
    )
    # GeoAlchemy2 auto-creates gist index on geom column
    op.create_index("idx_soil_hsg_group", "soil_hsg", ["hsg_group"])


def downgrade() -> None:
    op.drop_table("soil_hsg")
