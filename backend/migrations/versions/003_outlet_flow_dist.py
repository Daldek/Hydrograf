"""Add outlet_flow_dist_m to stream_catchments.

Flow distance [m] at the subcatchment outlet point (along the
stream_distance raster). Baseline for hydraulic_length_km.

Revision ID: 003
Create Date: 2026-08-02
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE stream_catchments ADD COLUMN outlet_flow_dist_m DOUBLE PRECISION"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE stream_catchments DROP COLUMN IF EXISTS outlet_flow_dist_m")
