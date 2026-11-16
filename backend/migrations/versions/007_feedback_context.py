"""Reports of „Zgłoś uwagę” with a context and no personal data (ADR-084).

A report is its text and the context the interface adds itself (Nogat DEV-15.12): the
view, the station, the view's parameters and the app version, in the new column
``context``. The columns of the form before ADR-084 (``contact``, ``page_url``,
``user_agent``, ``diagnostics``) stay with what the reports sent with that form hold,
because the operator decides about those reports; no new report fills them, and a
later migration drops them once those reports are handled and deleted.

The downgrade drops ``context``.

Revision ID: 007
Create Date: 2026-11-13
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

_LEGACY = "Form before ADR-084 only; no new report fills it (Nogat DEV-15.12)."


def upgrade() -> None:
    """Add the column ``context`` and mark the columns of the old form."""
    op.execute("ALTER TABLE feedback ADD COLUMN context JSONB")
    op.execute(
        "COMMENT ON COLUMN feedback.context IS 'The view, station, parameters and "
        "app version of the report (Nogat DEV-15.12, ADR-084).'"
    )
    for column in ("contact", "page_url", "user_agent", "diagnostics"):
        op.execute(f"COMMENT ON COLUMN feedback.{column} IS '{_LEGACY}'")


def downgrade() -> None:
    """Drop the column ``context`` and the comments."""
    for column in ("contact", "page_url", "user_agent", "diagnostics"):
        op.execute(f"COMMENT ON COLUMN feedback.{column} IS NULL")
    op.execute("ALTER TABLE feedback DROP COLUMN context")
