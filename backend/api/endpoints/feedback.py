"""
Feedback endpoint.

Accepts tester feedback with optional session diagnostics and stores
it in the feedback table.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from core.database import get_db
from models.schemas import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)
router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(verify_admin_key)])


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    payload: FeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    """
    Store a feedback submission.

    Parameters
    ----------
    payload : FeedbackRequest
        Feedback text with optional contact and session diagnostics

    Returns
    -------
    FeedbackResponse
        Id of the created record
    """
    try:
        query = text("""
            INSERT INTO feedback
            (message, contact, page_url, user_agent, diagnostics)
            VALUES (:message, :contact, :page_url, :user_agent,
                    CAST(:diagnostics AS JSONB))
            RETURNING id
        """)
        params = {
            "message": payload.message,
            "contact": payload.contact,
            "page_url": payload.page_url,
            "user_agent": request.headers.get("user-agent", "")[:500],
            "diagnostics": (
                json.dumps(payload.diagnostics)
                if payload.diagnostics is not None
                else None
            ),
        }
        row = db.execute(query, params).fetchone()
        db.commit()
        return FeedbackResponse(id=row.id, status="ok")
    except Exception as e:
        db.rollback()
        logger.error(f"Error storing feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error storing feedback",
        ) from e


@admin_router.get("/feedback")
def list_feedback(
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List feedback submissions, newest first, with unread count."""
    try:
        rows = db.execute(
            text("""
                SELECT id, created_at, message, contact, page_url,
                       user_agent, diagnostics, is_read
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
        items = [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "message": r.message,
                "contact": r.contact,
                "page_url": r.page_url,
                "user_agent": r.user_agent,
                "diagnostics": r.diagnostics,
                "is_read": r.is_read,
            }
            for r in rows
        ]
        return {"items": items, "total": counts.total, "unread_count": counts.unread}
    except Exception as e:
        logger.error(f"Error listing feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error listing feedback",
        ) from e


@admin_router.post("/feedback/{feedback_id}/read")
def mark_feedback_read(
    feedback_id: int, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Mark a feedback submission as read."""
    try:
        result = db.execute(
            text("UPDATE feedback SET is_read = true WHERE id = :id"),
            {"id": feedback_id},
        )
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Feedback not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error marking feedback read: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error updating feedback",
        ) from e


@admin_router.delete("/feedback/{feedback_id}")
def delete_feedback(
    feedback_id: int, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Delete a feedback submission. Returns JSON (admin-api.js expects it)."""
    try:
        result = db.execute(
            text("DELETE FROM feedback WHERE id = :id"),
            {"id": feedback_id},
        )
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Feedback not found")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error deleting feedback",
        ) from e
