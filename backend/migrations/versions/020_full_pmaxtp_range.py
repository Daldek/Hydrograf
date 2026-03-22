"""Expand precipitation_data to full PMAXTP range.

16 durations (5 min – 72 h) × 27 probabilities (0.01% – 99.9%) = 432 scenarios.
Changes probability column from INTEGER to DOUBLE PRECISION to support
fractional probabilities (0.01, 0.5, 98.5, etc.).
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"

# Full PMAXTP duration set
_ALL_DURATIONS = (
    "'5min','10min','15min','30min','45min','1h','1.5h','2h',"
    "'3h','6h','12h','18h','24h','36h','48h','72h'"
)

# Full PMAXTP probability set
_ALL_PROBABILITIES = (
    "0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,"
    "1,2,3,5,10,20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9"
)


def upgrade():
    # 1. Clear existing data (will be re-populated by preprocess script)
    op.execute("DELETE FROM precipitation_data")

    # 2. Drop constraints that reference the old column type
    op.drop_constraint("valid_duration", "precipitation_data", type_="check")
    op.drop_constraint("valid_probability", "precipitation_data", type_="check")
    op.drop_constraint(
        "unique_precipitation_scenario", "precipitation_data", type_="unique"
    )

    # 3. Change probability column from INTEGER to DOUBLE PRECISION
    op.alter_column(
        "precipitation_data",
        "probability",
        type_=sa.Float,
        existing_type=sa.Integer,
        existing_nullable=False,
    )

    # 4. Recreate constraints with full PMAXTP range
    op.create_check_constraint(
        "valid_duration",
        "precipitation_data",
        f"duration IN ({_ALL_DURATIONS})",
    )
    op.create_check_constraint(
        "valid_probability",
        "precipitation_data",
        f"probability IN ({_ALL_PROBABILITIES})",
    )

    # 5. Recreate unique constraint
    op.create_unique_constraint(
        "unique_precipitation_scenario",
        "precipitation_data",
        ["geom", "duration", "probability"],
    )


def downgrade():
    op.execute("DELETE FROM precipitation_data")
    op.drop_constraint("valid_duration", "precipitation_data", type_="check")
    op.drop_constraint("valid_probability", "precipitation_data", type_="check")
    op.drop_constraint(
        "unique_precipitation_scenario", "precipitation_data", type_="unique"
    )
    op.alter_column(
        "precipitation_data",
        "probability",
        type_=sa.Integer,
        existing_type=sa.Float,
        existing_nullable=False,
    )
    op.create_check_constraint(
        "valid_duration",
        "precipitation_data",
        "duration IN ('15min','30min','45min','1h','1.5h','2h','3h')",
    )
    op.create_check_constraint(
        "valid_probability",
        "precipitation_data",
        "probability IN (1, 2, 5, 10, 20, 50)",
    )
    op.create_unique_constraint(
        "unique_precipitation_scenario",
        "precipitation_data",
        ["geom", "duration", "probability"],
    )
