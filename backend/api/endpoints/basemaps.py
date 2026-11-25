"""
The base maps the map offers (Nogat DEV-15.15, ADR-089).

The page draws them with the kit's `nogat-basemaps.js` (frontend/nogat/); the entries
come from the kit's catalogue and the settings of the deployment (core/basemaps.py).
"""

from typing import Any

from fastapi import APIRouter

from core.basemaps import current_basemaps
from models.schemas import Basemap

router = APIRouter()


@router.get("/basemaps", response_model=list[Basemap], response_model_exclude_none=True)
def basemap_entries() -> list[dict[str, Any]]:
    """
    Return the base maps the map's page offers, in the order of its menu.

    The entries of Nogat's catalogue `nogat-basemaps.json` that the setting
    `basemaps` allows, in the catalogue's order and as it writes them, but for the
    `url` and `origin` of a copy the deployment serves (`basemap_mirrors`); then the
    deployment's own base maps (`basemap_extra`), with no `minzoom`, `maxzoom`,
    `bounds` or `blocks`. The page draws them with the kit; `[]` means no base map.
    """
    return current_basemaps()
