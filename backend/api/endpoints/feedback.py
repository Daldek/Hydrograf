"""
Feedback endpoint.

Accepts tester feedback with optional session diagnostics and stores
it in the feedback table.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db
from models.schemas import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)
router = APIRouter()


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
