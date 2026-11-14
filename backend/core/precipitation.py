"""
PMAXTP design depths from the local grid of ``precipitation_data``.

The grid holds the PMAXTP quantiles (IMGW-PIB) sampled at points every few km
(``scripts/preprocess_precipitation.py``). The design depth of a watershed is its
mean over the watershed by Thiessen polygons of the grid points, the method of the
Polish methodology for design floods (ADR-069): :func:`thiessen_cells` weighs the
points once per watershed and :func:`areal_depth` averages the depths of a scenario.
Without a watershed boundary the depth is interpolated at a point from the four
nearest grid points by inverse distance weighting (:func:`point_depth`).
"""

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import shapely
from hydrolog.precipitation import Station, inverse_distance_weighting
from hydrolog.precipitation import thiessen_polygons as hydrolog_thiessen
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Margin around the watershed searched for grid points whose Thiessen polygons can
# reach it. Every place lies at most half a cell diagonal (s/sqrt(2)) from its nearest
# point of a regular grid of spacing s, so a margin of s is enough; 5 km holds for
# grids up to 7 km (the default spacing is 2 km, `--spacing` of
# scripts.preprocess_precipitation).
THIESSEN_SEARCH_M = 5000.0

# A grid point given back to areal_depth matches a point of the table within this
# distance (the response rounds coordinates to 0.01 m)
GRID_POINT_TOLERANCE_M = 1.0

# Points of the inverse distance weighting at a point, and its power
IDW_NEIGHBOURS = 4
IDW_POWER = 2.0


@dataclass(frozen=True)
class ThiessenCell:
    """A grid point and the area of its Thiessen polygon inside a watershed."""

    easting_m: float
    northing_m: float
    area_km2: float


@dataclass(frozen=True)
class GridPointDepth:
    """A grid point used for a design depth, with its depth and weight.

    ``area_km2`` is set for the Thiessen mean (the polygon inside the watershed),
    ``distance_m`` for the interpolation at a point.
    """

    easting_m: float
    northing_m: float
    precipitation_mm: float
    weight: float
    area_km2: float | None = None
    distance_m: float | None = None


@dataclass(frozen=True)
class DesignDepth:
    """A PMAXTP design depth and the grid points it was computed from."""

    precipitation_mm: float
    interpolation: Literal["thiessen", "idw"]
    points: tuple[GridPointDepth, ...]


# Valid duration values (full PMAXTP range: 5 min – 72 h)
VALID_DURATIONS_MIN = {
    5,
    10,
    15,
    30,
    45,
    60,
    90,
    120,
    180,
    360,
    720,
    1080,
    1440,
    2160,
    2880,
    4320,
}
VALID_DURATIONS_STR = {
    "5min",
    "10min",
    "15min",
    "30min",
    "45min",
    "1h",
    "1.5h",
    "2h",
    "3h",
    "6h",
    "12h",
    "18h",
    "24h",
    "36h",
    "48h",
    "72h",
}

# Valid probability values (full PMAXTP range)
VALID_PROBABILITIES = {
    0.01,
    0.02,
    0.03,
    0.05,
    0.1,
    0.2,
    0.3,
    0.5,
    1,
    2,
    3,
    5,
    10,
    20,
    30,
    40,
    50,
    60,
    70,
    80,
    90,
    95,
    98,
    98.5,
    99,
    99.5,
    99.9,
}

# Duration mapping: minutes -> database string
DURATION_MIN_TO_STR = {
    5: "5min",
    10: "10min",
    15: "15min",
    30: "30min",
    45: "45min",
    60: "1h",
    90: "1.5h",
    120: "2h",
    180: "3h",
    360: "6h",
    720: "12h",
    1080: "18h",
    1440: "24h",
    2160: "36h",
    2880: "48h",
    4320: "72h",
}

# Duration mapping: string -> minutes
DURATION_STR_TO_MIN = {v: k for k, v in DURATION_MIN_TO_STR.items()}


def validate_duration(duration: int | str) -> str:
    """
    Validate and normalize duration parameter.

    Parameters
    ----------
    duration : int | str
        Duration in minutes (5–4320, full PMAXTP range)
        or as string ('5min'...'72h')

    Returns
    -------
    str
        Normalized duration string for database query

    Raises
    ------
    ValueError
        If duration is invalid
    """
    if isinstance(duration, int):
        if duration not in VALID_DURATIONS_MIN:
            raise ValueError(
                f"Invalid duration: {duration}. "
                f"Must be one of {sorted(VALID_DURATIONS_MIN)}"
            )
        return DURATION_MIN_TO_STR[duration]

    if isinstance(duration, str):
        if duration not in VALID_DURATIONS_STR:
            raise ValueError(
                f"Invalid duration: {duration}. "
                f"Must be one of {sorted(VALID_DURATIONS_STR)}"
            )
        return duration

    raise ValueError(f"Duration must be int or str, got {type(duration)}")


def validate_probability(probability: int | float) -> float:
    """
    Validate probability parameter.

    Parameters
    ----------
    probability : int | float
        Exceedance probability [%] (full PMAXTP range)

    Returns
    -------
    float
        Validated probability

    Raises
    ------
    ValueError
        If probability is invalid
    """
    prob_float = float(probability)
    if prob_float not in VALID_PROBABILITIES:
        raise ValueError(
            f"Invalid probability: {probability}. "
            f"Must be one of {sorted(VALID_PROBABILITIES)}"
        )
    return prob_float


class UnknownGridPointError(ValueError):
    """A point given as a grid point is not a point of ``precipitation_data``."""

    def __init__(self, easting_m: float, northing_m: float) -> None:
        self.easting_m = easting_m
        self.northing_m = northing_m
        super().__init__(
            f"No PMAXTP grid point at ({easting_m:.2f}, {northing_m:.2f}) EPSG:2180"
        )


def thiessen_cells(boundary_2180: BaseGeometry, db: Session) -> list[ThiessenCell]:
    """Weigh the PMAXTP grid points over a watershed by Thiessen polygons.

    The Thiessen (Voronoi) polygon of a grid point holds the places nearer to it than
    to any other point; its area inside the watershed is the point's share of the
    watershed mean (the method of equal-rainfall polygons, ADR-069).

    Parameters
    ----------
    boundary_2180 : BaseGeometry
        Watershed boundary (Polygon or MultiPolygon) in EPSG:2180
    db : Session
        SQLAlchemy database session

    Returns
    -------
    list[ThiessenCell]
        The grid points whose polygons overlap the watershed, with the overlap
        [km²]; empty when no grid point lies within THIESSEN_SEARCH_M of it
    """
    x0, y0, x1, y1 = boundary_2180.bounds
    rows = db.execute(
        text("""
            SELECT DISTINCT ST_X(geom) AS x, ST_Y(geom) AS y
            FROM precipitation_data
            WHERE geom && ST_Expand(
                ST_MakeEnvelope(:x0, :y0, :x1, :y1, 2180), :margin
            )
            ORDER BY x, y
        """),
        {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "margin": THIESSEN_SEARCH_M},
    ).fetchall()
    if not rows:
        return []
    coords = np.array([(row.x, row.y) for row in rows], dtype=np.float64)
    if len(coords) == 1:
        x, y = coords[0]
        return [ThiessenCell(float(x), float(y), boundary_2180.area / 1e6)]
    # ordered=True: the i-th polygon belongs to the i-th point
    polygons = shapely.get_parts(
        shapely.voronoi_polygons(
            shapely.multipoints(coords),
            extend_to=shapely.box(x0, y0, x1, y1).buffer(2 * THIESSEN_SEARCH_M),
            ordered=True,
        )
    )
    areas_m2 = shapely.area(shapely.intersection(polygons, boundary_2180))
    return [
        ThiessenCell(float(x), float(y), float(area_m2) / 1e6)
        for (x, y), area_m2 in zip(coords, areas_m2, strict=True)
        if area_m2 > 0
    ]


def areal_depth(
    cells: list[ThiessenCell],
    duration: int | str,
    probability: int | float,
    db: Session,
) -> DesignDepth | None:
    """Watershed mean of a PMAXTP scenario over the Thiessen polygons of its grid.

    The mean is Hydrolog's ``thiessen_polygons``: the depth of each grid point
    weighted by the area of its polygon inside the watershed.

    Parameters
    ----------
    cells : list[ThiessenCell]
        Grid points and their areas, from :func:`thiessen_cells`
    duration : int | str
        Rainfall duration in minutes or as string (see :func:`validate_duration`)
    probability : int | float
        Exceedance probability [%]
    db : Session
        SQLAlchemy database session

    Returns
    -------
    DesignDepth | None
        The mean depth [mm] and the depth and weight of each point; None when
        ``cells`` is empty

    Raises
    ------
    ValueError
        If duration or probability is invalid
    UnknownGridPointError
        If the grid has no depth of the scenario at a cell (no point within
        GRID_POINT_TOLERANCE_M)
    """
    duration_str = validate_duration(duration)
    probability = validate_probability(probability)
    if not cells:
        return None
    xs = [cell.easting_m for cell in cells]
    ys = [cell.northing_m for cell in cells]
    tol = GRID_POINT_TOLERANCE_M
    rows = db.execute(
        text("""
            SELECT ST_X(geom) AS x, ST_Y(geom) AS y, precipitation_mm
            FROM precipitation_data
            WHERE duration = :duration
              AND probability = :probability
              AND geom && ST_MakeEnvelope(:x0, :y0, :x1, :y1, 2180)
        """),
        {
            "duration": duration_str,
            "probability": probability,
            "x0": min(xs) - tol,
            "y0": min(ys) - tol,
            "x1": max(xs) + tol,
            "y1": max(ys) + tol,
        },
    ).fetchall()
    grid = np.array([(row.x, row.y) for row in rows], dtype=np.float64).reshape(-1, 2)
    stations = []
    for i, cell in enumerate(cells):
        distances = np.hypot(grid[:, 0] - cell.easting_m, grid[:, 1] - cell.northing_m)
        nearest = int(np.argmin(distances)) if len(distances) else -1
        if nearest < 0 or distances[nearest] > tol:
            raise UnknownGridPointError(cell.easting_m, cell.northing_m)
        stations.append(
            Station(
                str(i),
                cell.easting_m,
                cell.northing_m,
                float(rows[nearest].precipitation_mm),
            )
        )
    result = hydrolog_thiessen(
        stations, {str(i): cell.area_km2 for i, cell in enumerate(cells)}
    )
    return DesignDepth(
        precipitation_mm=float(result.areal_precipitation_mm),
        interpolation="thiessen",
        points=tuple(
            GridPointDepth(
                easting_m=cell.easting_m,
                northing_m=cell.northing_m,
                precipitation_mm=station.precipitation_mm,
                weight=result.station_weights[station.station_id],
                area_km2=cell.area_km2,
            )
            for cell, station in zip(cells, stations, strict=True)
        ),
    )


def point_depth(
    point: Point,
    duration: int | str,
    probability: int | float,
    db: Session,
) -> DesignDepth | None:
    """PMAXTP depth at a point: inverse distance weighting of the nearest grid points.

    Used when no watershed boundary is known (a request with its own morphometry
    and without ``pmaxtp_grid``). The weighting is Hydrolog's
    ``inverse_distance_weighting`` of the IDW_NEIGHBOURS nearest points with the
    power IDW_POWER.

    Parameters
    ----------
    point : Point
        Query point in EPSG:2180 (PL-1992)
    duration : int | str
        Rainfall duration in minutes or as string (see :func:`validate_duration`)
    probability : int | float
        Exceedance probability [%]
    db : Session
        SQLAlchemy database session

    Returns
    -------
    DesignDepth | None
        The interpolated depth [mm] and the depth, weight and distance of each
        point; None when the grid has no data of the scenario

    Raises
    ------
    ValueError
        If duration or probability is invalid
    """
    duration_str = validate_duration(duration)
    probability = validate_probability(probability)
    rows = db.execute(
        text("""
            SELECT ST_X(geom) AS x, ST_Y(geom) AS y, precipitation_mm
            FROM precipitation_data
            WHERE duration = :duration
              AND probability = :probability
            ORDER BY geom <-> ST_SetSRID(ST_Point(:x, :y), 2180)
            LIMIT :neighbours
        """),
        {
            "x": point.x,
            "y": point.y,
            "duration": duration_str,
            "probability": probability,
            "neighbours": IDW_NEIGHBOURS,
        },
    ).fetchall()
    if not rows:
        logger.warning(
            "No precipitation data near (%.1f, %.1f), duration=%s, probability=%s%%",
            point.x,
            point.y,
            duration_str,
            probability,
        )
        return None
    stations = [
        Station(str(i), float(row.x), float(row.y), float(row.precipitation_mm))
        for i, row in enumerate(rows)
    ]
    result = inverse_distance_weighting(stations, point.x, point.y, power=IDW_POWER)
    return DesignDepth(
        precipitation_mm=float(result.areal_precipitation_mm),
        interpolation="idw",
        points=tuple(
            GridPointDepth(
                easting_m=station.x,
                northing_m=station.y,
                precipitation_mm=station.precipitation_mm,
                # A point on the grid takes the whole weight, the others none
                weight=result.station_weights.get(station.station_id, 0.0),
                distance_m=float(np.hypot(station.x - point.x, station.y - point.y)),
            )
            for station in stations
        ),
    )
