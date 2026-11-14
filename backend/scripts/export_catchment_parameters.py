"""
Export the parameters of the watershed panel for the polygons of a GeoPackage.

For every polygon of a layer the script computes what the panel „Zlewnia” shows in
four sections, „Parametry podstawowe”, „Wskaźniki kształtu”, „Pokrycie terenu” and
„Grupy glebowe (HSG)”, the CN of the watershed for the three antecedent runoff
conditions, AMC I (dry), II (average) and III (wet), and as a control the runoff of
the composite CN against the weighted runoff of the soil-cover complexes, with the
polygon as the boundary of the watershed (no delineation from the NMT), and writes the
polygons with their key, the fields asked for and these values to a new GeoPackage.
The table ``<layer>_units`` of that GeoPackage gives the unit, the section, the row
of the panel and the source of each column.

The values come from the code behind the panel, on the rasters that the pipeline
saved in DEM_DIR (``dem_mosaic_02_filled``, ``_03_flowdir``, ``_04_flowacc``,
``_04b_stream_distance``, ``_05_slope`` and ``_10_subcatchments_<threshold>``) and
on the database: the zonal statistics of the sub-catchments (core.zonal_stats) over
the cells whose centre lies in the polygon, the flow paths of core.divide_flow_path,
the overland segment and the BDOT10k part of the main channel of
core.cell_parameters, the shape indices of core.morphometry and the land cover, the CN
of its soil-cover complexes and the soil groups of core.watershed_service. What needs
an outlet takes the cell of the largest flow accumulation in the polygon, and the flow
paths start in the part of the polygon that drains to it. The main channel runs up
the stream network of the threshold from the outlet, at each confluence into the
branch of the larger accumulation, as CatchmentGraph.trace_main_channel does, to its
source or to where it flows in from outside the polygon. The length and the mean
width of the watershed and the shape indices computed from them (elongation, form
factor, lemniscate) are left out.

Usage
-----
    cd backend
    python -m scripts.export_catchment_parameters --input zlewnie.gpkg \
        --layer zlew_h_07 --key ID_HYD_10 --keep ID_HYD_50,NAZ_ZLEWNI \
        --output parametry.gpkg
"""

import argparse
import json
import logging
import sys
import time
import warnings
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyflwdir
import rasterio
from hydrolog.runoff import AMC
from pyproj import CRS
from rasterio.features import geometry_mask
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.active_run import active_run_raster
from core.attribution import CATCHMENT, ProviderLines, instance_lines
from core.cell_parameters import (
    INTERMEDIATE_SUFFIXES,
    CellWindow,
    PipelineRasters,
    channel_parameters,
    d8_from_saved_flowdir,
    flow_path_parameters,
    outlet_cell,
    read_cell_window,
    terrain,
)
from core.cn_tables import cn_for_amc, runoff_mm, weighted_runoff_mm
from core.config import get_settings
from core.constants import CRS_PL1992, M2_PER_KM2, M_PER_KM
from core.database import get_db_session
from core.land_cover import get_land_cover_for_boundary
from core.morphometry import area_perimeter_indices
from core.version import get_version
from core.watershed_service import build_hsg_stats
from utils.geometry import transform_pl1992_to_wgs84

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Threshold [m²] of the main channel, the overland segment and the BDOT10k length:
# the default of „Próg akumulacji spływu” of the panel (js/layers.js)
PANEL_THRESHOLD_M2 = 100_000
# A polygon of fewer cells with NMT data gets the quality flag under_100_cells
MIN_CELLS = 100
# The panel queries the land cover of a watershed larger than 5 km² with its
# boundary simplified by 20 m (api.endpoints.watershed._build_watershed_response)
LAND_COVER_SIMPLIFY_ABOVE_KM2 = 5.0
LAND_COVER_SIMPLIFY_M = 20.0
# Storm depths P [mm] of the control columns of the runoff (ADR-075): the runoff of the
# composite CN against the area-weighted runoff of the soil-cover complexes, AMC II
CONTROL_STORMS_MM = (25, 50)
# Land cover categories of the database, in the order of the panel: the category,
# the stem of its columns and its label in the panel
LAND_COVER_CLASSES = (
    ("grunt_orny", "grunt_orny", "Grunty orne"),
    ("las", "las", "Lasy"),
    ("łąka", "laka", "Łąki i pastwiska"),
    ("zabudowa_mieszkaniowa", "zabudowa_mieszkaniowa", "Zabudowa mieszkaniowa"),
    ("zabudowa_przemysłowa", "zabudowa_przemyslowa", "Zabudowa przemysłowa"),
    ("droga", "droga", "Drogi"),
    ("woda", "woda", "Wody"),
    ("inny", "inny", "Inne"),
)
# Hydrologic soil groups and their labels in the panel (js/charts.js)
HSG_CLASSES = (
    ("A", "A: przepuszczalne"),
    ("B", "B: średnio przepuszczalne"),
    ("C", "C: słabo przepuszczalne"),
    ("D", "D: nieprzepuszczalne"),
)
DEFAULT_OUTPUT_LAYER = "catchment_parameters"

_BASIC = "Parametry podstawowe"
_SHAPE = "Wskaźniki kształtu"
_LAND_COVER = "Pokrycie terenu"
_HSG = "Grupy glebowe (HSG)"
_HYDROGRAPH = "Hydrogram"
_CONTROL = "Kontrola"


@dataclass(frozen=True)
class Column:
    """A column of the output layer.

    Attributes
    ----------
    name : str
        Column name, with the unit as its suffix.
    unit : str
        Unit ("-" without one).
    section : str
        Section of the panel „Zlewnia”, or „Kontrola” for a control column.
    panel_label : str
        Row of the panel; for a control column a Polish label or "".
    description : str
        What the value is and the code of Hydrograf it comes from.
    dtype : str
        pandas dtype of the column.
    """

    name: str
    unit: str
    section: str
    panel_label: str
    description: str
    dtype: str = "float64"


COLUMNS: tuple[Column, ...] = (
    Column(
        "area_km2",
        "km2",
        _BASIC,
        "Powierzchnia zlewni",
        "Cells of the polygon with NMT data times the cell area, as the area of "
        "a sub-catchment (core.zonal_stats.zonal_summary) that the catchment "
        "graph sums",
    ),
    Column(
        "perimeter_km",
        "km",
        _BASIC,
        "Obwód zlewni",
        "Length of the boundary of the polygon, every part and hole "
        "(build_morph_dict_from_graph)",
    ),
    Column(
        "elevation_min_m",
        "m n.p.m.",
        _BASIC,
        "Wysokość min.",
        "Lowest cell of the filled DEM in the polygon (zonal_summary)",
    ),
    Column(
        "elevation_max_m",
        "m n.p.m.",
        _BASIC,
        "Wysokość max.",
        "Highest cell of the filled DEM in the polygon (zonal_summary)",
    ),
    Column(
        "elevation_mean_m",
        "m n.p.m.",
        _BASIC,
        "Wysokość średnia",
        "Mean of the filled DEM over the cells of the polygon (zonal_summary)",
    ),
    Column(
        "mean_slope_m_per_m",
        "m/m",
        _BASIC,
        "Średni spadek terenu",
        "Mean of the slope raster over the cells of the polygon (zonal_summary); "
        "the panel shows it times 100 in %",
    ),
    Column(
        "channel_length_km",
        "km",
        _BASIC,
        "Długość cieku głównego",
        "Main channel along the DEM stream network of the threshold, from the "
        "outlet up to its source or to where it flows in from outside the "
        "polygon, at each confluence into the branch of the larger flow "
        "accumulation (CatchmentGraph.trace_main_channel); empty when the outlet "
        "is not on that network",
    ),
    Column(
        "real_channel_length_km",
        "km",
        _BASIC,
        "Długość cieku wg BDOT10k",
        "Part of the main channel along BDOT10k streams from the outlet "
        "(core.catchment_graph.contiguous_real_length_km with the flags of "
        "stream_network); like the panel it measures a segment along the "
        "smoothed line of stream_network, so it can be shorter than "
        "channel_length_km with every segment in BDOT10k",
    ),
    Column(
        "channel_slope_m_per_m",
        "m/m",
        _BASIC,
        "Spadek cieku głównego",
        "(Elevation of the source of the main channel - outlet elevation) / "
        "channel length; empty when not positive",
    ),
    Column(
        "flow_path_length_km",
        "km",
        _BASIC,
        "Najdłuższa droga spływu",
        "Flow distance from the cell of the polygon draining to the outlet that "
        "is farthest from it, to the cell below the outlet "
        "(core.divide_flow_path.watershed_flow_paths)",
    ),
    Column(
        "flow_path_slope_m_per_m",
        "m/m",
        _BASIC,
        "Spadek najdłuższej drogi spływu",
        "(Elevation of the head of the longest flow path - outlet elevation) / "
        "its length; empty when not positive",
    ),
    Column(
        "overland_length_km",
        "km",
        _BASIC,
        "Spływ powierzchniowy – długość",
        "Longest flow path from its head to the first cell of the DEM stream "
        "network of the threshold (core.cell_parameters.overland_segments)",
    ),
    Column(
        "overland_slope_m_per_m",
        "m/m",
        _BASIC,
        "Spływ powierzchniowy – spadek",
        "Drop along the overland segment / its length; empty when not positive",
    ),
    Column(
        "divide_flow_path_km",
        "km",
        _BASIC,
        "Najdłuższa droga spływu od granicy zlewni",
        "Longest flow path from a boundary cell of the part of the polygon "
        "draining to the outlet (watershed_flow_paths); empty when it starts at "
        "the head of the longest flow path, as the panel leaves the row out",
    ),
    Column(
        "cn",
        "-",
        _BASIC,
        "CN (krzywa odpływu)",
        "CN for AMC II (average antecedent runoff condition), the value of the panel: "
        "area-weighted composite CN of the soil-cover complexes of the polygon, land "
        "cover x hydrologic soil group, from the TR-55 table of Hydrolog "
        "(core.land_cover.get_land_cover_for_boundary, ADR-075); equal to cn_amc_ii",
    ),
    Column(
        "cn_amc_i",
        "-",
        _HYDROGRAPH,
        "CN użyty (AMC I)",
        "CN for AMC I (dry antecedent runoff condition): cn_amc_ii converted by "
        "Hydrolog (SCSCN.adjust_cn_for_amc: Hawkins et al. 1985, "
        "CN_I = CN / (2.281 - 0.01281 CN), which approximates NEH 630 chapter 10, "
        "table 10-1), an integer, as the hydrograph converts it",
    ),
    Column(
        "cn_amc_ii",
        "-",
        _HYDROGRAPH,
        "CN użyty (AMC II)",
        "CN for AMC II (average antecedent runoff condition, the condition of the "
        "TR-55 tables): equal to cn, the area-weighted composite CN, which the "
        "hydrograph takes unconverted",
    ),
    Column(
        "cn_amc_iii",
        "-",
        _HYDROGRAPH,
        "CN użyty (AMC III)",
        "CN for AMC III (wet antecedent runoff condition): cn_amc_ii converted by "
        "Hydrolog (Hawkins et al. 1985, CN_III = CN / (0.427 + 0.00573 CN), which "
        "approximates NEH 630 chapter 10, table 10-1), an integer, as cn_amc_i",
    ),
    Column(
        "outlet_latitude_deg",
        "°N",
        _BASIC,
        "Ujście — szerokość φ",
        "Centre of the cell of the largest flow accumulation in the polygon, "
        "WGS84; the panel takes the end of the outlet's stream segment, at most "
        "a cell away",
    ),
    Column(
        "outlet_longitude_deg",
        "°E",
        _BASIC,
        "Ujście — długość λ",
        "As outlet_latitude_deg",
    ),
    Column(
        "outlet_elevation_m",
        "m n.p.m.",
        _BASIC,
        "Ujście — wysokość",
        "Filled DEM at the outlet cell; the panel shows the lowest elevation of "
        "the watershed, the same cell for a watershed delineated from the NMT",
    ),
    Column(
        "compactness_coefficient",
        "-",
        _SHAPE,
        "Wsk. zwartości Cz",
        "Gravelius Kc = P / (2 sqrt(pi A)) of area_km2 and perimeter_km "
        "(core.morphometry.area_perimeter_indices)",
    ),
    Column(
        "circularity_ratio",
        "-",
        _SHAPE,
        "Wsk. kolistości Ck",
        "Miller Rc = 4 pi A / P^2 of area_km2 and perimeter_km "
        "(area_perimeter_indices)",
    ),
    *(
        column
        for category, stem, label in LAND_COVER_CLASSES
        for column in (
            Column(
                f"lc_{stem}_pct",
                "%",
                _LAND_COVER,
                label,
                f"Share of „{category}” in the land cover of the polygon "
                "(get_land_cover_for_boundary); 0 when absent, empty without land "
                "cover",
            ),
            Column(
                f"lc_{stem}_cn",
                "-",
                _LAND_COVER,
                f"{label}: CN",
                f"CN (AMC II) of „{category}”, area-weighted over its soil-cover "
                "complexes (its pieces on each soil group); empty when absent",
            ),
        )
    ),
    *(
        Column(
            f"hsg_{group.lower()}_pct",
            "%",
            _HSG,
            label,
            f"Share of the soil group {group} in the polygon, of its area with soil "
            "groups (core.watershed_service.build_hsg_stats); 0 when absent, empty "
            "without soil groups",
        )
        for group, label in HSG_CLASSES
    ),
    Column(
        "lc_without_hsg_pct",
        "%",
        _CONTROL,
        "",
        "Share of the land cover of the polygon outside the soil groups: its soil "
        "groups follow the shares of the rest of the polygon (group B without any, "
        "ADR-075)",
    ),
    *(
        column
        for p in CONTROL_STORMS_MM
        for column in (
            Column(
                f"q_cn_mm_p{p}",
                "mm",
                _CONTROL,
                f"Opad efektywny z CN zlewni (P = {p} mm)",
                f"Runoff depth Q of a storm of P = {p} mm, AMC II, from the composite "
                "CN (cn_amc_ii) by Hydrolog's SCS-CN equation of NEH 630 chapter 10 "
                "(SCSCN.effective_precipitation, Ia = 0.2 S; "
                "core.cn_tables.runoff_mm), as the hydrograph computes the runoff; to "
                "0.01 mm, empty without land cover",
            ),
            Column(
                f"q_weighted_mm_p{p}",
                "mm",
                _CONTROL,
                f"Opad efektywny ważony po kompleksach (P = {p} mm)",
                "Area-weighted runoff depth of the soil-cover complexes of the polygon "
                f"for P = {p} mm, AMC II: the Q of each complex from its own CN by the "
                "same equation (core.cn_tables.weighted_runoff_mm), the method of "
                "weighted Q of USDA-NRCS NEH 630 chapter 10, p. 10-10. Its difference "
                f"from q_cn_mm_p{p} is the error of the composite CN for that storm, "
                "largest for small storms and a wide spread of the CN (ADR-075); to "
                "0.01 mm, empty without land cover",
            ),
        )
    ),
    Column(
        "polygon_area_km2",
        "km2",
        _CONTROL,
        "",
        "Area of the polygon geometry",
    ),
    Column(
        "outlet_upstream_area_km2",
        "km2",
        _CONTROL,
        "",
        "Flow accumulation of the NMT at the outlet cell times the cell area: the "
        "watershed the NMT gives that outlet",
    ),
    Column(
        "polygon_to_upstream_area_ratio",
        "-",
        _CONTROL,
        "",
        "polygon_area_km2 / outlet_upstream_area_km2: about 1 for a polygon that "
        "is the NMT watershed of its outlet, less with inflow from outside it",
    ),
    Column(
        "cell_count",
        "-",
        _CONTROL,
        "",
        "Cells of the NMT grid whose centre lies in the polygon and that have data",
        dtype="int64",
    ),
    Column(
        "quality_flag",
        "-",
        _CONTROL,
        "",
        f"Semicolon-separated: under_{MIN_CELLS}_cells (fewer cells with NMT "
        "data), partly_outside_nmt (some cells of the polygon without NMT data: "
        "the values describe the rest), outside_nmt (no cell with NMT data); "
        "empty when none",
        dtype="object",
    ),
)
COLUMN_NAMES = tuple(column.name for column in COLUMNS)


def is_pl1992(crs: CRS) -> bool:
    """Whether a CRS is PL-1992 (EPSG:2180) on any realisation of ETRS89.

    ESRI:102173 (ETRS_1989_UWPP_1992) and EPSG:2180 (ETRF2000-PL / CS92 in the
    current EPSG database) differ only in the name of the datum, which pyproj does
    not ignore; the projection and its ellipsoid are compared instead.

    Parameters
    ----------
    crs : CRS
        The CRS to check.

    Returns
    -------
    bool
        True for PL-1992.
    """
    target = CRS.from_epsg(2180)
    if crs.equals(target, ignore_axis_order=True):
        return True
    with warnings.catch_warnings():
        # A PROJ string drops the datum, which is what the comparison needs
        warnings.simplefilter("ignore", UserWarning)
        return bool(crs.is_projected and crs.to_proj4() == target.to_proj4())


@contextmanager
def open_rasters(dem_dir: Path, threshold_m2: int) -> Iterator[PipelineRasters]:
    """Open the rasters of the pipeline in a directory.

    With an active unit run in ``dem_dir`` (``active_run.json``) its VRT mosaics are
    read, as the API reads them; otherwise the GeoTIFFs of a single-raster run.

    Parameters
    ----------
    dem_dir : Path
        Directory of the rasters (DEM_DIR of the API).
    threshold_m2 : int
        Threshold of the label raster.

    Yields
    ------
    PipelineRasters
        The open rasters.

    Raises
    ------
    FileNotFoundError
        When a raster is missing.
    ValueError
        When the rasters are not on one grid or not in PL-1992.
    """
    suffixes = dict(INTERMEDIATE_SUFFIXES)
    suffixes["labels"] = f"10_subcatchments_{threshold_m2}"
    # The VRT mosaics of an active unit run take precedence, as for the API
    paths = {
        name: active_run_raster(dem_dir, suffix) or dem_dir / f"dem_mosaic_{suffix}.tif"
        for name, suffix in suffixes.items()
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Rasters of the pipeline not found: " + ", ".join(missing)
        )
    with ExitStack() as stack:
        sources = {
            name: stack.enter_context(rasterio.open(path))
            for name, path in paths.items()
        }
        dem = sources["filled_dem"]
        for name, source in sources.items():
            if (source.shape, source.transform) != (dem.shape, dem.transform):
                raise ValueError(
                    f"{paths[name]} is not on the grid of {paths['filled_dem']}"
                )
        if dem.crs is None or not is_pl1992(CRS.from_user_input(dem.crs)):
            raise ValueError(f"{paths['filled_dem']} is not in PL-1992 (EPSG:2180)")
        yield PipelineRasters(
            filled_dem=dem,
            slope=sources["slope"],
            acc=sources["acc"],
            fdir=sources["fdir"],
            flow_dist=sources["flow_dist_m"],
            labels=sources["labels"],
            threshold_m2=threshold_m2,
        )


@dataclass(frozen=True)
class PolygonCells(CellWindow):
    """The rasters in a window around a polygon, and the cells of the polygon.

    ``member`` is ``inside & valid``: the cells of the polygon.

    Attributes
    ----------
    inside : np.ndarray
        Cells whose centre lies in the polygon.
    """

    inside: np.ndarray


def read_polygon_cells(
    geometry: BaseGeometry, rasters: PipelineRasters
) -> PolygonCells:
    """Read the rasters around a polygon: its bounding box and one cell more.

    Parameters
    ----------
    geometry : BaseGeometry
        Polygon or MultiPolygon in EPSG:2180.
    rasters : PipelineRasters
        Open rasters.

    Returns
    -------
    PolygonCells
        The windows and the cells of the polygon.
    """
    window = read_cell_window(rasters, geometry.bounds)
    inside = geometry_mask(
        [geometry],
        out_shape=window.valid.shape,
        transform=window.transform,
        invert=True,
    )
    arrays = {field.name: getattr(window, field.name) for field in fields(window)}
    arrays["member"] = inside & window.valid
    return PolygonCells(**arrays, inside=inside)


def polygon_parameters(
    geometry: BaseGeometry, rasters: PipelineRasters, db: Session
) -> dict[str, Any]:
    """Compute the columns of COLUMNS for a polygon.

    Parameters
    ----------
    geometry : BaseGeometry
        Valid Polygon or MultiPolygon in EPSG:2180.
    rasters : PipelineRasters
        Open rasters of the pipeline.
    db : Session
        Database session (land cover and the BDOT10k flags of ``stream_network``).

    Returns
    -------
    dict[str, Any]
        Value of each column of COLUMN_NAMES; None where it cannot be computed (a
        polygon without cells with NMT data has only its land cover, perimeter,
        area and flags).
    """
    row: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    polygon_area_km2 = geometry.area / M2_PER_KM2
    row["polygon_area_km2"] = round(polygon_area_km2, 4)
    row["perimeter_km"] = round(geometry.length / M_PER_KM, 4)

    cells = read_polygon_cells(geometry, rasters)
    cell_count = int(np.count_nonzero(cells.member))
    row["cell_count"] = cell_count
    flags = []
    if cell_count < MIN_CELLS:
        flags.append(f"under_{MIN_CELLS}_cells")
    if cell_count and np.any(cells.inside & ~cells.valid):
        flags.append("partly_outside_nmt")
    elif not cell_count and np.any(cells.inside):
        flags.append("outside_nmt")
    row["quality_flag"] = ";".join(flags) or None

    area_km2 = polygon_area_km2
    if cell_count:
        terrain_row, area_km2 = terrain(cells, rasters.cellsize_m)
        row.update(terrain_row)
        row.update(area_perimeter_indices(area_km2, row["perimeter_km"]))
        outlet = outlet_cell(cells)
        row.update(_outlet_columns(cells, outlet, rasters.cellsize_m, polygon_area_km2))
        row.update(_flow_path_columns(cells, outlet, rasters))
        row.update(channel_parameters(cells, outlet, rasters, db))
    row.update(_land_cover_columns(geometry, area_km2, db))
    return row


def _outlet_columns(
    cells: PolygonCells,
    outlet: tuple[int, int],
    cellsize_m: float,
    polygon_area_km2: float,
) -> dict[str, Any]:
    """Position and elevation of the outlet and the NMT watershed of it."""
    x, y = cells.transform * (outlet[1] + 0.5, outlet[0] + 0.5)
    lon, lat = transform_pl1992_to_wgs84(x, y)
    upstream_km2 = float(cells.acc[outlet]) * cellsize_m * cellsize_m / M2_PER_KM2
    return {
        "outlet_latitude_deg": round(lat, 6),
        "outlet_longitude_deg": round(lon, 6),
        "outlet_elevation_m": round(float(cells.dem[outlet]), 2),
        "outlet_upstream_area_km2": round(upstream_km2, 4),
        "polygon_to_upstream_area_ratio": (
            round(polygon_area_km2 / upstream_km2, 4) if upstream_km2 > 0 else None
        ),
    }


def _flow_path_columns(
    cells: PolygonCells, outlet: tuple[int, int], rasters: PipelineRasters
) -> dict[str, Any]:
    """Longest flow path, its slope and overland segment, and the divide path.

    The flow paths start in the part of the polygon that drains to the outlet:
    the cells of the polygon in the pyflwdir basin of the outlet.
    """
    d8 = d8_from_saved_flowdir(cells.fdir, cells.flow_dist, cells.valid)
    d8[outlet] = 0  # the pit that the basin of the outlet and the paths end in
    flw = pyflwdir.from_array(d8, ftype="d8", transform=cells.transform, latlon=False)
    basin = flw.basins(idxs=np.array([np.ravel_multi_index(outlet, d8.shape)]))
    drained = replace(cells, member=cells.member & (basin > 0))
    values, _ = flow_path_parameters(drained, d8, outlet, rasters.threshold_cells)
    return values


def _land_cover_columns(
    geometry: BaseGeometry, area_km2: float, db: Session
) -> dict[str, Any]:
    """CN, land cover, soil groups and control runoff of the polygon.

    The CN for AMC II, also as ``cn_amc_ii``, and for AMC I and III (Hydrolog's
    conversion of the CN for AMC II, as in the hydrograph), the share and the CN of
    each land cover class, the share of each soil group, the share of the land cover
    without one and, for each storm of ``CONTROL_STORMS_MM``, the runoff of the CN for
    AMC II and the area-weighted runoff of the soil-cover complexes (ADR-075). The
    boundary is simplified as the panel simplifies it.
    """
    tolerance = (
        LAND_COVER_SIMPLIFY_M if area_km2 > LAND_COVER_SIMPLIFY_ABOVE_KM2 else None
    )
    query_boundary = geometry if tolerance is None else geometry.simplify(tolerance)
    stats = get_land_cover_for_boundary(query_boundary, db)
    result: dict[str, Any] = {
        "cn": None,
        "cn_amc_i": None,
        "cn_amc_ii": None,
        "cn_amc_iii": None,
        "lc_without_hsg_pct": None,
    }
    for _, stem, _ in LAND_COVER_CLASSES:
        result[f"lc_{stem}_pct"] = None
        result[f"lc_{stem}_cn"] = None
    for group, _ in HSG_CLASSES:
        result[f"hsg_{group.lower()}_pct"] = None
    for p in CONTROL_STORMS_MM:
        result[f"q_cn_mm_p{p}"] = None
        result[f"q_weighted_mm_p{p}"] = None
    if stats is not None:
        cn = stats["weighted_cn"]
        result["cn"] = cn
        result["cn_amc_i"] = cn_for_amc(cn, AMC.I)
        result["cn_amc_ii"] = cn
        result["cn_amc_iii"] = cn_for_amc(cn, AMC.III)
        result["lc_without_hsg_pct"] = stats["hsg_assumed_pct"]
        by_category = {c["category"]: c for c in stats["categories"]}
        for category, stem, _ in LAND_COVER_CLASSES:
            entry = by_category.get(category)
            result[f"lc_{stem}_pct"] = 0.0 if entry is None else entry["percentage"]
            result[f"lc_{stem}_cn"] = None if entry is None else entry["cn_value"]
        for p in CONTROL_STORMS_MM:
            result[f"q_cn_mm_p{p}"] = round(runoff_mm(cn, p), 2)
            result[f"q_weighted_mm_p{p}"] = round(
                weighted_runoff_mm(stats["complexes"], p), 2
            )
    soils = build_hsg_stats(query_boundary, db)
    if soils is not None:
        by_group = {c.group: c.percentage for c in soils.categories}
        for group, _ in HSG_CLASSES:
            result[f"hsg_{group.lower()}_pct"] = round(by_group.get(group, 0.0), 1)
    return result


def read_polygons(
    path: Path, layer: str | None, key: str, keep: Sequence[str]
) -> gpd.GeoDataFrame:
    """Read the polygons of a layer with their key and the fields to keep.

    Parameters
    ----------
    path : Path
        GeoPackage (or any file GDAL reads).
    layer : str | None
        Layer; None for the only layer of the file.
    key : str
        Field with a unique, non-empty value per polygon.
    keep : Sequence[str]
        Other fields to keep.

    Returns
    -------
    gpd.GeoDataFrame
        The key, the kept fields and the geometry, in EPSG:2180.

    Raises
    ------
    ValueError
        When the layer is not in PL-1992 (EPSG:2180, or ESRI:102173), a field is
        missing, the key is empty or repeated, or a geometry is not a valid
        Polygon or MultiPolygon.
    """
    if layer is None:
        layers = gpd.list_layers(path)
        if len(layers) != 1:
            raise ValueError(
                f"{path} has {len(layers)} layers ({', '.join(layers['name'])}); "
                "choose one with --layer"
            )
        layer = str(layers["name"].iloc[0])
    frame = gpd.read_file(path, layer=layer)
    source = f"{path} (layer {layer})"
    if frame.crs is None:
        raise ValueError(f"{source} has no CRS; the rasters are in EPSG:2180")
    if not is_pl1992(frame.crs):
        raise ValueError(
            f"CRS mismatch: {source} is in {frame.crs.name} "
            f"({frame.crs.to_string()}), the rasters in EPSG:2180 (PL-1992); "
            "reproject the layer to EPSG:2180"
        )
    missing = [field for field in (key, *keep) if field not in frame.columns]
    if missing:
        raise ValueError(f"{source} has no field {', '.join(missing)}")
    if frame[key].isna().any() or frame[key].duplicated().any():
        repeated = frame.loc[frame[key].duplicated(keep=False), key].unique()
        raise ValueError(
            f"The key {key} of {source} must be unique and not empty "
            f"(empty: {int(frame[key].isna().sum())}, repeated: {list(repeated)[:5]})"
        )
    geometry = frame.geometry
    bad = ~geometry.geom_type.isin(["Polygon", "MultiPolygon"]) | geometry.is_empty
    bad |= ~bad & ~geometry.is_valid
    if bad.any():
        raise ValueError(
            f"{int(bad.sum())} features of {source} are not valid polygons "
            f"({key}: {list(frame.loc[bad, key])[:5]}); repair them first"
        )
    return frame[[key, *keep, "geometry"]].set_crs(CRS_PL1992, allow_override=True)


def write_output(
    polygons: gpd.GeoDataFrame,
    rows: Sequence[dict[str, Any]],
    output: Path,
    layer: str,
    metadata: dict[str, str],
    lines: ProviderLines,
) -> None:
    """Write the polygons with their columns, the table of the units and the lines.

    Parameters
    ----------
    polygons : gpd.GeoDataFrame
        Key, kept fields and geometry (EPSG:2180).
    rows : Sequence[dict[str, Any]]
        Values of the columns of each polygon, in the order of ``polygons``.
    output : Path
        New GeoPackage.
    layer : str
        Layer of the polygons; the units go to ``<layer>_units``.
    metadata : dict[str, str]
        Metadata of the layer (GDAL metadata items of the GeoPackage).
    lines : ProviderLines
        The lines of the providers of the data (Nogat DEV §20): the metadata items
        ``attribution`` and ``terms_notice`` of the layer, each a JSON array as in a
        Parquet file, and the table ``<layer>_attribution``, one line per row in
        their order.
    """
    values = pd.DataFrame(list(rows), columns=list(COLUMN_NAMES), index=polygons.index)
    for column in COLUMNS:
        values[column.name] = values[column.name].astype(column.dtype)
    frame = gpd.GeoDataFrame(
        pd.concat([polygons.drop(columns=polygons.geometry.name), values], axis=1),
        geometry=polygons.geometry,
        crs=CRS_PL1992,
    )
    metadata = {
        **metadata,
        "attribution": json.dumps(list(lines.attribution), ensure_ascii=False),
        "terms_notice": json.dumps(list(lines.terms_notice), ensure_ascii=False),
    }
    frame.to_file(output, layer=layer, driver="GPKG", metadata=metadata)
    units = pd.DataFrame(
        {
            "column_name": [c.name for c in COLUMNS],
            "unit": [c.unit for c in COLUMNS],
            "section": [c.section for c in COLUMNS],
            "panel_label": [c.panel_label for c in COLUMNS],
            "description": [c.description for c in COLUMNS],
        }
    )
    gpd.GeoDataFrame(units).to_file(output, layer=f"{layer}_units", driver="GPKG")
    kinds = [("attribution", lines.attribution), ("terms_notice", lines.terms_notice)]
    attribution = pd.DataFrame(
        [{"field": field, "line": text} for field, texts in kinds for text in texts],
        columns=["field", "line"],
    )
    gpd.GeoDataFrame(attribution).to_file(
        output, layer=f"{layer}_attribution", driver="GPKG"
    )


def export(
    input_path: Path,
    layer: str | None,
    key: str,
    keep: Sequence[str],
    output: Path,
    output_layer: str,
    dem_dir: Path,
    threshold_m2: int,
    db: Session,
) -> int:
    """Compute the columns of every polygon of a layer and write them.

    Parameters
    ----------
    input_path, layer, key, keep
        The polygons (read_polygons).
    output : Path
        New GeoPackage; it must not exist.
    output_layer : str
        Layer of the output.
    dem_dir : Path
        Directory of the rasters of the pipeline.
    threshold_m2 : int
        Threshold of the stream network [m²].
    db : Session
        Database session.

    Returns
    -------
    int
        Number of polygons written.

    Raises
    ------
    FileNotFoundError
        When a raster is missing.
    ValueError
        When the output exists, the input is refused (read_polygons), the rasters
        are not on one grid in PL-1992 or the database has no stream network of
        the threshold.
    """
    if output.exists():
        raise ValueError(f"{output} exists; remove it or choose another --output")
    polygons = read_polygons(input_path, layer, key, keep)
    has_threshold = db.execute(
        text("SELECT EXISTS (SELECT 1 FROM stream_network WHERE threshold_m2 = :t)"),
        {"t": threshold_m2},
    ).scalar()
    if not has_threshold:
        raise ValueError(f"The database has no stream network of {threshold_m2} m²")
    rows = []
    with open_rasters(dem_dir, threshold_m2) as rasters:
        for i, (value, geometry) in enumerate(
            zip(polygons[key], polygons.geometry, strict=True), start=1
        ):
            t0 = time.perf_counter()
            row = polygon_parameters(geometry, rasters, db)
            rows.append(row)
            logger.info(
                "%d/%d %s=%s: %s km2, %d cells, %s (%.1f s)",
                i,
                len(polygons),
                key,
                value,
                row["area_km2"],
                row["cell_count"],
                row["quality_flag"] or "ok",
                time.perf_counter() - t0,
            )
    # The parameters are of the NMT burned with the BDOT10k watercourses, the BDOT10k
    # land cover and the SoilGrids soil groups (Nogat DEV §20)
    lines = instance_lines(CATCHMENT, get_settings().frontend_data_dir)
    write_output(
        polygons,
        rows,
        output,
        output_layer,
        {
            "hydrograf_version": get_version(),
            "source": f"{input_path} ({layer or 'only layer'})",
            "dem_dir": str(dem_dir),
            "threshold_m2": str(threshold_m2),
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        lines,
    )
    for line in (*lines.attribution, *lines.terms_notice):
        logger.info(line)
    return len(rows)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the export."""
    parser = argparse.ArgumentParser(
        description=(
            "Export the parameters of the watershed panel (basic parameters, shape "
            "indices, land cover) for the polygons of a GeoPackage"
        )
    )
    parser.add_argument("--input", required=True, help="GeoPackage of the polygons")
    parser.add_argument(
        "--layer", default=None, help="Layer of the polygons (default: the only one)"
    )
    parser.add_argument(
        "--key", required=True, help="Field with a unique value per polygon"
    )
    parser.add_argument(
        "--keep",
        default="",
        help="Comma-separated fields to keep besides the key (ID_HYD_50,NAZ_ZLEWNI)",
    )
    parser.add_argument("--output", required=True, help="New GeoPackage")
    parser.add_argument(
        "--output-layer",
        default=DEFAULT_OUTPUT_LAYER,
        help=f"Layer of the output (default: {DEFAULT_OUTPUT_LAYER})",
    )
    parser.add_argument(
        "--threshold-m2",
        type=int,
        default=PANEL_THRESHOLD_M2,
        help=(
            "Flow accumulation threshold of the stream network [m²] for the main "
            f"channel and the overland segment (default: {PANEL_THRESHOLD_M2}, the "
            "default of the panel)"
        ),
    )
    parser.add_argument(
        "--dem-dir",
        default=None,
        help="Directory of the rasters of the pipeline (default: DEM_DIR)",
    )
    args = parser.parse_args(argv)

    t0 = time.time()
    try:
        with get_db_session() as db:
            count = export(
                Path(args.input),
                args.layer,
                args.key,
                [field for field in args.keep.split(",") if field],
                Path(args.output),
                args.output_layer,
                Path(args.dem_dir or get_settings().dem_dir),
                args.threshold_m2,
                db,
            )
    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        sys.exit(1)
    logger.info(
        "%d polygons written to %s in %.1f s", count, args.output, time.time() - t0
    )


if __name__ == "__main__":
    main()
