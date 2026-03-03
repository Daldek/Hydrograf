"""
Add partial spatial indexes for tile serving performance.

Partial GIST indexes on stream_network and stream_catchments
per threshold_m2 value significantly speed up tile queries
that filter WHERE threshold_m2 = N.

Revision ID: 011
Revises: 010
Create Date: 2026-02-13
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

THRESHOLDS = [100, 1000, 10000, 100000]


def upgrade() -> None:
    for t in THRESHOLDS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_stream_geom_t{t} "
            f"ON stream_network USING GIST(geom) WHERE threshold_m2 = {t}"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_catchment_geom_t{t} "
            f"ON stream_catchments USING GIST(geom) WHERE threshold_m2 = {t}"
        )


def downgrade() -> None:
    for t in THRESHOLDS:
        op.execute(f"DROP INDEX IF EXISTS idx_stream_geom_t{t}")
        op.execute(f"DROP INDEX IF EXISTS idx_catchment_geom_t{t}")
