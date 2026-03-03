"""Remove stream_network rows with threshold_m2=100.

Threshold 100 m² generated ~2.5M segments (90% of table) that have no
corresponding catchments (removed in ADR-026) and are unused by API/frontend.
This migration deletes the data and drops the now-unnecessary partial indexes.

Revision ID: 017
Revises: 016
Create Date: 2026-02-24
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET statement_timeout = 0")
    op.execute("DELETE FROM stream_network WHERE threshold_m2 = 100")
    op.execute("DROP INDEX IF EXISTS idx_stream_geom_t100")
    op.execute("DROP INDEX IF EXISTS idx_catchment_geom_t100")


def downgrade() -> None:
    # Data cannot be restored — re-run pipeline with threshold 100 if needed.
    pass
