"""process_dem over a synthetic DEM, its catchment graph and a fake database.

run_pipeline runs process_dem over a DEM array with its rasters saved and the
database replaced by recorders of the rows it would insert; catchment_graph builds
the catchment graph of one or more thresholds from those rows as CatchmentGraph.load
builds it from the database; FakeDatabase answers, from the same rows and a synthetic
land cover and soil layout, the queries of the watershed panel, of the export of
catchment parameters, of catchments_bounds and of the network preview.

river_network_dem builds the DEM of the network tests: a main river with three
tributaries, one of which has a tributary of its own, all draining to one outlet
on the south edge (NETWORK_RIVERS).
"""

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
import shapely
from rasterio.transform import from_origin
from scipy import sparse
from shapely import wkb, wkt
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry

from core.catchment_graph import CatchmentGraph
from scripts.process_dem import process_dem

# A land cover polygon: category, BDOT10k class, imperviousness, geometry
LandCover = tuple[str, str, float, BaseGeometry]
# A soil polygon: hydrologic soil group, geometry
Soil = tuple[str, BaseGeometry]
# The panel's values that a watershed measured from its cells must give
# (test_export_catchment_parameters, test_network_delineation), and the tolerances of
# those the graph aggregates from sub-catchment values rounded to 0.01 (mean
# elevation [m], mean slope [%])
PANEL_FIELDS = (
    "area_km2",
    "perimeter_km",
    "elevation_min_m",
    "elevation_max_m",
    "elevation_mean_m",
    "mean_slope_m_per_m",
    "channel_length_km",
    "real_channel_length_km",
    "channel_slope_m_per_m",
    "flow_path_length_km",
    "flow_path_slope_m_per_m",
    "overland_length_km",
    "overland_slope_m_per_m",
    "divide_flow_path_km",
    "cn",
    "compactness_coefficient",
    "circularity_ratio",
)
PANEL_TOLERANCES = {"elevation_mean_m": 0.01, "mean_slope_m_per_m": 0.00005}

# The DEM of the network tests (river_network_dem): square cells of 10 m, units of
# 1 ha, and the threshold of the streams its points snap to (20 ha), above the
# accumulation of every hollow on the valley sides
NETWORK_CELL_M = 10.0
NETWORK_X0, NETWORK_Y1 = 600_000.0, 500_000.0  # north-west corner
NETWORK_UNIT_THRESHOLD_M2 = 10_000
NETWORK_SNAP_THRESHOLD_M2 = 200_000
NETWORK_SHAPE = (220, 170)  # rows, columns
# The rivers of river_network_dem: the river each joins (None: the main river,
# leaving the grid at its outlet on the south edge) and its course from its mouth
# upstream, (column, row) of cell centres. Each mouth lies where a hollow of the
# river it joins would not (a multiple of _RIPPLE_CELLS along that river).
NETWORK_RIVERS: dict[str, tuple[str | None, tuple[tuple[int, int], ...]]] = {
    "main": (None, ((85, 219), (85, 4))),
    "T1": ("main", ((85, 159), (49, 159), (49, 60))),
    "T1a": ("T1", ((49, 159), (3, 159))),
    "T2": ("main", ((85, 123), (167, 123))),
    "T3": ("main", ((85, 75), (167, 75))),
}
_OUTLET_BED_M = 100.0
_BED_SLOPE_M_PER_M = 0.02
_VALLEY_SIDE_SLOPE_M_PER_M = 0.1
_RIPPLE_CELLS = 12  # spacing of the hollows along a river
_RIPPLE_M = 2.0


@dataclass(frozen=True)
class PipelineRun:
    """The saved rasters of a process_dem run and the rows it would insert.

    Attributes
    ----------
    directory : Path
        Directory of the DEM (``dem_mosaic.tif``) and of the saved rasters.
    cell_m : float
        Cell size [m].
    x0, y1 : float
        North-west corner of the DEM, EPSG:2180 [m].
    segments : dict[int, list[dict[str, Any]]]
        Stream segments by threshold [m²], segment ``i`` at index ``i - 1``.
    catchments : dict[int, list[dict[str, Any]]]
        Sub-catchments by threshold [m²], sorted by ``segment_idx``.
    """

    directory: Path
    cell_m: float
    x0: float
    y1: float
    segments: dict[int, list[dict[str, Any]]]
    catchments: dict[int, list[dict[str, Any]]]

    def cell_centre_xy(self, row: int, col: int) -> tuple[float, float]:
        """Centre of a cell of the DEM, EPSG:2180 [m]."""
        return (
            self.x0 + (col + 0.5) * self.cell_m,
            self.y1 - (row + 0.5) * self.cell_m,
        )


def is_real(segment_idx: int) -> bool:
    """BDOT10k flag of a segment: two of every three, so channels have gaps."""
    return segment_idx % 3 != 2


def line_length_m(segment: dict[str, Any]) -> float:
    """length_m of stream_network: its smoothed line, shorter than its cells' path."""
    return round(0.95 * float(segment["length_m"]), 1)


def land_cover_layout(
    x0: float, y1: float, width_m: float, height_m: float
) -> tuple[LandCover, ...]:
    """Synthetic land cover: forest in the west, arable land in the east, a pond.

    The pond covers the middle fifth of the width and of the height.
    """
    pond = box(
        x0 + width_m * 2 / 5,
        y1 - height_m * 3 / 5,
        x0 + width_m * 3 / 5,
        y1 - height_m * 2 / 5,
    )
    west = box(x0, y1 - height_m, x0 + width_m / 2, y1)
    east = box(x0 + width_m / 2, y1 - height_m, x0 + width_m, y1)
    return (
        ("las", "PTLZ", 0.0, west.difference(pond)),
        ("grunt_orny", "PTTR:grunty orne", 0.1, east.difference(pond)),
        ("woda", "PTWP", 1.0, pond),
    )


def soil_layout(
    x0: float, y1: float, width_m: float, height_m: float
) -> tuple[Soil, ...]:
    """Synthetic soil groups: A in the west, B in the rest but a northern strip.

    Group A covers the western three tenths; the northern fifth of the rest has no
    soil group.
    """
    return (
        ("A", box(x0, y1 - height_m, x0 + width_m * 3 / 10, y1)),
        (
            "B",
            box(
                x0 + width_m * 3 / 10,
                y1 - height_m,
                x0 + width_m,
                y1 - height_m / 5,
            ),
        ),
    )


def run_pipeline(
    directory: Path,
    dem: np.ndarray,
    *,
    cell_m: float,
    x0: float,
    y1: float,
    thresholds: Sequence[int],
) -> PipelineRun:
    """Run process_dem over a DEM with its rasters saved and no database.

    Parameters
    ----------
    directory : Path
        Existing directory of the DEM GeoTIFF and of the saved rasters.
    dem : np.ndarray
        Elevations [m], float32, north row first, without nodata.
    cell_m : float
        Cell size [m].
    x0, y1 : float
        North-west corner of the DEM, EPSG:2180 [m].
    thresholds : Sequence[int]
        Flow accumulation thresholds [m²] of the stream networks and sub-catchments.

    Returns
    -------
    PipelineRun
        The directory and the rows process_dem would insert, by threshold.
    """
    dem_path = directory / "dem_mosaic.tif"
    height, width = dem.shape
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(x0, y1, cell_m, cell_m),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem.astype("float32"), 1)

    segments: dict[int, list[dict[str, Any]]] = {}
    catchments: dict[int, list[dict[str, Any]]] = {}

    @contextmanager
    def session():
        yield MagicMock()

    def insert_segments(db, rows, threshold_m2, **_):
        segments[threshold_m2] = rows
        return len(rows)

    def insert_catchments(db, rows, threshold_m2, **_):
        catchments[threshold_m2] = sorted(rows, key=lambda c: c["segment_idx"])
        return len(rows)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("core.database.get_db_session", session)
        patch.setattr("scripts.process_dem.insert_stream_segments", insert_segments)
        patch.setattr("scripts.process_dem.insert_catchments", insert_catchments)
        patch.setattr(
            "scripts.process_dem.update_stream_real_flags_all", lambda db, t: {}
        )
        process_dem(
            dem_path,
            save_intermediates=True,
            output_dir=directory,
            thresholds=list(thresholds),
        )
    return PipelineRun(
        directory=directory,
        cell_m=cell_m,
        x0=x0,
        y1=y1,
        segments=segments,
        catchments=catchments,
    )


def catchment_graph(run: PipelineRun, *thresholds_m2: int) -> CatchmentGraph:
    """The catchment graph of one or more thresholds, as CatchmentGraph.load builds it.

    BDOT10k flags come from is_real, segment lengths from line_length_m.
    """
    rows = [
        (threshold_m2, c, run.segments[threshold_m2][c["segment_idx"] - 1])
        for threshold_m2 in sorted(thresholds_m2)
        for c in run.catchments[threshold_m2]
    ]
    catchments = [c for _, c, _ in rows]
    n = len(rows)

    def column(key, dtype=np.float32):
        values = [np.nan if c.get(key) is None else c[key] for c in catchments]
        return np.array(values, dtype=dtype)

    cg = CatchmentGraph()
    cg._n = n
    cg._segment_idx = np.array([c["segment_idx"] for c in catchments], np.int32)
    cg._threshold_m2 = np.array([t for t, _, _ in rows], np.int32)
    cg._area_km2 = column("area_km2")
    cg._elev_min = column("elevation_min_m")
    cg._elev_max = column("elevation_max_m")
    cg._elev_mean = column("mean_elevation_m")
    cg._slope_mean = column("mean_slope_percent")
    cg._stream_length_km = column("stream_length_km")
    cg._strahler = np.array([c["strahler_order"] or 0 for c in catchments], np.int8)
    cg._max_flow_dist_m = np.nan_to_num(column("max_flow_dist_m", np.float64))
    cg._outlet_flow_dist_m = column("outlet_flow_dist_m", np.float64)
    cg._flow_path_head_elev_m = column("flow_path_head_elev_m")
    cg._overland_length_m = column("overland_length_m")
    cg._overland_drop_m = column("overland_drop_m")
    cg._stream_head_elev_m = column("stream_head_elev_m")
    cg._histograms = [c["elev_histogram"] for c in catchments]
    cg._is_real_stream = np.array([is_real(c["segment_idx"]) for c in catchments])
    cg._segment_length_km = np.array(
        [line_length_m(segment) / 1000.0 for _, _, segment in rows]
    )
    cg._upstream_area_km2 = np.array(
        [segment["upstream_area_km2"] for _, _, segment in rows]
    )
    cg._lookup = {(t, c["segment_idx"]): i for i, (t, c, _) in enumerate(rows)}
    links = [
        (i, cg._lookup[(t, c["downstream_segment_idx"])])
        for i, (t, c, _) in enumerate(rows)
        if c.get("downstream_segment_idx") is not None
    ]
    upstream, downstream = zip(*links, strict=True)
    cg._upstream_adj = sparse.csr_matrix(
        (np.ones(len(links), np.int8), (downstream, upstream)), shape=(n, n)
    )
    cg._loaded = True
    return cg


class FakeDatabase:
    """Answers the queries of the panel, the export, catchments_bounds and the preview.

    Parameters
    ----------
    run : PipelineRun
        The rows of the stream networks and sub-catchments.
    threshold_m2 : int
        Threshold of a query that names none.
    land_cover : Sequence[LandCover]
        Land cover polygons (land_cover_layout).
    soils : Sequence[Soil]
        Soil group polygons (soil_layout).
    """

    def __init__(
        self,
        run: PipelineRun,
        threshold_m2: int,
        *,
        land_cover: Sequence[LandCover] = (),
        soils: Sequence[Soil] = (),
    ) -> None:
        self.run = run
        self.threshold_m2 = threshold_m2
        self.land_cover = tuple(land_cover)
        self.soils = tuple(soils)

    @staticmethod
    def _result(rows=(), row=None, scalar=None):
        return SimpleNamespace(
            fetchall=lambda: list(rows),
            fetchone=lambda: row,
            scalar=lambda: scalar,
        )

    def _threshold(self, params):
        return (params or {}).get("threshold", self.threshold_m2)

    def execute(self, statement, params=None):
        sql = str(statement)
        # The land cover query clips the soils too, so it is recognised first and by
        # its table alone, however it joins land_cover to the watershed.
        if "land_cover lc" in sql:
            boundary = wkb.loads(bytes.fromhex(params["boundary_wkb"]))
            rows = []
            for category, bdot_class, imperviousness, geometry in self.land_cover:
                inside = geometry.intersection(boundary)
                if inside.is_empty:
                    continue
                pieces = [(None, inside)] + [
                    (group, inside.intersection(soil)) for group, soil in self.soils
                ]
                rows.extend(
                    SimpleNamespace(
                        category=category,
                        bdot_class=bdot_class,
                        imperviousness=imperviousness,
                        hsg_group=group,
                        area_m2=piece.area,
                    )
                    for group, piece in pieces
                    if not piece.is_empty
                )
            return self._result(rows)
        if "FROM soil_hsg sh" in sql:
            boundary = wkb.loads(bytes.fromhex(params["boundary_wkb"]))
            areas = {g: s.intersection(boundary).area for g, s in self.soils}
            total = sum(areas.values())
            return self._result(
                SimpleNamespace(
                    hsg_group=g, total_area_m2=a, percentage=a / total * 100
                )
                for g, a in sorted(areas.items(), key=lambda item: -item[1])
                if a > 0
            )
        if "ST_Extent(geom)" in sql and "stream_catchments" in sql:
            idxs = set(params["idxs"])
            geometries = [
                wkt.loads(c["wkt"])
                for c in self.run.catchments.get(self._threshold(params), [])
                if c["segment_idx"] in idxs
            ]
            if not geometries:
                return self._result(
                    row=SimpleNamespace(minx=None, miny=None, maxx=None, maxy=None)
                )
            minx, miny, maxx, maxy = shapely.total_bounds(geometries)
            return self._result(
                row=SimpleNamespace(
                    minx=float(minx),
                    miny=float(miny),
                    maxx=float(maxx),
                    maxy=float(maxy),
                )
            )
        if "is_real_stream" in sql and "ANY" in sql:
            threshold_m2 = self._threshold(params)
            segments = self.run.segments[threshold_m2]
            catchments = {
                c["segment_idx"]: c for c in self.run.catchments[threshold_m2]
            }
            return self._result(
                SimpleNamespace(
                    segment_idx=i,
                    is_real=is_real(i),
                    line_length_m=line_length_m(segments[i - 1]),
                    stream_length_km=catchments[i]["stream_length_km"],
                )
                for i in params["idxs"]
                if i in catchments
            )
        if "ST_EndPoint(geom)" in sql:
            segments = self.run.segments[self._threshold(params)]
            x, y = segments[params["seg_idx"] - 1]["coords"][-1]
            return self._result(row=SimpleNamespace(x=x, y=y))
        if "AS p(threshold_m2, segment_idx, element)" in sql:
            # The outlines of the preview: the polygons of the chosen sub-catchments
            # united by element on the grid of the query
            polygons = {
                (threshold_m2, c["segment_idx"]): wkt.loads(c["wkt"])
                for threshold_m2, rows in self.run.catchments.items()
                for c in rows
            }
            by_element: dict[int, list[BaseGeometry]] = {}
            for key in zip(
                params["thresholds"],
                params["segments"],
                params["elements"],
                strict=True,
            ):
                by_element.setdefault(key[2], []).append(polygons[key[:2]])
            return self._result(
                SimpleNamespace(
                    element=element,
                    geom=shapely.union_all(parts, grid_size=params["grid_m"]).wkb,
                )
                for element, parts in by_element.items()
            )
        if "FROM stream_network" in sql and "ST_AsBinary(geom)" in sql:
            segments = self.run.segments[self._threshold(params)]
            return self._result(
                SimpleNamespace(
                    segment_idx=i, geom=LineString(segments[i - 1]["coords"]).wkb
                )
                for i in params["idxs"]
            )
        if "EXISTS" in sql:
            return self._result(scalar=True)
        return self._result()


def river_network_dem() -> np.ndarray:
    """DEM of the network tests: NETWORK_SHAPE cells of NETWORK_CELL_M, float32.

    The main river flows south along column 85 to its outlet on the south edge
    (row 219). T3 (row 75) and T2 (row 123) come from the east; T1 comes from the
    north along column 49 and turns east along row 159, where T1a joins it from
    the west. Each river lies in a valley: its bed rises upstream from its mouth at
    _BED_SLOPE_M_PER_M and the ground rises at _VALLEY_SIDE_SLOPE_M_PER_M across
    the valley; a cell takes the lowest of the rivers' valleys. A ripple along each
    river makes hollows on the valley sides every _RIPPLE_CELLS cells, whose 1 ha
    streams split every river into units; no hollow drains
    NETWORK_SNAP_THRESHOLD_M2. The filled DEM equals the DEM: no pits, no flats.

    Returns
    -------
    np.ndarray
        Elevations [m], north row first; the north-west corner of the grid is at
        NETWORK_X0, NETWORK_Y1.
    """
    rows, cols = NETWORK_SHAPE
    r, c = np.mgrid[0:rows, 0:cols]
    cells = shapely.points(c.ravel().astype(float), r.ravel().astype(float))
    dem_m = np.full(rows * cols, np.inf)
    lines: dict[str, LineString] = {}
    mouth_bed_m: dict[str, float] = {}
    for name, (joins, course) in NETWORK_RIVERS.items():
        line = lines[name] = LineString(course)
        if joins is None:
            mouth_bed_m[name] = _OUTLET_BED_M
        else:
            along_parent_cells = shapely.line_locate_point(
                lines[joins], shapely.points(course[0])
            )
            mouth_bed_m[name] = (
                mouth_bed_m[joins]
                + _BED_SLOPE_M_PER_M * along_parent_cells * NETWORK_CELL_M
            )
        along_cells = shapely.line_locate_point(line, cells)
        across_cells = shapely.distance(line, cells)
        # A crest at the mouth and every _RIPPLE_CELLS upstream, so a hollow of the
        # river a tributary joins never meets it at its mouth
        ripple = 0.5 * (1 + np.cos(2 * np.pi * along_cells / _RIPPLE_CELLS))
        surface_m = (
            mouth_bed_m[name]
            + _BED_SLOPE_M_PER_M * along_cells * NETWORK_CELL_M
            + _VALLEY_SIDE_SLOPE_M_PER_M * across_cells * NETWORK_CELL_M
            + _RIPPLE_M * ripple * np.minimum(across_cells / 3.0, 1.0)
        )
        dem_m = np.minimum(dem_m, surface_m)
    return dem_m.reshape(rows, cols).astype("float32")
