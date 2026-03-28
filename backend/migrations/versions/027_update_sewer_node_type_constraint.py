"""Update sewer_nodes node_type constraint: replace 'isolated' with 'storage'.

Revision ID: 027_update_node_type
Revises: 026
Create Date: 2026-03-27
"""

from alembic import op

revision = "027_update_node_type"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE sewer_nodes SET node_type = 'junction' "
        "WHERE node_type = 'isolated'"
    )
    op.execute("ALTER TABLE sewer_nodes DROP CONSTRAINT IF EXISTS chk_node_type")
    op.execute(
        "ALTER TABLE sewer_nodes ADD CONSTRAINT chk_node_type "
        "CHECK (node_type IN ('inlet', 'outlet', 'junction', 'storage'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sewer_nodes SET node_type = 'junction' "
        "WHERE node_type = 'storage'"
    )
    op.execute("ALTER TABLE sewer_nodes DROP CONSTRAINT IF EXISTS chk_node_type")
    op.execute(
        "ALTER TABLE sewer_nodes ADD CONSTRAINT chk_node_type "
        "CHECK (node_type IN ('inlet', 'outlet', 'junction', 'isolated'))"
    )
