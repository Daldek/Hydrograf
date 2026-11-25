"""
The commands ``layers availability`` and ``layers thresholds`` (ADR-091).

What the layers panel of the map needs to know of the server's data: which optional
layers hold any, and the thresholds of the precomputed stream network and
sub-catchments, from which a delineation's ``threshold_m2`` is chosen.
"""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.envelope import Outcome
from models.schemas import LayerAvailability, LayerThresholds, NoOptions

logger = logging.getLogger(__name__)


def layer_availability(options: NoOptions, db: Session) -> Outcome:
    """
    Report which optional map layers have data: ``layers availability``.

    Public, read-only; lets the layers panel hide entries whose tiles
    would always be empty.

    Returns
    -------
    Outcome
        ``LayerAvailability``: ``sewer`` is True when the sewer network or its nodes
        hold at least one row (False when the tables cannot be read).
    """
    try:
        sewer = bool(
            db.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM sewer_network)"
                    " OR EXISTS (SELECT 1 FROM sewer_nodes)"
                )
            ).scalar()
        )
    except Exception as e:
        logger.warning("Sewer availability check failed: %s", e)
        db.rollback()
        sewer = False
    return Outcome(LayerAvailability(sewer=sewer))


def layer_thresholds(options: NoOptions, db: Session) -> Outcome:
    """
    List the flow accumulation thresholds of the data: ``layers thresholds``.

    Queries distinct threshold_m2 from stream_network and stream_catchments
    so the frontend can build dropdown options dynamically.

    Returns
    -------
    Outcome
        ``LayerThresholds``; ``catchments`` is empty while stream_catchments does not
        exist yet.
    """
    streams_rows = db.execute(
        text("SELECT DISTINCT threshold_m2 FROM stream_network ORDER BY threshold_m2")
    ).fetchall()
    streams = [row[0] for row in streams_rows]

    try:
        catchments_rows = db.execute(
            text(
                "SELECT DISTINCT threshold_m2"
                " FROM stream_catchments ORDER BY threshold_m2"
            )
        ).fetchall()
        catchments = [row[0] for row in catchments_rows]
    except Exception:
        catchments = []

    return Outcome(LayerThresholds(streams=streams, catchments=catchments))
