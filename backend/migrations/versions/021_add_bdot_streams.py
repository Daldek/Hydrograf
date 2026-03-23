"""Add bdot_streams table and is_real_stream flag to stream_network.

Revision ID: 021_bdot_streams
Revises: 020
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "021_bdot_streams"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create bdot_streams table
    op.create_table(
        "bdot_streams",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("geom", Geometry("LINESTRING", srid=2180), nullable=False),
        sa.Column(
            "layer_type",
            sa.String(10),
            nullable=False,
            comment="SWRS=river, SWKN=canal, SWRM=ditch",
        ),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("length_m", sa.Float, nullable=True),
    )
    # GeoAlchemy2 auto-creates spatial index idx_bdot_streams_geom via create_table
    op.create_index("idx_bdot_streams_type", "bdot_streams", ["layer_type"])

    # 2. Add is_real_stream to stream_network
    # NULL = not yet matched, false = overland, true = real stream
    op.add_column(
        "stream_network",
        sa.Column("is_real_stream", sa.Boolean, nullable=True),
    )


def downgrade():
    op.drop_column("stream_network", "is_real_stream")
    op.drop_index("idx_bdot_streams_type", table_name="bdot_streams")
    # Spatial index idx_bdot_streams_geom is dropped automatically with the table
    op.drop_table("bdot_streams")
