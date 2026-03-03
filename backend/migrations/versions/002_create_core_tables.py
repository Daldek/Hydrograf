"""
Create flow_network, land_cover, stream_network tables.

Revision ID: 002
Revises: 001
Create Date: 2026-01-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create core tables for hydrological analysis."""
    # ===================
    # flow_network table
    # ===================
    op.create_table(
        "flow_network",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "geom",
            Geometry(geometry_type="POINT", srid=2180),
            nullable=False,
            comment="Cell centroid in EPSG:2180 (PL-1992)",
        ),
        sa.Column(
            "elevation",
            sa.Float,
            nullable=False,
            comment="Elevation [m a.s.l.]",
        ),
        sa.Column(
            "flow_accumulation",
            sa.Integer,
            nullable=False,
            default=0,
            comment="Number of upstream cells",
        ),
        sa.Column(
            "slope",
            sa.Float,
            nullable=True,
            comment="Terrain slope [%]",
        ),
        sa.Column(
            "downstream_id",
            sa.Integer,
            sa.ForeignKey("flow_network.id", ondelete="SET NULL"),
            nullable=True,
            comment="ID of downstream cell (NULL for outlets)",
        ),
        sa.Column(
            "cell_area",
            sa.Float,
            nullable=False,
            comment="Cell area [m2]",
        ),
        sa.Column(
            "is_stream",
            sa.Boolean,
            nullable=False,
            default=False,
            comment="True if cell is part of stream network",
        ),
        # Check constraints
        sa.CheckConstraint(
            "elevation >= -50 AND elevation <= 3000",
            name="valid_elevation",
        ),
        sa.CheckConstraint(
            "flow_accumulation >= 0",
            name="valid_accumulation",
        ),
        sa.CheckConstraint(
            "cell_area > 0",
            name="positive_area",
        ),
        sa.CheckConstraint(
            "slope IS NULL OR slope >= 0",
            name="valid_slope",
        ),
        comment="Flow direction graph from DEM preprocessing",
    )

    # Indexes for flow_network
    op.create_index(
        "idx_flow_geom",
        "flow_network",
        ["geom"],
        postgresql_using="gist",
    )
    op.create_index(
        "idx_downstream",
        "flow_network",
        ["downstream_id"],
    )
    op.create_index(
        "idx_is_stream",
        "flow_network",
        ["is_stream"],
        postgresql_where=sa.text("is_stream = TRUE"),
    )
    op.create_index(
        "idx_accumulation",
        "flow_network",
        ["flow_accumulation"],
    )

    # ===================
    # land_cover table
    # ===================
    op.create_table(
        "land_cover",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "geom",
            Geometry(geometry_type="MULTIPOLYGON", srid=2180),
            nullable=False,
            comment="Land cover polygon in EPSG:2180",
        ),
        sa.Column(
            "category",
            sa.String(50),
            nullable=False,
            comment="Simplified category: las, laka, grunt_orny, etc.",
        ),
        sa.Column(
            "cn_value",
            sa.Integer,
            nullable=False,
            comment="Curve Number (0-100) for AMC-II conditions",
        ),
        sa.Column(
            "imperviousness",
            sa.Float,
            nullable=True,
            comment="Imperviousness fraction (0.0-1.0)",
        ),
        sa.Column(
            "bdot_class",
            sa.String(20),
            nullable=True,
            comment="Original BDOT10k class code",
        ),
        # Check constraints
        sa.CheckConstraint(
            "cn_value >= 0 AND cn_value <= 100",
            name="valid_cn",
        ),
        sa.CheckConstraint(
            "imperviousness IS NULL OR (imperviousness >= 0 AND imperviousness <= 1)",
            name="valid_imperviousness",
        ),
        sa.CheckConstraint(
            "category IN ('las', 'łąka', 'grunt_orny', 'zabudowa_mieszkaniowa', "
            "'zabudowa_przemysłowa', 'droga', 'woda', 'inny')",
            name="valid_category",
        ),
        comment="Land cover from BDOT10k with CN values",
    )

    # Indexes for land_cover
    op.create_index(
        "idx_landcover_geom",
        "land_cover",
        ["geom"],
        postgresql_using="gist",
    )
    op.create_index(
        "idx_category",
        "land_cover",
        ["category"],
    )
    op.create_index(
        "idx_cn_value",
        "land_cover",
        ["cn_value"],
    )

    # ===================
    # stream_network table
    # ===================
    op.create_table(
        "stream_network",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "geom",
            Geometry(geometry_type="LINESTRING", srid=2180),
            nullable=False,
            comment="Stream line in EPSG:2180",
        ),
        sa.Column(
            "name",
            sa.String(100),
            nullable=True,
            comment="Stream name (NULL for unnamed)",
        ),
        sa.Column(
            "length_m",
            sa.Float,
            nullable=True,
            comment="Stream segment length [m]",
        ),
        sa.Column(
            "strahler_order",
            sa.Integer,
            nullable=True,
            comment="Strahler stream order",
        ),
        sa.Column(
            "source",
            sa.String(50),
            nullable=True,
            default="MPHP",
            comment="Data source",
        ),
        # Check constraints
        sa.CheckConstraint(
            "length_m IS NULL OR length_m > 0",
            name="positive_length",
        ),
        sa.CheckConstraint(
            "strahler_order IS NULL OR strahler_order > 0",
            name="valid_strahler",
        ),
        comment="Stream network from MPHP",
    )

    # Indexes for stream_network
    op.create_index(
        "idx_stream_geom",
        "stream_network",
        ["geom"],
        postgresql_using="gist",
    )
    op.create_index(
        "idx_stream_name",
        "stream_network",
        ["name"],
    )
    op.create_index(
        "idx_strahler_order",
        "stream_network",
        ["strahler_order"],
    )
    # Unique constraint to prevent duplicate stream segments
    op.create_index(
        "idx_stream_unique",
        "stream_network",
        [
            sa.text("COALESCE(name, '')"),
            sa.text("ST_GeoHash(ST_Transform(geom, 4326), 12)"),
        ],
        unique=True,
    )


def downgrade() -> None:
    """Drop core tables."""
    # stream_network
    op.drop_index("idx_stream_unique", table_name="stream_network")
    op.drop_index("idx_strahler_order", table_name="stream_network")
    op.drop_index("idx_stream_name", table_name="stream_network")
    op.drop_index("idx_stream_geom", table_name="stream_network")
    op.drop_table("stream_network")

    # land_cover
    op.drop_index("idx_cn_value", table_name="land_cover")
    op.drop_index("idx_category", table_name="land_cover")
    op.drop_index("idx_landcover_geom", table_name="land_cover")
    op.drop_table("land_cover")

    # flow_network
    op.drop_index("idx_accumulation", table_name="flow_network")
    op.drop_index("idx_is_stream", table_name="flow_network")
    op.drop_index("idx_downstream", table_name="flow_network")
    op.drop_index("idx_flow_geom", table_name="flow_network")
    op.drop_table("flow_network")
