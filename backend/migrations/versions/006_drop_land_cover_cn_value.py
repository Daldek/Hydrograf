"""Drop land_cover.cn_value: the CN is that of the soil-cover complexes (ADR-075).

The CN of a land cover row depends on its soil group: it is computed from the
category and the source (``bdot_class``) of the row on each hydrologic soil group of
``soil_hsg`` (``core/cn_tables.py``), so the one CN per category that ``cn_value``
held is read by nothing and the import no longer writes it (ADR-074, ADR-075). The
check ``valid_cn`` and the index ``idx_cn_value`` go with the column.

The downgrade restores the column, filled with the CN of each category that the
import wrote until then, with its check and its index.

Revision ID: 006
Create Date: 2026-11-08
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

# The CN for AMC II of each category of land_cover that cn_value held
_CATEGORY_CN = {
    "las": 60,
    "łąka": 70,
    "grunt_orny": 78,
    "zabudowa_mieszkaniowa": 85,
    "zabudowa_przemysłowa": 92,
    "droga": 98,
    "woda": 100,
    "inny": 75,
}


def upgrade() -> None:
    """Drop the column with its check and its index."""
    op.execute("ALTER TABLE land_cover DROP COLUMN cn_value")


def downgrade() -> None:
    """Restore the column with the CN of each category, its check and its index."""
    op.execute("ALTER TABLE land_cover ADD COLUMN cn_value INTEGER")
    cases = " ".join(
        f"WHEN '{category}' THEN {cn}" for category, cn in _CATEGORY_CN.items()
    )
    op.execute(f"UPDATE land_cover SET cn_value = CASE category {cases} END")
    op.execute("ALTER TABLE land_cover ALTER COLUMN cn_value SET NOT NULL")
    op.execute(
        "ALTER TABLE land_cover ADD CONSTRAINT valid_cn "
        "CHECK (cn_value >= 0 AND cn_value <= 100)"
    )
    op.execute("CREATE INDEX idx_cn_value ON land_cover USING btree (cn_value)")
