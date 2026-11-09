"""
Check the flow directions of the BDOT10k watercourse lines of an area.

A diagnostic, outside the pipeline (ADR-077): it reads the lines of OT_SWRS_L,
OT_SWKN_L and OT_SWRM_L within 1 km of the area, splits a line where an end of
another line lies on its middle, and joins the ends within 0.5 m into the nodes of a
network. For every line it gathers the evidence that BDOT10k digitized it upstream:

- the DEM along it, sampled every 5 m the way it is digitized (the lowest value of
  its last quarter against the lowest of its first, as ``_rises_downstream`` of
  ``core.hydrology`` reads it);
- with ``--catchments``, the order of the MPHP catchments of its own river at its two
  ends (the codes number a river's own catchments from its source down);
- a run of lines from a node where only lines begin, through nodes where one line
  ends and one begins, to a node where only lines end;
- its direction against the rest of its watercourse: the lines of one MPHP
  identifier, else of one name, joined end to end where exactly two of them meet,
  whose downstream end is decided by the DEM along the whole watercourse (a rise of
  more than 0.5 m between the quarters), else by the digitized majority.

The verdict ``werdykt`` weighs the evidence. Independent of it, the mouth test
(``test_ujscia``) orients the lines of an MPHP watercourse towards the node where it
meets its receiver, a line whose MPHP identifier is a proper prefix of its own.
``kategoria`` sets apart the reversed lines that are doubtful: artificial connectors
through lakes (``CECHAGEOMETRII = 'sztuczny łącznik'``, where the DEM is a water
surface) and networks detached from the main watercourses. ``regula`` and
``odwraca`` are what the smoothing of the pipeline does with a burned line
(``core.hydrology._line_directions``): the rule that decides its direction and
whether it reverses it, computed on the burned lines alone.

The new GeoPackage ``--out`` gets three layers: ``odcinki`` (the lines, with the
evidence, the verdict, ``test_ujscia``, ``kategoria``, ``regula`` and ``odwraca``),
``wezly`` (the nodes, their kinds as digitized and after the lines with the verdict
``odwrocony`` are reversed) and ``cieki`` (the watercourses, drawn downstream). The
names of the layers, the columns and their values are Polish, as the review map of
the author reads them.

Usage
-----
    cd backend
    python -m scripts.check_stream_directions --hydro hydro_merged.gpkg \
        --dem dem_mosaic.vrt --area obszar.gpkg:Zlewnie \
        --catchments zlewnie.gpkg:zlew_h_07 --burning main --out kierunki.gpkg
"""

import argparse
import heapq
import logging
import math
import sys
import time
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.transform import Affine
from rasterio.windows import from_bounds
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from core.hydrology import (
    CONNECTOR,
    LAKE_SNAP_M,
    REVERSED_LINE_MIN_LENGTH_M,
    REVERSED_LINE_RISE_M,
    STREAM_BURNING_MODES,
    WATERCOURSE_RISE_M,
    _line_directions,
    _select_burned_features,
)

logger = logging.getLogger(__name__)

LINE_LAYERS = ("OT_SWRS_L", "OT_SWKN_L", "OT_SWRM_L")
WATER_LAYER = "OT_PTWP_A"
# The attributes of a line carried to the output
ATTRIBUTES = (
    "LOKALNYID",
    "TERYT",
    "NAZWA",
    "RODZAJ",
    "PRZEBIEG",
    "IDENTYFIKATORMPHP",
    "POLOZENIE",
    "CECHAGEOMETRII",
)
# The rules of the smoothing (``_line_directions``) by their Polish names
RULES = {
    "mouth": "ujscie",
    "watercourse": "nmt_cieku",
    "rise": "nmt_odcinka",
    "digitized": "digitalizacja",
}
# The field of the MPHP code of a catchment (MPHP10)
CATCHMENT_CODE = "ID_HYD_10"
# Ends of lines this close are one node; an end this close to the middle of another
# line splits that line
SNAP_M = 0.5
# Spacing of the DEM samples along a line: the cell of the 5 m NMT
STEP_M = 5.0
# The lines within this distance of the area are read
REGION_BUFFER_M = 1000.0
# A node this close to the boundary of the area, or outside it, is at its edge
EDGE_M = 25.0
# A node this close to a water polygon is at water (the lake snap of the pipeline)
WATER_M = LAKE_SNAP_M
# A rise of more than RISE_STRONG_M the way a line is digitized: ADR-072 reverses it
RISE_STRONG_M = REVERSED_LINE_RISE_M
# A rise or fall within RISE_WEAK_M is flat (rule 2 of the smoothing)
RISE_WEAK_M = WATERCOURSE_RISE_M
# A shorter line or watercourse has no DEM class
MIN_LENGTH_M = REVERSED_LINE_MIN_LENGTH_M
# The catchment of a line's end is read this far inside the line
MPHP_PROBE_M = 10.0
# The walk along a run of lines stops after this many lines
MAX_RUN_LINES = 500
# The categories of the reversed lines
REVERSED_CATEGORIES = ("odwrocony", "odwrocony_lacznik", "odwrocony_siec_oderwana")


def parse_layer_spec(spec: str) -> tuple[Path, str | None]:
    """Split ``FILE[:LAYER]`` into the file and the layer (None when not given)."""
    path, separator, layer = spec.rpartition(":")
    if separator and path and layer and "/" not in layer:
        return Path(path), layer
    return Path(spec), None


def read_layer(spec: str) -> gpd.GeoDataFrame:
    """Read the layer of ``FILE[:LAYER]`` in EPSG:2180; the only one without LAYER."""
    path, layer = parse_layer_spec(spec)
    if not path.is_file():
        raise FileNotFoundError(f"{path}: no such file")
    if layer is None:
        layers = gpd.list_layers(path)["name"].tolist()
        if len(layers) != 1:
            raise ValueError(f"{path} has {len(layers)} layers: give one as FILE:LAYER")
        layer = layers[0]
    gdf = gpd.read_file(path, layer=layer)
    if gdf.crs is None:
        raise ValueError(f"{spec}: the layer has no coordinate reference system")
    return gdf.to_crs(2180)


def _text(series: pd.Series) -> pd.Series:
    """Return the values as stripped text, '' for a missing one."""
    return series.fillna("").astype(str).str.strip()


def read_lines(hydro: Path, region: BaseGeometry) -> gpd.GeoDataFrame:
    """Read the watercourse lines of the three BDOT10k layers that reach into a region.

    One row per part of a multipart line, in 2D, without the lines of zero length and
    the exact duplicates (equal geometry in either direction). The text attributes are
    stripped ('' when missing); ``warstwa`` is the layer (SWRS, SWKN, SWRM) and
    ``glowny`` says whether the line is a main watercourse, the selection of
    ``dem.stream_burning: main`` (``core.hydrology._select_burned_features``).
    """
    layers = set(gpd.list_layers(hydro)["name"])
    frames = []
    for layer in LINE_LAYERS:
        if layer not in layers:
            continue
        gdf = gpd.read_file(hydro, layer=layer, bbox=region.bounds)
        if gdf.empty:
            continue
        if gdf.crs is None or gdf.crs.to_epsg() != 2180:
            raise ValueError(f"{hydro}:{layer} is not in EPSG:2180")
        gdf = gdf[gdf.geometry.notna() & gdf.geometry.intersects(region)].copy()
        main = _select_burned_features(gdf, layer, "main")
        gdf["glowny"] = gdf.index.isin(main.index)
        gdf["warstwa"] = layer[3:7]
        for column in ATTRIBUTES:
            if column not in gdf:
                gdf[column] = None
        frames.append(gdf[["warstwa", *ATTRIBUTES, "glowny", "geometry"]])
    if not frames:
        raise ValueError(f"{hydro}: no watercourse lines within the area")
    lines = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=2180
    ).explode(index_parts=False)
    lines = lines[lines.geom_type == "LineString"].copy()
    lines["geometry"] = shapely.force_2d(lines.geometry.values)
    lines = lines[lines.geometry.length > 0]
    wkb = pd.Series(shapely.to_wkb(shapely.normalize(lines.geometry.values)))
    lines = lines[~wkb.duplicated().to_numpy()].reset_index(drop=True)
    for column in ATTRIBUTES:
        lines[column] = _text(lines[column])
    if lines.empty:
        raise ValueError(f"{hydro}: no watercourse lines within the area")
    return lines


def read_water(hydro: Path, region: BaseGeometry) -> np.ndarray:
    """Read the water polygons (OT_PTWP_A) that reach into a region."""
    if WATER_LAYER not in set(gpd.list_layers(hydro)["name"]):
        return np.array([], dtype=object)
    water = gpd.read_file(hydro, layer=WATER_LAYER, bbox=region.bounds)
    water = water[water.geometry.notna()]
    return np.asarray(water.geometry.values[water.geometry.intersects(region)])


def read_dem(path: Path, bounds: tuple[float, ...]) -> tuple[np.ndarray, Affine, Any]:
    """Read the DEM in a window of the bounds: (values, transform, nodata)."""
    with rasterio.open(path) as src:
        if src.crs is None or src.crs.to_epsg() != 2180:
            raise ValueError(f"{path} is not in EPSG:2180")
        window = (
            from_bounds(*bounds, transform=src.transform)
            .round_offsets()
            .round_lengths()
        )
        fill = src.nodata if src.nodata is not None else np.nan
        dem = src.read(1, window=window, boundless=True, fill_value=fill)
        return dem, src.window_transform(window), src.nodata


def read_catchments(spec: str) -> gpd.GeoDataFrame:
    """Read the MPHP catchments: their geometry and code (``kod``, from ID_HYD_10)."""
    catchments = read_layer(spec)
    if CATCHMENT_CODE not in catchments:
        raise ValueError(f"{spec}: no field {CATCHMENT_CODE}")
    catchments["kod"] = (
        catchments[CATCHMENT_CODE].astype(str).str.replace(r"\.0$", "", regex=True)
    )
    return catchments[["kod", "geometry"]]


def split_at_t_junctions(
    geoms: np.ndarray, snap_m: float = SNAP_M
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split the lines where an end of another line lies on their middle.

    An end of a line within ``snap_m`` of another line, and farther than ``snap_m``
    from both ends of that line, cuts it there (a T-junction).

    Returns
    -------
    tuple
        (the pieces; for each piece the index of its line; the number of the piece
        along its line, from 0; for each line, whether an end of it cuts another line)
    """
    n = len(geoms)
    starts = shapely.get_point(geoms, 0)
    ends = shapely.get_point(geoms, -1)
    points = np.concatenate([starts, ends])
    owner = np.concatenate([np.arange(n), np.arange(n)])
    point_idx, line_idx = shapely.STRtree(geoms).query(
        points, predicate="dwithin", distance=snap_m
    )
    other = line_idx != owner[point_idx]
    point_idx, line_idx = point_idx[other], line_idx[other]
    middle = (shapely.distance(points[point_idx], starts[line_idx]) > snap_m) & (
        shapely.distance(points[point_idx], ends[line_idx]) > snap_m
    )
    point_idx, line_idx = point_idx[middle], line_idx[middle]
    positions = shapely.line_locate_point(geoms[line_idx], points[point_idx])
    cuts: dict[int, list[float]] = defaultdict(list)
    for host, position in zip(line_idx.tolist(), positions.tolist(), strict=True):
        cuts[host].append(position)
    ends_on_middle = np.zeros(n, dtype=bool)
    ends_on_middle[owner[point_idx]] = True
    pieces: list[BaseGeometry] = []
    source: list[int] = []
    part: list[int] = []
    for i, geom in enumerate(geoms):
        length = geom.length
        marks = sorted(
            {round(d, 2) for d in cuts.get(i, []) if snap_m < d < length - snap_m}
        )
        bounds = [0.0, *marks, length]
        number = 0
        for start, end in zip(bounds[:-1], bounds[1:], strict=True):
            if end - start <= 1e-6:
                continue
            pieces.append(substring(geom, start, end) if marks else geom)
            source.append(i)
            part.append(number)
            number += 1
    result = np.empty(len(pieces), dtype=object)
    result[:] = pieces
    return (
        result,
        np.array(source, dtype=int),
        np.array(part, dtype=int),
        ends_on_middle,
    )


def join_ends(
    geoms: np.ndarray, snap_m: float = SNAP_M
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Give the ends of the lines their nodes: ends within ``snap_m`` are one node.

    The joining chains: three ends 0.4 m apart in a row are one node.

    Returns
    -------
    tuple
        (the node of the first point of each line, the node of its last point, the
        coordinates of each node: the mean of its ends)
    """
    n = len(geoms)
    xy = np.vstack(
        [
            shapely.get_coordinates(shapely.get_point(geoms, 0)),
            shapely.get_coordinates(shapely.get_point(geoms, -1)),
        ]
    )
    pairs = cKDTree(xy).query_pairs(snap_m, output_type="ndarray")
    graph = coo_matrix(
        (np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(2 * n, 2 * n)
    )
    n_nodes, node_of_end = connected_components(graph, directed=False)
    node_xy = np.zeros((n_nodes, 2))
    np.add.at(node_xy, node_of_end, xy)
    node_xy /= np.bincount(node_of_end, minlength=n_nodes)[:, None]
    return node_of_end[:n], node_of_end[n:], node_xy


def oriented(
    u: np.ndarray, v: np.ndarray, flip: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return the first and last node of each line, the flipped lines reversed."""
    a, b = u.copy(), v.copy()
    if flip is not None:
        a[flip], b[flip] = v[flip], u[flip]
    return a, b


def node_kinds(
    a: np.ndarray, b: np.ndarray, edge: np.ndarray, at_water: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Count the lines ending and beginning at each node and name its kind.

    The lines run from ``a`` to ``b``; a closed line is left out. The kinds:
    ``krawedz`` (at the edge of the area or outside it), ``tylko_petla`` (closed lines
    only), ``zrodlo`` (one line begins, none ends), ``koniec_przy_wodzie`` and
    ``slepy_koniec`` (one ends, none begins; at water or not), ``przejscie`` (one
    ends, one begins), ``zbieg`` (two or more end, one begins), ``rozwidlenie`` (one
    or more end, two or more begin), ``same_poczatki`` (two or more begin, none ends)
    and ``same_konce`` (two or more end, none begins).

    Returns
    -------
    tuple
        (lines ending at each node, lines beginning at it, its kind)
    """
    n_nodes = len(edge)
    open_lines = a != b
    n_out = np.bincount(a[open_lines], minlength=n_nodes)
    n_in = np.bincount(b[open_lines], minlength=n_nodes)
    kind = np.empty(n_nodes, dtype=object)
    for k in range(n_nodes):
        ending, beginning = n_in[k], n_out[k]
        if edge[k]:
            name = "krawedz"
        elif ending == 0 and beginning == 0:
            name = "tylko_petla"
        elif ending == 0 and beginning == 1:
            name = "zrodlo"
        elif ending == 1 and beginning == 0:
            name = "koniec_przy_wodzie" if at_water[k] else "slepy_koniec"
        elif ending == 1 and beginning == 1:
            name = "przejscie"
        elif ending >= 2 and beginning == 1:
            name = "zbieg"
        elif ending >= 1 and beginning >= 2:
            name = "rozwidlenie"
        elif ending == 0:
            name = "same_poczatki"
        else:
            name = "same_konce"
        kind[k] = name
    return n_in, n_out, kind


def incident_lines(
    a: np.ndarray, b: np.ndarray, closed: np.ndarray
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Map each node to the lines beginning and to the lines ending at it (no loops)."""
    beginning: dict[int, list[int]] = defaultdict(list)
    ending: dict[int, list[int]] = defaultdict(list)
    for i in np.flatnonzero(~closed).tolist():
        beginning[int(a[i])].append(i)
        ending[int(b[i])].append(i)
    return beginning, ending


@dataclass(frozen=True)
class Profiles:
    """The DEM every STEP_M along each line, in the order the line is digitized.

    Attributes
    ----------
    z : np.ndarray
        The samples of all lines, NaN without data.
    offsets : np.ndarray
        The samples of line ``i`` are ``z[offsets[i]:offsets[i + 1]]``.
    distance_m : np.ndarray
        The distance of each sample from the first point of its line.
    """

    z: np.ndarray
    offsets: np.ndarray
    distance_m: np.ndarray

    def of(self, line: int) -> np.ndarray:
        """Return the samples of one line."""
        return self.z[self.offsets[line] : self.offsets[line + 1]]


def sample_profiles(
    geoms: np.ndarray,
    dem: np.ndarray,
    transform: Affine,
    nodata: Any,
    step_m: float = STEP_M,
) -> Profiles:
    """Sample the DEM along each line: both ends and points at most ``step_m`` apart.

    A sample takes the cell that contains it; outside the raster, on nodata or on a
    value that is not finite it is NaN.
    """
    n = len(geoms)
    lengths = shapely.length(geoms)
    counts = np.maximum(np.ceil(lengths / step_m).astype(int) + 1, 2)
    line = np.repeat(np.arange(n), counts)
    offsets = np.concatenate([[0], np.cumsum(counts)])
    distance = (
        (np.arange(line.size) - offsets[line]) / (counts[line] - 1) * lengths[line]
    )
    xy = shapely.get_coordinates(shapely.line_interpolate_point(geoms[line], distance))
    col, row = ~transform * (xy[:, 0], xy[:, 1])
    row = np.floor(row).astype(int)
    col = np.floor(col).astype(int)
    inside = (row >= 0) & (row < dem.shape[0]) & (col >= 0) & (col < dem.shape[1])
    z = np.full(line.size, np.nan)
    z[inside] = dem[row[inside], col[inside]]
    if nodata is not None:
        z[z == nodata] = np.nan
    z[~np.isfinite(z)] = np.nan
    return Profiles(z=z, offsets=offsets, distance_m=distance)


def quarter_minima(values: np.ndarray) -> tuple[float, float]:
    """Return the lowest value of the first and of the last quarter of a profile.

    A quarter has at least one value. The rise of the profile is the second less the
    first, as ``core.hydrology._rises_downstream`` takes it.
    """
    quarter = max(values.size // 4, 1)
    return float(values[:quarter].min()), float(values[-quarter:].min())


@dataclass(frozen=True)
class Relief:
    """The DEM along each line, the way it is digitized.

    Attributes
    ----------
    first_m, last_m : np.ndarray
        The lowest value of the first and of the last quarter (NaN under two samples).
    rise_m : np.ndarray
        ``last_m - first_m``.
    valid_share : np.ndarray
        The share of the samples with data.
    slope_m_km : np.ndarray
        The least-squares slope of the samples, positive when they rise.
    """

    first_m: np.ndarray
    last_m: np.ndarray
    rise_m: np.ndarray
    valid_share: np.ndarray
    slope_m_km: np.ndarray


def line_relief(profiles: Profiles) -> Relief:
    """Measure the DEM along each line (``Relief``)."""
    counts = np.diff(profiles.offsets)
    n = counts.size
    first = np.full(n, np.nan)
    last = np.full(n, np.nan)
    share = np.zeros(n)
    for i in range(n):
        values = profiles.of(i)
        values = values[~np.isnan(values)]
        share[i] = values.size / counts[i]
        if values.size >= 2:
            first[i], last[i] = quarter_minima(values)
    line = np.repeat(np.arange(n), counts)
    good = ~np.isnan(profiles.z)
    owner, d, z = line[good], profiles.distance_m[good], profiles.z[good]
    count = np.bincount(owner, minlength=n).astype(float)
    sum_d = np.bincount(owner, weights=d, minlength=n)
    sum_z = np.bincount(owner, weights=z, minlength=n)
    sum_dd = np.bincount(owner, weights=d * d, minlength=n)
    sum_dz = np.bincount(owner, weights=d * z, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        slope = (count * sum_dz - sum_d * sum_z) / (count * sum_dd - sum_d**2) * 1000.0
    return Relief(first, last, last - first, share, slope)


def dem_classes(
    lengths_m: np.ndarray, valid_share: np.ndarray, rise_m: np.ndarray
) -> np.ndarray:
    """Class each line by the DEM along it, the way it is digitized.

    ``nieoceniony`` (shorter than MIN_LENGTH_M, data on less than half of it, or
    fewer than two samples), ``w_gore_wyraznie`` (rises by more than RISE_STRONG_M:
    ADR-072 reverses it), ``w_gore_slabo`` (rises by more than RISE_WEAK_M),
    ``w_dol`` (falls by more than RISE_WEAK_M), ``plaski`` (the rest).
    """
    with np.errstate(invalid="ignore"):
        return np.where(
            (lengths_m < MIN_LENGTH_M) | (valid_share < 0.5) | np.isnan(rise_m),
            "nieoceniony",
            np.where(
                rise_m > RISE_STRONG_M,
                "w_gore_wyraznie",
                np.where(
                    rise_m > RISE_WEAK_M,
                    "w_gore_slabo",
                    np.where(rise_m < -RISE_WEAK_M, "w_dol", "plaski"),
                ),
            ),
        )


def catchment_codes(
    geoms: np.ndarray, catchments: gpd.GeoDataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Read the MPHP code of the catchment at each end of each line.

    The point is MPHP_PROBE_M (at most a third of the line) inside the line, so an
    end on a catchment boundary takes the catchment the line runs in.

    Returns
    -------
    tuple
        (the code at the first end, at the last end; None outside the catchments)
    """
    lengths = shapely.length(geoms)
    probe = np.minimum(MPHP_PROBE_M, lengths / 3)
    codes = []
    for at in (probe, lengths - probe):
        points = gpd.GeoDataFrame(
            geometry=shapely.line_interpolate_point(geoms, at), crs=2180
        )
        found = gpd.sjoin(points, catchments, how="left", predicate="within")
        code = found.groupby(level=0)["kod"].first().reindex(range(len(geoms)))
        codes.append(code.astype(object).where(code.notna(), None).to_numpy())
    return codes[0], codes[1]


def catchment_order(
    mphp: np.ndarray, code_from: np.ndarray, code_to: np.ndarray
) -> np.ndarray:
    """Say whether a line runs down the MPHP catchments of its own river.

    The codes of a river's own catchments are its code, an odd digit and more digits,
    numbered from the source down (188519 lies upstream of 188531 on the Noteć, 188).
    A line whose two ends lie in two such catchments of its river is ``zgodny`` when
    the code at its last end comes later, else ``odwrocony``; None when it cannot be
    told (no MPHP identifier, one catchment, a tributary's catchment, none).
    """
    result = np.full(len(mphp), None, dtype=object)
    for i, (river, first, last) in enumerate(
        zip(mphp.tolist(), code_from.tolist(), code_to.tolist(), strict=True)
    ):
        if not river or not isinstance(first, str) or not isinstance(last, str):
            continue
        if first == last or not (first.startswith(river) and last.startswith(river)):
            continue
        if len(first) <= len(river) or len(last) <= len(river):
            continue
        if first[len(river)] not in "13579" or last[len(river)] not in "13579":
            continue
        width = max(len(first), len(last))
        downstream = first.ljust(width, "0") < last.ljust(width, "0")
        result[i] = "zgodny" if downstream else "odwrocony"
    return result


def conflict_runs(
    v: np.ndarray, kind: np.ndarray, beginning: dict[int, list[int]]
) -> tuple[np.ndarray, np.ndarray]:
    """Find the runs of lines that begin and end against their neighbours.

    A run starts with a line beginning at a node where only lines begin, follows the
    nodes where one line ends and one begins, and ends at a node where only lines end:
    the lines at both of its ends are digitized against each other, so one side of it
    is digitized upstream.

    Returns
    -------
    tuple
        (the run of each line, -1 outside one; the number of lines of its run)
    """
    run = np.full(v.size, -1)
    size = np.zeros(v.size, dtype=int)
    runs = 0
    for node in np.flatnonzero(kind == "same_poczatki").tolist():
        for first in beginning[node]:
            path = [first]
            at = int(v[first])
            while kind[at] == "przejscie" and len(path) < MAX_RUN_LINES:
                following = beginning[at][0]
                path.append(following)
                at = int(v[following])
            if kind[at] == "same_konce":
                run[path] = runs
                size[path] = len(path)
                runs += 1
    return run, size


def watercourse_keys(mphp: np.ndarray, names: np.ndarray) -> np.ndarray:
    """Name the watercourse of each line: its MPHP identifier, else its name.

    ``M:<identifier>``, ``N:<name>`` or '' (a line of no watercourse).
    """
    mphp = np.asarray(mphp, dtype=object)
    names = np.asarray(names, dtype=object)
    return np.where(
        mphp != "", "M:" + mphp, np.where(names != "", "N:" + names, "")
    ).astype(object)


@dataclass
class Watercourse:
    """The lines of one watercourse joined end to end, in the order of a walk.

    Attributes
    ----------
    key : str
        The watercourse (``watercourse_keys``).
    lines : list[int]
        The lines in the order of the walk.
    loop : bool
        The walk went round a loop.
    start, end : int
        The nodes where the walk begins and ends.
    length_m, rise_m : float
        The length, and the rise of the DEM along the whole walk (NaN when shorter than
        MIN_LENGTH_M).
    forward_m : float
        The length of the lines digitized the way of the walk.
    downstream_forward : bool or None
        Whether the walk runs downstream; None when it cannot be told.
    source : str
        What decides it: ``nmt`` (the DEM), ``wiekszosc`` (the digitized majority) or
        ``brak``.
    reversed_lines, reversed_m : int, float
        The lines digitized against the downstream direction, and their length.
    """

    key: str
    lines: list[int]
    loop: bool
    start: int
    end: int
    length_m: float = 0.0
    rise_m: float = math.nan
    forward_m: float = 0.0
    downstream_forward: bool | None = None
    source: str = "brak"
    reversed_lines: int = 0
    reversed_m: float = 0.0


def trace_watercourses(
    u: np.ndarray, v: np.ndarray, key: np.ndarray, closed: np.ndarray
) -> tuple[list[Watercourse], np.ndarray, np.ndarray, np.ndarray]:
    """Join the lines of each watercourse end to end.

    A node continues a watercourse where exactly two of its lines meet. A joint is
    ``ok`` where one line ends and the other begins, ``glowa`` where both begin
    (head to head) and ``ogon`` where both end (tail to tail): there the digitizing
    of the watercourse changes direction. Each watercourse is walked from one of its
    free ends (or round its loop).

    Returns
    -------
    tuple
        (the watercourses; for each line its watercourse, -1 without one; whether it is
        digitized the way of the walk; its joints at its first and last point, '' when
        no line of its watercourse goes on there)
    """
    n = u.size
    at_node: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i in range(n):
        if key[i] and not closed[i]:
            at_node[(int(u[i]), key[i])].append(i)
            at_node[(int(v[i]), key[i])].append(i)
    goes_on: dict[int, dict[int, int]] = defaultdict(dict)
    joint = np.full((n, 2), "", dtype=object)
    for (node, _), members in at_node.items():
        if len(members) != 2:
            continue
        i, j = members
        goes_on[i][node], goes_on[j][node] = j, i
        i_begins, j_begins = u[i] == node, u[j] == node
        if i_begins == j_begins:
            joint_state = "glowa" if i_begins else "ogon"
        else:
            joint_state = "ok"
        for line in (i, j):
            joint[line, 0 if u[line] == node else 1] = joint_state
    course = np.full(n, -1)
    forward = np.zeros(n, dtype=bool)
    courses: list[Watercourse] = []
    for first in range(n):
        if course[first] >= 0 or not key[first] or closed[first]:
            continue
        # back to a free end, or round the loop
        line, entry, seen, loop = first, int(u[first]), {first}, False
        while entry in goes_on[line]:
            previous = goes_on[line][entry]
            if previous in seen:
                loop = True
                break
            seen.add(previous)
            entry = int(v[previous] if u[previous] == entry else u[previous])
            line = previous
        number = len(courses)
        path = []
        node = entry
        while True:
            course[line] = number
            forward[line] = u[line] == node
            path.append(line)
            node = int(v[line] if u[line] == node else u[line])
            following = goes_on[line].get(node)
            if following is None or course[following] >= 0:
                break
            line = following
        courses.append(Watercourse(key[first], path, loop, entry, node))
    return courses, course, forward, joint


def orient_watercourses(
    courses: list[Watercourse],
    profiles: Profiles,
    lengths_m: np.ndarray,
    forward: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Decide the downstream end of each watercourse and set it in the watercourse.

    The DEM along the whole watercourse decides when it rises or falls by more than
    RISE_WEAK_M between the quarters (weight 2 beyond RISE_STRONG_M, else 1); else the
    longer digitized direction (weight 1); else nothing.

    Returns
    -------
    tuple
        (for each line ``zgodny`` or ``odwrocony`` against the downstream direction of
        its watercourse, '' when undecided; the weight of that evidence)
    """
    n = lengths_m.size
    against = np.full(n, "", dtype=object)
    weight = np.zeros(n, dtype=int)
    for watercourse in courses:
        lines = np.array(watercourse.lines)
        profile = np.concatenate(
            [profiles.of(i) if forward[i] else profiles.of(i)[::-1] for i in lines]
        )
        profile = profile[~np.isnan(profile)]
        watercourse.length_m = float(lengths_m[lines].sum())
        if profile.size >= 2 and watercourse.length_m >= MIN_LENGTH_M:
            first, last = quarter_minima(profile)
            watercourse.rise_m = last - first
        watercourse.forward_m = float(lengths_m[lines][forward[lines]].sum())
        rise = watercourse.rise_m
        if not math.isnan(rise) and abs(rise) > RISE_WEAK_M:
            downstream, source = rise < 0, "nmt"
            evidence = 2 if abs(rise) > RISE_STRONG_M else 1
        elif watercourse.forward_m * 2 != watercourse.length_m:
            downstream = watercourse.forward_m * 2 > watercourse.length_m
            source, evidence = "wiekszosc", 1
        else:
            continue
        watercourse.downstream_forward, watercourse.source = downstream, source
        agree = forward[lines] == downstream
        against[lines] = np.where(agree, "zgodny", "odwrocony")
        weight[lines] = evidence
        watercourse.reversed_lines = int((~agree).sum())
        watercourse.reversed_m = float(lengths_m[lines][~agree].sum())
    return against, weight


def verdicts(
    dem_class: np.ndarray,
    in_run: np.ndarray,
    catchment: np.ndarray,
    versus_watercourse: np.ndarray,
    watercourse_weight: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weigh the evidence of each line into a verdict.

    Against the digitized direction: a clear rise of the DEM (2), a slight one (1), a
    run (1), the MPHP catchments (2), the watercourse (its weight). Along it: a fall
    of the DEM (2), the MPHP catchments (2), the watercourse (its weight). The verdict
    is ``odwrocony`` with at least 2 against and none along, or 2 more against than
    along; ``podejrzany`` with more against; ``sprzeczny`` with some against;
    ``zgodny`` with some along; ``nieustalony`` with none.

    Returns
    -------
    tuple
        (the verdicts, the evidence against, the evidence along)
    """
    against = (
        2 * (dem_class == "w_gore_wyraznie")
        + (dem_class == "w_gore_slabo")
        + in_run.astype(int)
        + 2 * (catchment == "odwrocony")
        + watercourse_weight * (versus_watercourse == "odwrocony")
    ).astype(int)
    along = (
        2 * (dem_class == "w_dol")
        + 2 * (catchment == "zgodny")
        + watercourse_weight * (versus_watercourse == "zgodny")
    ).astype(int)
    verdict = np.where(
        ((against >= 2) & (along == 0)) | (against >= along + 2),
        "odwrocony",
        np.where(
            against > along,
            "podejrzany",
            np.where(
                against >= 1, "sprzeczny", np.where(along >= 1, "zgodny", "nieustalony")
            ),
        ),
    )
    return verdict, against, along


def mouth_test(
    u: np.ndarray,
    v: np.ndarray,
    mphp: np.ndarray,
    lengths_m: np.ndarray,
    closed: np.ndarray,
) -> np.ndarray:
    """Orient the lines of each MPHP watercourse towards its mouth.

    A watercourse with the MPHP identifier K flows to where it meets its receiver: a
    node of K's lines where a line whose identifier is a proper prefix of K begins or
    ends. Along K's lines a line flows from its end farther from the mouth (by the
    length of K's lines between them) to the nearer one; with several such nodes, to
    the nearest. Independent of the DEM and of the digitized direction.

    Returns
    -------
    np.ndarray
        For each line ``zgodny`` (digitized towards the mouth), ``odwrocony`` (away
        from it) or None (no MPHP identifier, closed, no mouth reached, or both ends
        as far from it).
    """
    codes_at: dict[int, set[str]] = defaultdict(set)
    members: dict[str, list[int]] = defaultdict(list)
    for i, code in enumerate(mphp.tolist()):
        if not code:
            continue
        codes_at[int(u[i])].add(code)
        codes_at[int(v[i])].add(code)
        if not closed[i]:
            members[code].append(i)
    result = np.full(u.size, None, dtype=object)
    for code, lines in members.items():
        neighbours: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for i in lines:
            a, b, length = int(u[i]), int(v[i]), float(lengths_m[i])
            neighbours[a].append((b, length))
            neighbours[b].append((a, length))
        mouths = [
            node
            for node in neighbours
            if any(c != code and code.startswith(c) for c in codes_at[node])
        ]
        if not mouths:
            continue
        distance = dict.fromkeys(mouths, 0.0)
        heap = [(0.0, node) for node in mouths]
        while heap:
            d, node = heapq.heappop(heap)
            if d > distance[node]:
                continue
            for other, length in neighbours[node]:
                if d + length < distance.get(other, math.inf):
                    distance[other] = d + length
                    heapq.heappush(heap, (d + length, other))
        for i in lines:
            first, last = distance.get(int(u[i])), distance.get(int(v[i]))
            if first is None or last is None or first == last:
                continue
            result[i] = "zgodny" if last < first else "odwrocony"
    return result


def smoothing_directions(
    geoms: np.ndarray,
    burned: np.ndarray,
    profiles: Profiles,
    lengths_m: np.ndarray,
    mphp: np.ndarray,
    names: np.ndarray,
    connector: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Orient the burned lines as the smoothing does (ADR-077).

    ``core.hydrology._line_directions`` on the burned lines alone: their ends joined by
    ``join_ends``, the DEM along each its samples with data (``sample_profiles``), at
    most STEP_M apart.

    Returns
    -------
    tuple
        (for each line the rule that decides its direction by its Polish name
        (``RULES``), None for a line not burned or closed; whether the rule reverses
        it; whether it lies in a block that the guard of rule 2 keeps)
    """
    n = len(geoms)
    rule = np.full(n, None, dtype=object)
    reverses = np.zeros(n, dtype=bool)
    kept = np.zeros(n, dtype=bool)
    index = np.flatnonzero(burned)
    if not index.size:
        return rule, reverses, kept
    u, v, _ = join_ends(geoms[index])
    values = {}
    for k, line in enumerate(index.tolist()):
        samples = profiles.of(line)
        values[k] = samples[~np.isnan(samples)]
    directions, blocks = _line_directions(
        dict(enumerate(zip(u.tolist(), v.tolist(), strict=True))),
        values,
        dict(enumerate(lengths_m[index].tolist())),
        mphp[index].tolist(),
        names[index].tolist(),
        connector[index].tolist(),
        STEP_M,
    )
    for k, (reversed_line, name) in directions.items():
        rule[index[k]] = RULES[name]
        reverses[index[k]] = reversed_line
    for block in blocks:
        kept[index[block]] = True
    return rule, reverses, kept


def strahler_orders(
    a: np.ndarray, b: np.ndarray, use: np.ndarray, n_nodes: int
) -> np.ndarray:
    """Strahler order of the lines ``use`` running from ``a`` to ``b``, 0 elsewhere.

    The lines must have no directed cycle: a node is taken once every line of
    ``use`` ending at it has its order (Kahn's algorithm).
    """
    upstream: dict[int, list[int]] = defaultdict(list)
    downstream: dict[int, list[int]] = defaultdict(list)
    for i in np.flatnonzero(use).tolist():
        downstream[int(a[i])].append(i)
        upstream[int(b[i])].append(i)
    order = np.zeros(a.size, dtype=int)
    waiting = {node: len(upstream[node]) for node in range(n_nodes)}
    ready = deque(node for node in range(n_nodes) if waiting[node] == 0)
    while ready:
        node = ready.popleft()
        feeders = [int(order[i]) for i in upstream[node] if order[i] > 0]
        top = max(feeders, default=0)
        here = top + 1 if feeders.count(top) >= 2 else max(top, 1)
        for i in downstream[node]:
            order[i] = here
            end = int(b[i])
            waiting[end] -= 1
            if waiting[end] == 0:
                ready.append(end)
    return order


def categories(
    verdict: np.ndarray, connector: np.ndarray, detached: np.ndarray
) -> np.ndarray:
    """Set apart the doubtful reversed lines.

    A line with the verdict ``odwrocony`` is ``odwrocony_lacznik`` when it is an
    artificial connector (the DEM along it is a lake surface),
    ``odwrocony_siec_oderwana`` when its network has no main watercourse (closed
    drainage, often ending in an endorheic basin), else ``odwrocony``. Any other line
    keeps its verdict.
    """
    return np.where(
        verdict != "odwrocony",
        verdict,
        np.where(
            connector,
            "odwrocony_lacznik",
            np.where(detached, "odwrocony_siec_oderwana", "odwrocony"),
        ),
    )


def _ids(lines: list[int]) -> str:
    """Return line numbers as comma separated text."""
    return ",".join(str(i) for i in lines)


def analyze(
    raw: gpd.GeoDataFrame,
    area: BaseGeometry,
    water: np.ndarray,
    dem: np.ndarray,
    transform: Affine,
    nodata: Any,
    catchments: gpd.GeoDataFrame | None,
    burning: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Check the directions of the lines of ``read_lines``.

    Parameters
    ----------
    raw : gpd.GeoDataFrame
        The lines, as ``read_lines`` gives them.
    area : BaseGeometry
        The area; a node within EDGE_M of its boundary, or outside it, is at the edge.
    water : np.ndarray
        The water polygons.
    dem, transform, nodata
        The DEM, in EPSG:2180, around the lines.
    catchments : gpd.GeoDataFrame or None
        The MPHP catchments (``read_catchments``), or None.
    burning : str
        The lines the pipeline burns (``dem.stream_burning``): ``main`` the main
        watercourses, ``all`` every line.

    Returns
    -------
    tuple
        The layers ``odcinki``, ``wezly`` and ``cieki``.
    """
    pieces, source, part, ends_on_middle = split_at_t_junctions(raw.geometry.values)
    lines = gpd.GeoDataFrame(
        raw.drop(columns="geometry").iloc[source].reset_index(drop=True),
        geometry=pieces,
        crs=2180,
    )
    lines["czesc"] = part
    lines["dlugosc_m"] = lines.geometry.length
    geoms = lines.geometry.values
    lengths = lines["dlugosc_m"].to_numpy()
    n = len(lines)
    main = lines["glowny"].to_numpy(dtype=bool)
    connector = lines["CECHAGEOMETRII"].to_numpy(dtype=object) == CONNECTOR
    mphp = lines["IDENTYFIKATORMPHP"].to_numpy(dtype=object)
    logger.info(
        "%d lines, %d split where another line ends on them: %d pieces",
        len(raw),
        len(np.unique(source[part > 0])),
        n,
    )

    u, v, node_xy = join_ends(geoms)
    n_nodes = len(node_xy)
    node_points = shapely.points(node_xy)
    closed = u == v
    at_water = np.zeros(n_nodes, dtype=bool)
    if len(water):
        near, _ = shapely.STRtree(water).query(
            node_points, predicate="dwithin", distance=WATER_M
        )
        at_water[np.unique(near)] = True
    edge = ~shapely.contains(area.buffer(-EDGE_M), node_points)
    n_in, n_out, kind = node_kinds(u, v, edge, at_water)
    beginning, ending = incident_lines(u, v, closed)
    logger.info("%d nodes, %d closed lines", n_nodes, int(closed.sum()))

    profiles = sample_profiles(geoms, dem, transform, nodata)
    relief = line_relief(profiles)
    dem_class = dem_classes(lengths, relief.valid_share, relief.rise_m)
    if catchments is not None:
        code_from, code_to = catchment_codes(geoms, catchments)
    else:
        code_from = code_to = np.full(n, None, dtype=object)
    catchment = catchment_order(mphp, code_from, code_to)
    run, run_size = conflict_runs(v, kind, beginning)
    leaf = (kind[u] == "rozwidlenie") & (kind[v] == "slepy_koniec")

    key = watercourse_keys(mphp, lines["NAZWA"].to_numpy(dtype=object))
    courses, course, forward, joint = trace_watercourses(u, v, key, closed)
    versus, weight = orient_watercourses(courses, profiles, lengths, forward)
    verdict, against, along = verdicts(dem_class, run >= 0, catchment, versus, weight)
    mouth = mouth_test(u, v, mphp, lengths, closed)
    burned = main if burning == "main" else np.ones(n, dtype=bool)
    rule, reverses, kept = smoothing_directions(
        geoms,
        burned,
        profiles,
        lengths,
        mphp,
        lines["NAZWA"].to_numpy(dtype=object),
        connector,
    )

    # The network with the lines of the verdict odwrocony reversed
    flip = verdict == "odwrocony"
    a, b = oriented(u, v, flip)
    n_in_after, n_out_after, kind_after = node_kinds(a, b, edge, at_water)
    beginning_after, ending_after = incident_lines(a, b, closed)
    graph = coo_matrix(
        (np.ones(int((~closed).sum())), (a[~closed], b[~closed])),
        shape=(n_nodes, n_nodes),
    )
    _, component = connected_components(graph, directed=False)
    _, strong = connected_components(graph, directed=True, connection="strong")
    strong_size = np.bincount(strong)
    in_cycle = ~closed & (strong[a] == strong[b]) & (strong_size[strong[a]] > 1)
    order = strahler_orders(a, b, ~closed & ~in_cycle & main, n_nodes)
    main_components = np.unique(component[a][main & ~closed])
    detached = ~np.isin(component[a], main_components)

    lines.insert(0, "id", np.arange(n))
    lines["kod_zlewni_od"], lines["kod_zlewni_do"] = code_from, code_to
    lines["wezel_od"], lines["wezel_do"] = u, v
    lines["poprzednie"] = [_ids(ending.get(int(node), [])) for node in u]
    lines["nastepne"] = [_ids(beginning.get(int(node), [])) for node in v]
    lines["typ_od"], lines["typ_do"] = kind[u], kind[v]
    lines["z_pocz_m"] = np.round(relief.first_m, 2)
    lines["z_kon_m"] = np.round(relief.last_m, 2)
    lines["przyrost_m"] = np.round(relief.rise_m, 2)
    lines["spadek_m_km"] = np.round(relief.slope_m_km, 3)
    lines["udzial_nmt"] = np.round(relief.valid_share, 3)
    lines["nmt"] = dem_class
    lines["mphp"] = catchment
    lines["ciag_konfliktu"] = run
    lines["ciag_dlugosc"] = run_size
    lines["lisc_od_rozwidlenia"] = leaf
    lines["dowody_odwr"], lines["dowody_zgod"] = against, along
    lines["werdykt"] = verdict
    lines["wypalany"] = burned
    lines["regula"] = rule
    lines["odwraca"] = reverses
    lines["blok_zachowany"] = kept
    lines["odwrocic"] = flip
    lines["poprz_po_korekcie"] = [_ids(ending_after.get(int(x), [])) for x in a]
    lines["nast_po_korekcie"] = [_ids(beginning_after.get(int(x), [])) for x in b]
    lines["skladowa"] = component[a]
    lines["cykl"] = np.where(in_cycle, strong[a], -1)
    lines["strahler_glowne"] = np.where(~closed & ~in_cycle & main, order, -1)
    lines["konczy_na_srodku"] = ends_on_middle[source]
    lines["zamknieta"] = closed
    lines["ciek"] = key
    lines["odcinek_cieku"] = course
    lines["wzgledem_cieku"] = versus
    lines["styk_od"], lines["styk_do"] = joint[:, 0], joint[:, 1]
    lines["odwrocony_miedzy_sasiadami"] = (joint[:, 0] == "glowa") & (
        joint[:, 1] == "ogon"
    )
    lines["lacznik_jezioro"] = connector
    lines["siec_oderwana"] = detached
    lines["test_ujscia"] = mouth
    lines["kategoria"] = categories(verdict, connector, detached)

    nodes = gpd.GeoDataFrame(
        {
            "id": np.arange(n_nodes),
            "we": n_in,
            "wy": n_out,
            "typ": kind,
            "we_po": n_in_after,
            "wy_po": n_out_after,
            "typ_po": kind_after,
            "przy_wodzie": at_water,
            "krawedz": edge,
        },
        geometry=node_points,
        crs=2180,
    )
    return lines, nodes, _watercourse_layer(lines, courses, course, forward, ending)


def _watercourse_layer(
    lines: gpd.GeoDataFrame,
    courses: list[Watercourse],
    course: np.ndarray,
    forward: np.ndarray,
    ending: dict[int, list[int]],
) -> gpd.GeoDataFrame:
    """Draw each watercourse as one line, downstream, with the watercourse it joins."""
    geoms = lines.geometry.values
    names = lines["NAZWA"].to_numpy(dtype=object)
    main = lines["glowny"].to_numpy(dtype=bool)
    u = lines["wezel_od"].to_numpy()
    beginning: dict[int, list[int]] = defaultdict(list)
    for i in np.flatnonzero(~lines["zamknieta"].to_numpy()).tolist():
        beginning[int(u[i])].append(i)
    rows = []
    for number, watercourse in enumerate(courses):
        parts = [
            geoms[i] if forward[i] else shapely.reverse(geoms[i])
            for i in watercourse.lines
        ]
        merged = shapely.line_merge(shapely.multilinestrings(parts))
        downstream = watercourse.downstream_forward
        if downstream is False:
            merged = shapely.reverse(merged)
        mouth = watercourse.start if downstream is False else watercourse.end
        receivers = sorted(
            {
                int(course[i])
                for i in ending.get(mouth, []) + beginning.get(mouth, [])
                if course[i] >= 0 and course[i] != number
            }
        )
        rise = watercourse.rise_m
        rows.append(
            {
                "id": number,
                "ciek": watercourse.key,
                "nazwa": Counter(names[watercourse.lines]).most_common(1)[0][0],
                "odcinkow": len(watercourse.lines),
                "dlugosc_km": round(watercourse.length_m / 1000, 3),
                "przyrost_m": None if math.isnan(rise) else round(rise, 2),
                "kierunek_z": watercourse.source,
                "petla": watercourse.loop,
                "odwrocone_odcinki": watercourse.reversed_lines,
                "odwrocone_km": round(watercourse.reversed_m / 1000, 3),
                "glowny": bool(main[watercourse.lines].any()),
                "wezel_ujscia": int(mouth),
                "uchodzi_do": _ids(receivers),
                "geometry": merged,
            }
        )
    if not rows:
        return gpd.GeoDataFrame({"id": []}, geometry=[], crs=2180)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=2180)


def summarize(lines: gpd.GeoDataFrame) -> dict[str, Any]:
    """Count what the review needs, over the burned lines."""
    burned = lines["wypalany"].to_numpy(dtype=bool)
    length = lines["dlugosc_m"].to_numpy()
    category = lines["kategoria"].to_numpy(dtype=object)
    verdict = lines["werdykt"].to_numpy(dtype=object)
    mouth = lines["test_ujscia"].to_numpy(dtype=object)
    checked = lines["test_ujscia"].notna().to_numpy()

    def count(mask: np.ndarray) -> list[float]:
        return [int(mask.sum()), round(float(length[mask].sum()) / 1000, 1)]

    reversed_line = burned & (category == "odwrocony")
    mouth_reverses = burned & (mouth == "odwrocony") & (verdict != "odwrocony")
    rule = lines["regula"].to_numpy(dtype=object)
    reverses = lines["odwraca"].to_numpy(dtype=bool)
    return {
        "burned": count(burned),
        "reversed": {
            name: count(burned & (category == name)) for name in REVERSED_CATEGORIES
        },
        "rules": {
            name: {
                "decides": count(burned & (rule == name)),
                "reverses": count(burned & reverses & (rule == name)),
            }
            for name in RULES.values()
        },
        "rules_reverse": count(burned & reverses),
        "rules_reverse_reversed": count(reversed_line & reverses),
        "rules_reverse_others": count(burned & reverses & (category != "odwrocony")),
        "rules_against_mouth_test": count(
            burned
            & (((mouth == "odwrocony") & ~reverses) | ((mouth == "zgodny") & reverses))
        ),
        "rules_kept_by_fall": count(lines["blok_zachowany"].to_numpy(dtype=bool)),
        "mouth_checked": count(burned & checked),
        "reversed_mouth_confirms": count(reversed_line & (mouth == "odwrocony")),
        "reversed_mouth_contradicts": count(reversed_line & (mouth == "zgodny")),
        "mouth_reverses_verdict_not": count(mouth_reverses),
        "mouth_reverses_verdict_not_by_verdict": dict(Counter(verdict[mouth_reverses])),
    }


def check(
    hydro: Path,
    dem_path: Path,
    area_spec: str,
    catchments_spec: str | None,
    burning: str,
    out: Path,
) -> dict[str, Any]:
    """Read the inputs, check the directions and write the three layers to ``out``.

    Returns
    -------
    dict
        The summary of ``summarize``.
    """
    if out.exists():
        raise ValueError(f"{out} exists: give a new file")
    for path in (hydro, dem_path):
        if not path.is_file():
            raise FileNotFoundError(f"{path}: no such file")
    area = read_layer(area_spec).geometry.union_all()
    region = area.buffer(REGION_BUFFER_M)
    raw = read_lines(hydro, region)
    water = read_water(hydro, region)
    catchments = read_catchments(catchments_spec) if catchments_spec else None
    dem, transform, nodata = read_dem(dem_path, region.bounds)
    lines, nodes, courses = analyze(
        raw, area, water, dem, transform, nodata, catchments, burning
    )
    del dem
    lines.to_file(out, layer="odcinki", driver="GPKG")
    nodes.to_file(out, layer="wezly", driver="GPKG")
    courses.to_file(out, layer="cieki", driver="GPKG")
    return summarize(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the check."""
    parser = argparse.ArgumentParser(
        description=(
            "Check the flow directions of the BDOT10k watercourse lines of an area "
            "(a diagnostic, ADR-077)"
        )
    )
    parser.add_argument(
        "--hydro",
        required=True,
        help="BDOT10k GeoPackage with OT_SWRS_L, OT_SWKN_L, OT_SWRM_L and OT_PTWP_A",
    )
    parser.add_argument("--dem", required=True, help="DEM in EPSG:2180 (VRT, GeoTIFF)")
    parser.add_argument("--area", required=True, help="the area: GPKG[:layer]")
    parser.add_argument(
        "--catchments",
        default=None,
        help=f"MPHP catchments with {CATCHMENT_CODE}: GPKG[:layer] (optional)",
    )
    parser.add_argument(
        "--burning",
        choices=STREAM_BURNING_MODES,
        default="all",
        help="the lines the pipeline burns, as dem.stream_burning (default: all)",
    )
    parser.add_argument(
        "--out", required=True, help="new GeoPackage on a local disk (not a share)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    t0 = time.time()
    try:
        summary = check(
            Path(args.hydro),
            Path(args.dem),
            args.area,
            args.catchments,
            args.burning,
            Path(args.out),
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        sys.exit(1)
    for name, value in summary.items():
        logger.info("%s: %s", name, value)
    logger.info("Written to %s in %.1f s", args.out, time.time() - t0)


if __name__ == "__main__":
    main()
