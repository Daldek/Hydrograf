"""
Drop flow_network table.

Table stored every DEM pixel (~39.4M rows) but is not used by any API
endpoint at runtime. Stream/catchment data is served from stream_network
and stream_catchments tables. Saves ~2 GB disk and 17 min pipeline time.

Revision ID: 015
Revises: 014
Create Date: 2026-02-17
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("flow_network")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE flow_network (
            id SERIAL PRIMARY KEY,
            geom geometry(Point, 2180) NOT NULL,
            elevation REAL NOT NULL,
            flow_accumulation INTEGER NOT NULL DEFAULT 0,
            slope REAL,
            downstream_id INTEGER REFERENCES flow_network(id),
            cell_area REAL NOT NULL DEFAULT 1.0,
            is_stream BOOLEAN NOT NULL DEFAULT FALSE,
            strahler_order SMALLINT
        )
    """)
    op.execute("CREATE INDEX idx_flow_geom ON flow_network USING GIST (geom)")
    op.execute("CREATE INDEX idx_downstream ON flow_network (downstream_id)")
    op.execute("CREATE INDEX idx_is_stream ON flow_network (is_stream)")
    op.execute("CREATE INDEX idx_flow_accumulation ON flow_network (flow_accumulation)")
    op.execute("CREATE INDEX idx_strahler ON flow_network (strahler_order)")
