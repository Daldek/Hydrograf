"""Feedback table for tester submissions.

Revision ID: 002
Create Date: 2026-08-02
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE feedback (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 5000),
            contact TEXT CHECK (length(contact) <= 200),
            page_url TEXT,
            user_agent TEXT,
            diagnostics JSONB,
            is_read BOOLEAN NOT NULL DEFAULT false
        )
    """)
    op.execute(
        "CREATE INDEX idx_feedback_created_at ON feedback USING btree (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback CASCADE")
