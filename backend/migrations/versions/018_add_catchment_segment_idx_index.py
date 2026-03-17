"""Add composite index on (threshold_m2, segment_idx) for stream_catchments.

Speeds up ANY(:idxs) filtering in merge_catchment_boundaries() which is
the main bottleneck when selecting large upstream catchments.
"""

from alembic import op

revision = "018"
down_revision = "017"


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_catchments_threshold_segment "
        "ON stream_catchments(threshold_m2, segment_idx)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_catchments_threshold_segment")
