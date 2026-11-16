"""NMT sheet lookup for a point + buffer, delegating to Kartograf.

The removed local godlo-math implementation reimplemented the Polish
map-sheet (godlo) subdivision directly and got the 1:10000 level wrong
(2 rows x 4 cols instead of Kartograf/GUGiK's nested 2x2).
sheets_for_point_buffer() replaces that with a thin wrapper around
kartograf.find_sheets_for_bbox(), which implements the subdivision
correctly. point_buffer_bbox() is the area it asks about, which the land cover
downloads use too.
"""

from kartograf import BBox, find_sheets_for_bbox

from utils.geometry import transform_wgs84_to_pl1992
from utils.kartograf_store import SHEET_SYSTEM


def point_buffer_bbox(lat: float, lon: float, buffer_km: float) -> BBox:
    """
    Return the square of ``buffer_km`` around a point, in EPSG:2180.

    Parameters
    ----------
    lat : float
        Center latitude (WGS84)
    lon : float
        Center longitude (WGS84)
    buffer_km : float
        Buffer radius in kilometers (half of the side of the square)

    Returns
    -------
    BBox
        The area, as a Kartograf bounding box in EPSG:2180
    """
    center = transform_wgs84_to_pl1992(lat, lon)
    buffer_m = buffer_km * 1000

    return BBox(
        min_x=center.x - buffer_m,
        min_y=center.y - buffer_m,
        max_x=center.x + buffer_m,
        max_y=center.y + buffer_m,
        crs="EPSG:2180",
    )


def sheets_for_point_buffer(
    lat: float, lon: float, buffer_km: float, scale: str = "1:10000"
) -> list[str]:
    """
    Find sheet codes (godla) covering the area around a point.

    Parameters
    ----------
    lat : float
        Center latitude (WGS84)
    lon : float
        Center longitude (WGS84)
    buffer_km : float
        Buffer radius in kilometers
    scale : str
        Target scale (default "1:10000")

    Returns
    -------
    list[str]
        Sorted list of sheet codes covering the buffered area
    """
    bbox = point_buffer_bbox(lat, lon, buffer_km)

    return sorted(
        find_sheets_for_bbox(bbox, target_scale=scale, sheet_system=SHEET_SYSTEM)
    )
