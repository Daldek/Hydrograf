"""Add hydraulic_length_km column to stream_catchments.

Stores the maximum flow path distance (meters → km) from the most remote
cell in each sub-catchment to the global outlet, computed via pyflwdir
stream_distance(). Used for NRCS (TR-55) and Kerby-Kirpich time of
concentration methods.

Revision ID: 022_hydraulic_length
Revises: 021_bdot_streams
"""
from alembic import op
import sqlalchemy as sa

revision = "022_hydraulic_length"
down_revision = "021_bdot_streams"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stream_catchments",
        sa.Column("hydraulic_length_km", sa.Float, nullable=True),
    )


def downgrade():
    op.drop_column("stream_catchments", "hydraulic_length_km")
