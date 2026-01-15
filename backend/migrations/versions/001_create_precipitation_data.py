"""
Create precipitation_data table for IMGW PMAXTP data.

Revision ID: 001
Revises:
Create Date: 2026-01-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create precipitation_data table.

    Stores IMGW PMAXTP data for 42 rainfall scenarios:
    - 7 durations: 15min, 30min, 1h, 2h, 6h, 12h, 24h
    - 6 probabilities: 1%, 2%, 5%, 10%, 20%, 50%
    """
    # Ensure PostGIS extension is enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "precipitation_data",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "geom",
            Geometry(geometry_type="POINT", srid=2180),
            nullable=False,
            comment="Point location in EPSG:2180 (PL-1992)",
        ),
        sa.Column(
            "duration",
            sa.String(10),
            nullable=False,
            comment="Rainfall duration: 15min, 30min, 1h, 2h, 6h, 12h, 24h",
        ),
        sa.Column(
            "probability",
            sa.Integer,
            nullable=False,
            comment="Exceedance probability [%]: 1, 2, 5, 10, 20, 50",
        ),
        sa.Column(
            "precipitation_mm",
            sa.Float,
            nullable=False,
            comment="Rainfall depth [mm]",
        ),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            comment="Data source: IMGW_PMAXTP (atlas), IMGW_HISTORICAL (own analysis)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=True,
            server_default=sa.func.current_timestamp(),
            comment="Last update timestamp",
        ),
        # Check constraints
        sa.CheckConstraint(
            "duration IN ('15min', '30min', '1h', '2h', '6h', '12h', '24h')",
            name="valid_duration",
        ),
        sa.CheckConstraint(
            "probability IN (1, 2, 5, 10, 20, 50)",
            name="valid_probability",
        ),
        sa.CheckConstraint(
            "precipitation_mm >= 0",
            name="positive_precipitation",
        ),
        # Unique constraint for scenario
        sa.UniqueConstraint(
            "geom", "duration", "probability",
            name="unique_precipitation_scenario",
        ),
        comment="IMGW PMAXTP rainfall data for hydrological analysis",
    )

    # Create spatial index (GIST) for geometry queries
    op.create_index(
        "idx_precipitation_geom",
        "precipitation_data",
        ["geom"],
        postgresql_using="gist",
    )

    # Create composite index for scenario lookups
    op.create_index(
        "idx_precipitation_scenario",
        "precipitation_data",
        ["duration", "probability"],
    )

    # Create individual indexes for filtering
    op.create_index(
        "idx_precipitation_duration",
        "precipitation_data",
        ["duration"],
    )

    op.create_index(
        "idx_precipitation_probability",
        "precipitation_data",
        ["probability"],
    )


def downgrade() -> None:
    """Drop precipitation_data table."""
    op.drop_index("idx_precipitation_probability", table_name="precipitation_data")
    op.drop_index("idx_precipitation_duration", table_name="precipitation_data")
    op.drop_index("idx_precipitation_scenario", table_name="precipitation_data")
    op.drop_index("idx_precipitation_geom", table_name="precipitation_data")
    op.drop_table("precipitation_data")
