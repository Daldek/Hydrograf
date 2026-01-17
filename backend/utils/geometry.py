"""
Coordinate transformation utilities.

Provides functions for transforming coordinates between WGS84 (EPSG:4326)
and PL-1992 (EPSG:2180) coordinate reference systems.
"""

from typing import Any

from pyproj import Transformer
from shapely.geometry import Point, Polygon, mapping

# Cached transformers (thread-safe in PyProj 3.0+)
_transformer_wgs84_to_pl1992: Transformer | None = None
_transformer_pl1992_to_wgs84: Transformer | None = None


def _get_transformer_wgs84_to_pl1992() -> Transformer:
    """
    Get cached WGS84 -> PL-1992 transformer.

    Returns
    -------
    Transformer
        PyProj transformer for WGS84 to PL-1992
    """
    global _transformer_wgs84_to_pl1992
    if _transformer_wgs84_to_pl1992 is None:
        _transformer_wgs84_to_pl1992 = Transformer.from_crs(
            "EPSG:4326", "EPSG:2180", always_xy=True
        )
    return _transformer_wgs84_to_pl1992


def _get_transformer_pl1992_to_wgs84() -> Transformer:
    """
    Get cached PL-1992 -> WGS84 transformer.

    Returns
    -------
    Transformer
        PyProj transformer for PL-1992 to WGS84
    """
    global _transformer_pl1992_to_wgs84
    if _transformer_pl1992_to_wgs84 is None:
        _transformer_pl1992_to_wgs84 = Transformer.from_crs(
            "EPSG:2180", "EPSG:4326", always_xy=True
        )
    return _transformer_pl1992_to_wgs84


def transform_wgs84_to_pl1992(latitude: float, longitude: float) -> Point:
    """
    Transform WGS84 coordinates to PL-1992 Point.

    Parameters
    ----------
    latitude : float
        Latitude in WGS84 (decimal degrees)
    longitude : float
        Longitude in WGS84 (decimal degrees)

    Returns
    -------
    Point
        Shapely Point in EPSG:2180 (PL-1992)

    Examples
    --------
    >>> point = transform_wgs84_to_pl1992(52.23, 21.01)
    >>> print(f"X: {point.x:.0f}, Y: {point.y:.0f}")
    X: 639139, Y: 486706
    """
    transformer = _get_transformer_wgs84_to_pl1992()
    # PyProj with always_xy=True expects (lon, lat) order
    x, y = transformer.transform(longitude, latitude)
    return Point(x, y)


def transform_pl1992_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """
    Transform PL-1992 coordinates to WGS84.

    Parameters
    ----------
    x : float
        X coordinate in EPSG:2180 (PL-1992)
    y : float
        Y coordinate in EPSG:2180 (PL-1992)

    Returns
    -------
    tuple[float, float]
        (longitude, latitude) in WGS84

    Examples
    --------
    >>> lon, lat = transform_pl1992_to_wgs84(639139, 486706)
    >>> print(f"Lat: {lat:.2f}, Lon: {lon:.2f}")
    Lat: 52.23, Lon: 21.01
    """
    transformer = _get_transformer_pl1992_to_wgs84()
    lon, lat = transformer.transform(x, y)
    return lon, lat


def transform_polygon_pl1992_to_wgs84(polygon: Polygon) -> Polygon:
    """
    Transform Polygon from PL-1992 to WGS84.

    Parameters
    ----------
    polygon : Polygon
        Shapely Polygon in EPSG:2180 (PL-1992)

    Returns
    -------
    Polygon
        Shapely Polygon in EPSG:4326 (WGS84)

    Examples
    --------
    >>> from shapely.geometry import Polygon
    >>> poly_2180 = Polygon([(500000, 600000), (500100, 600000),
    ...                       (500100, 600100), (500000, 600100)])
    >>> poly_wgs84 = transform_polygon_pl1992_to_wgs84(poly_2180)
    """
    transformer = _get_transformer_pl1992_to_wgs84()

    def transform_coords(coords: list) -> list:
        """Transform list of coordinate tuples."""
        return [transformer.transform(x, y) for x, y in coords]

    # Transform exterior ring
    exterior = transform_coords(polygon.exterior.coords)

    # Transform interior rings (holes)
    interiors = [transform_coords(ring.coords) for ring in polygon.interiors]

    return Polygon(exterior, interiors)


def polygon_to_geojson_feature(
    polygon: Polygon, properties: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Convert Shapely Polygon to GeoJSON Feature.

    Parameters
    ----------
    polygon : Polygon
        Shapely Polygon geometry
    properties : dict, optional
        Properties to include in the Feature

    Returns
    -------
    dict
        GeoJSON Feature dictionary

    Examples
    --------
    >>> from shapely.geometry import Polygon
    >>> poly = Polygon([(21.0, 52.0), (21.1, 52.0),
    ...                 (21.1, 52.1), (21.0, 52.1)])
    >>> feature = polygon_to_geojson_feature(poly, {"area_km2": 45.3})
    >>> print(feature["type"])
    Feature
    """
    return {
        "type": "Feature",
        "geometry": mapping(polygon),
        "properties": properties or {},
    }
