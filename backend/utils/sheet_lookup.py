"""NMT sheet lookup for a point + buffer, delegating to Kartograf.

The removed local godlo-math implementation reimplemented the Polish
map-sheet (godlo) subdivision directly and got the 1:10000 level wrong
(2 rows x 4 cols instead of Kartograf/GUGiK's nested 2x2).
sheets_for_point_buffer() replaces that with a thin wrapper around
kartograf.find_sheets_for_bbox(), which implements the subdivision
correctly.
"""

from kartograf import BBox, find_sheets_for_bbox

from utils.geometry import transform_wgs84_to_pl1992


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
    center = transform_wgs84_to_pl1992(lat, lon)
    buffer_m = buffer_km * 1000

    bbox = BBox(
        min_x=center.x - buffer_m,
        min_y=center.y - buffer_m,
        max_x=center.x + buffer_m,
        max_y=center.y + buffer_m,
        crs="EPSG:2180",
    )

    return sorted(find_sheets_for_bbox(bbox, target_scale=scale))
