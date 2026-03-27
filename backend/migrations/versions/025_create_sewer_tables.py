"""Create sewer_nodes and sewer_network tables; augment stream_network.

Adds two new tables for stormwater sewer integration:
- sewer_nodes: manhole/inlet/outlet nodes with topology and elevation data
- sewer_network: pipe segments connecting sewer nodes

Also adds is_sewer_augmented flag to stream_network for tracking
segments whose flow path was modified by the sewer network.

Revision ID: 025
Revises: 024
Create Date: 2026-03-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create sewer_nodes, sewer_network and extend stream_network."""
    op.execute(
        """
        CREATE TABLE sewer_nodes (
            id SERIAL PRIMARY KEY,
            geom GEOMETRY(Point, 2180) NOT NULL,
            node_type VARCHAR(20) NOT NULL,
            component_id INTEGER,
            depth_m DOUBLE PRECISION,
            invert_elev_m DOUBLE PRECISION,
            dem_elev_m DOUBLE PRECISION,
            burn_elev_m DOUBLE PRECISION,
            fa_value INTEGER,
            total_upstream_fa INTEGER,
            root_outlet_id INTEGER REFERENCES sewer_nodes(id),
            nearest_stream_segment_idx INTEGER,
            source_type VARCHAR(20) NOT NULL DEFAULT 'topology_generated',
            rim_elev_m DOUBLE PRECISION,
            max_depth_m DOUBLE PRECISION,
            ponded_area_m2 DOUBLE PRECISION,
            outfall_type VARCHAR(20),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_outlet_not_self CHECK (root_outlet_id != id),
            CONSTRAINT chk_node_type CHECK (node_type IN ('inlet', 'outlet', 'junction', 'isolated'))
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_sewer_nodes_geom "
        "ON sewer_nodes USING GIST (geom)"
    )
    op.execute(
        "CREATE INDEX idx_sewer_nodes_node_type "
        "ON sewer_nodes (node_type)"
    )
    op.execute(
        "CREATE INDEX idx_sewer_nodes_root_outlet_node_type "
        "ON sewer_nodes (root_outlet_id, node_type)"
    )

    op.execute(
        """
        CREATE TABLE sewer_network (
            id SERIAL PRIMARY KEY,
            geom GEOMETRY(LineString, 2180) NOT NULL,
            node_from_id INTEGER NOT NULL REFERENCES sewer_nodes(id),
            node_to_id INTEGER NOT NULL REFERENCES sewer_nodes(id),
            diameter_mm INTEGER,
            width_mm INTEGER,
            height_mm INTEGER,
            cross_section_shape VARCHAR(20),
            invert_elev_start_m DOUBLE PRECISION,
            invert_elev_end_m DOUBLE PRECISION,
            material VARCHAR(50),
            manning_n DOUBLE PRECISION,
            length_m DOUBLE PRECISION NOT NULL,
            slope_percent DOUBLE PRECISION,
            source VARCHAR(50) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_diameter_positive CHECK (diameter_mm IS NULL OR diameter_mm > 0),
            CONSTRAINT chk_length_positive CHECK (length_m > 0),
            CONSTRAINT chk_manning_range CHECK (manning_n IS NULL OR (manning_n > 0 AND manning_n < 1))
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_sewer_network_geom "
        "ON sewer_network USING GIST (geom)"
    )
    op.execute(
        "CREATE INDEX idx_sewer_network_node_from_id "
        "ON sewer_network (node_from_id)"
    )
    op.execute(
        "CREATE INDEX idx_sewer_network_node_to_id "
        "ON sewer_network (node_to_id)"
    )

    op.execute(
        "ALTER TABLE stream_network "
        "ADD COLUMN is_sewer_augmented BOOLEAN DEFAULT FALSE"
    )


def downgrade() -> None:
    """Remove sewer tables and stream_network augmentation flag."""
    op.execute(
        "ALTER TABLE stream_network "
        "DROP COLUMN IF EXISTS is_sewer_augmented"
    )

    op.execute("DROP TABLE IF EXISTS sewer_network")
    op.execute("DROP TABLE IF EXISTS sewer_nodes")
