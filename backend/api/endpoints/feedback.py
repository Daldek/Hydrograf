"""
„Zgłoś uwagę”: reports of the interface's users (Nogat DEV-15.12, ADR-084).

A report is its text and the context the interface adds itself (the view, the station,
the view's parameters) with the app version the server adds; never a contact, an IP
address or the User-Agent. The operator lists, marks and deletes the reports at
`/api/admin/feedback[/{id}]` (X-Admin-Key, and Cloudflare Access in front of it) and
deletes each once handled.

Reports sent with the form before ADR-084 keep what they were sent with (contact, page
URL, User-Agent, diagnostics) in columns no new report fills; the admin list gives them
as `legacy`, so that the operator can handle them, until migration of a later version
drops those columns.
"""

import json
import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from core.database import get_db
from core.errors import HydrografError, InternalError, NotFoundError
from core.version import get_version
from models.schemas import FeedbackRequest, FeedbackResponse, FeedbackUpdate

logger = logging.getLogger(__name__)
router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(verify_admin_key)])

# The columns of the form before ADR-084, which only its reports fill
LEGACY_COLUMNS = ("contact", "page_url", "user_agent", "diagnostics")


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    """
    Store a report of „Zgłoś uwagę”.

    Parameters
    ----------
    payload : FeedbackRequest
        The text and the view's context; any other member is refused (400).

    Returns
    -------
    FeedbackResponse
        Id of the created report
    """
    context = {**payload.context.model_dump(), "app_version": get_version()}
    try:
        row = db.execute(
            text("""
                INSERT INTO feedback (message, context)
                VALUES (:message, CAST(:context AS JSONB))
                RETURNING id
            """),
            {"message": payload.message, "context": json.dumps(context)},
        ).fetchone()
        db.commit()
        if row is None:
            raise RuntimeError("INSERT INTO feedback RETURNING id returned no row")
        return FeedbackResponse(id=row.id, status="ok")
    except Exception as e:
        db.rollback()
        logger.error("Error storing feedback: %s", type(e).__name__, exc_info=True)
        raise InternalError(
            "feedback_store_failed", reason="feedback_store_failed"
        ) from e


@admin_router.get("/feedback")
def list_feedback(
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List the reports, newest first, with the unread count.

    Each item has `id`, `created_at`, `message`, `context` (null for a report of the
    form before ADR-084), `is_read` and `legacy`: null for a new report, else the
    `contact`, `page_url`, `user_agent` and `diagnostics` it was sent with.
    """
    try:
        rows = db.execute(
            text("""
                SELECT id, created_at, message, context, is_read,
                       contact, page_url, user_agent, diagnostics
                FROM feedback
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        ).fetchall()
        counts = db.execute(
            text("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE NOT is_read) AS unread
                FROM feedback
            """)
        ).fetchone()
        if counts is None:
            raise RuntimeError("SELECT COUNT(*) returned no row")
        items = [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "message": r.message,
                "context": r.context,
                "is_read": r.is_read,
                "legacy": _legacy(r),
            }
            for r in rows
        ]
        return {"items": items, "total": counts.total, "unread_count": counts.unread}
    except Exception as e:
        logger.error("Error listing feedback: %s", type(e).__name__, exc_info=True)
        raise InternalError(
            "feedback_list_failed", reason="feedback_list_failed"
        ) from e


def _legacy(row: Any) -> dict[str, Any] | None:
    """Return what a report of the form before ADR-084 was sent with, or None."""
    values = {column: getattr(row, column) for column in LEGACY_COLUMNS}
    return values if any(v is not None for v in values.values()) else None


@admin_router.patch("/feedback/{feedback_id}")
def update_feedback(
    feedback_id: int, body: FeedbackUpdate, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Mark a feedback submission as read or unread."""
    try:
        result = db.execute(
            text("UPDATE feedback SET is_read = :is_read WHERE id = :id"),
            {"id": feedback_id, "is_read": body.is_read},
        )
        db.commit()
        if cast("CursorResult[Any]", result).rowcount == 0:
            raise NotFoundError(
                "feedback_not_found",
                reason="feedback_not_found",
                feedback_id=feedback_id,
            )
        return {"status": "ok"}
    except HydrografError:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating feedback: {e}", exc_info=True)
        raise InternalError(
            "feedback_update_failed", reason="feedback_update_failed"
        ) from e


@admin_router.delete("/feedback/{feedback_id}")
def delete_feedback(feedback_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    """Delete a feedback submission. Returns JSON (admin-api.js expects it)."""
    try:
        result = db.execute(
            text("DELETE FROM feedback WHERE id = :id"),
            {"id": feedback_id},
        )
        db.commit()
        if cast("CursorResult[Any]", result).rowcount == 0:
            raise NotFoundError(
                "feedback_not_found",
                reason="feedback_not_found",
                feedback_id=feedback_id,
            )
        return {"status": "deleted"}
    except HydrografError:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting feedback: {e}", exc_info=True)
        raise InternalError(
            "feedback_delete_failed", reason="feedback_delete_failed"
        ) from e
