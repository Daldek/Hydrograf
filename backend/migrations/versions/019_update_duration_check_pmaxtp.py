"""Update precipitation_data duration CHECK constraint to full PMAXTP range.

Replaces 6h/12h/24h with 45min/1.5h/3h to match IMGW PMAXTP available durations.
Also removes old data for durations no longer in the valid set.
"""

from alembic import op

revision = "019"
down_revision = "018"


def upgrade():
    # Remove data for durations that are no longer valid
    op.execute(
        "DELETE FROM precipitation_data "
        "WHERE duration IN ('6h', '12h', '24h')"
    )

    # Drop old constraint and create new one
    op.drop_constraint("valid_duration", "precipitation_data", type_="check")
    op.create_check_constraint(
        "valid_duration",
        "precipitation_data",
        "duration IN ('15min', '30min', '45min', '1h', '1.5h', '2h', '3h')",
    )


def downgrade():
    op.drop_constraint("valid_duration", "precipitation_data", type_="check")
    op.create_check_constraint(
        "valid_duration",
        "precipitation_data",
        "duration IN ('15min', '30min', '1h', '2h', '6h', '12h', '24h')",
    )
