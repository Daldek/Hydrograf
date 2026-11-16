"""Add the flow path head, overland and stream head columns to stream_catchments.

Per sub-catchment, on the filled DEM of the zonal statistics:

- flow_path_head_elev_m: elevation of the head (farthest cell) of the longest
  flow path [m a.s.l.]
- overland_length_m, overland_drop_m: length [m] and drop [m] of the overland
  segment of that path, from its head to the first cell of the DEM stream
  network of the sub-catchment's threshold
- stream_head_elev_m: elevation of the upstream end of the sub-catchment's
  stream segment [m a.s.l.] (the source of a first-order stream)

Also the partial GIST indexes of the accumulation thresholds 1 km² and 10 km²,
as 001 has them for 1000, 10000 and 100000 m².

Revision ID: 004
Create Date: 2026-11-05
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

_COLUMNS = (
    "flow_path_head_elev_m",
    "overland_length_m",
    "overland_drop_m",
    "stream_head_elev_m",
)
_THRESHOLDS_M2 = (1_000_000, 10_000_000)


def upgrade() -> None:
    """Add the four columns and the partial indexes."""
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE stream_catchments ADD COLUMN {column} DOUBLE PRECISION"
        )
    for threshold in _THRESHOLDS_M2:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_stream_geom_t{threshold} "
            f"ON stream_network USING GIST (geom) WHERE threshold_m2 = {threshold}"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_catchment_geom_t{threshold} "
            f"ON stream_catchments USING GIST (geom) WHERE threshold_m2 = {threshold}"
        )


def downgrade() -> None:
    """Drop the partial indexes and the four columns."""
    for threshold in _THRESHOLDS_M2:
        op.execute(f"DROP INDEX IF EXISTS idx_catchment_geom_t{threshold}")
        op.execute(f"DROP INDEX IF EXISTS idx_stream_geom_t{threshold}")
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE stream_catchments DROP COLUMN IF EXISTS {column}")
