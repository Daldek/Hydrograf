"""
Coordinate transformation utilities.

Provides functions for transforming coordinates between WGS84 (EPSG:4326),
PL-1992 (EPSG:2180) and PL-2000 (EPSG:2176 to 2179, one per zone) coordinate
reference systems.
"""

import math
from typing import Any

import shapely
from pyproj import Transformer
from shapely.geometry import Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry

# PL-2000 zone -> EPSG code; zone n has its central meridian at 3n °E
PL2000_EPSG_BY_ZONE = {5: 2176, 6: 2177, 7: 2178, 8: 2179}

# Cached transformers (thread-safe in PyProj 3.0+)
_transformer_wgs84_to_pl1992: Transformer | None = None
_transformer_pl1992_to_wgs84: Transformer | None = None
_transformers_wgs84_to_pl2000: dict[int, Transformer] = {}


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


def pl2000_zone(longitude: float) -> int:
    """
    PL-2000 zone of a longitude.

    Zone n reaches 1.5° either side of its central meridian 3n °E: zone 5
    west of 16.5°, 6 from 16.5° to 19.5°, 7 from 19.5° to 22.5° and 8 from
    22.5° east. A point outside Poland gets the nearest of the four zones.

    Parameters
    ----------
    longitude : float
        Longitude in WGS84 (decimal degrees)

    Returns
    -------
    int
        Zone number, 5 to 8 (EPSG code in ``PL2000_EPSG_BY_ZONE``)
    """
    return min(max(math.floor((longitude + 1.5) / 3), 5), 8)


def transform_wgs84_to_pl2000(
    latitude: float, longitude: float
) -> tuple[int, float, float]:
    """
    Transform WGS84 coordinates to PL-2000, in the zone of the longitude.

    Parameters
    ----------
    latitude : float
        Latitude in WGS84 (decimal degrees)
    longitude : float
        Longitude in WGS84 (decimal degrees)

    Returns
    -------
    tuple[int, float, float]
        (zone, easting, northing): the zone (``pl2000_zone``) and the
        coordinates in metres; the easting (Y of Polish surveying) starts with
        the zone number

    Examples
    --------
    >>> zone, easting, northing = transform_wgs84_to_pl2000(52.23, 21.01)
    >>> print(f"zone {zone}: X {northing:.0f}, Y {easting:.0f}")
    zone 7: X 5788490, Y 7500683
    """
    zone = pl2000_zone(longitude)
    transformer = _transformers_wgs84_to_pl2000.get(zone)
    if transformer is None:
        transformer = Transformer.from_crs(
            "EPSG:4326", f"EPSG:{PL2000_EPSG_BY_ZONE[zone]}", always_xy=True
        )
        _transformers_wgs84_to_pl2000[zone] = transformer
    easting, northing = transformer.transform(longitude, latitude)
    return zone, easting, northing


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

    def transform_coords(coords: list[Any]) -> list[Any]:
        """Transform list of coordinate tuples."""
        return [transformer.transform(x, y) for x, y in coords]

    # Transform exterior ring
    exterior = transform_coords(polygon.exterior.coords)

    # Transform interior rings (holes)
    interiors = [transform_coords(ring.coords) for ring in polygon.interiors]

    return Polygon(exterior, interiors)


def transform_geometry_pl1992_to_wgs84(geometry: BaseGeometry) -> BaseGeometry:
    """
    Transform any Shapely geometry from PL-1992 to WGS84 (longitude, latitude).

    Parameters
    ----------
    geometry : BaseGeometry
        Geometry in EPSG:2180 (PL-1992): a point, line, polygon or multipart one

    Returns
    -------
    BaseGeometry
        The same geometry in EPSG:4326 (WGS84)
    """
    transformer = _get_transformer_pl1992_to_wgs84()
    return shapely.transform(geometry, transformer.transform, interleaved=False)


def transform_polygon_wgs84_to_pl1992(polygon: Polygon) -> Polygon:
    """
    Transform Polygon from WGS84 to PL-1992.

    Parameters
    ----------
    polygon : Polygon
        Shapely Polygon in EPSG:4326 (WGS84), coordinates as (lon, lat)

    Returns
    -------
    Polygon
        Shapely Polygon in EPSG:2180 (PL-1992)
    """
    transformer = _get_transformer_wgs84_to_pl1992()

    def transform_coords(coords: list[Any]) -> list[Any]:
        """Transform list of coordinate tuples."""
        return [transformer.transform(lon, lat) for lon, lat in coords]

    exterior = transform_coords(polygon.exterior.coords)
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
