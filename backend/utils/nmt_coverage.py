"""Whether the NMT sheets of a bootstrap cover its area (ADR-076).

Step 3 mosaics the sheets it is given, and a gap in that mosaic is nodata: inside the
area it cuts the area off, and enclosed by the sheets it is an outlet of the depression
fill, so the land around it drains into it (h07, set 2026: one sheet missing, 4.9 km²
of nodata drained 40 km²). The gap is measured on the sheet grid, not on the rasters:
the frames of the sheets (their meridians and parallels, ``SheetParser.get_bbox`` in
EPSG:4326, projected to EPSG:2180) are unioned, and what of the area, and of every
hole the frames enclose, lies outside them is uncovered. Parts narrower than the
tolerance (a few cells: an outline drawn a little beyond the frame) are not counted.
The missing sheets are those of Kartograf's sheet grid that overlap the uncovered part.
"""

import logging
from collections.abc import Collection, Iterator
from dataclasses import dataclass

import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.errors import NoDataError
from utils.kartograf_store import SHEET_SYSTEM

logger = logging.getLogger(__name__)

# The cells of the NMT grid below which an uncovered part is not counted.
TOLERANCE_CELLS = 3
# The longest edge, in degrees, of a frame before it is projected: the parallels are
# curves in EPSG:2180.
FRAME_SEGMENT_DEG = 0.005

_TO_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)


@dataclass(frozen=True)
class NmtCoverage:
    """The part of the area that the sheets leave without data.

    Attributes
    ----------
    uncovered_km2 : float
        The area, and the holes the sheet frames enclose, outside every frame.
    missing_sheets : tuple[str, ...]
        The sheets of the grid that overlap the uncovered part, sorted.
    """

    uncovered_km2: float
    missing_sheets: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Say whether the sheets leave nothing uncovered."""
        return self.uncovered_km2 == 0.0


def sheet_frame(sheet: str) -> Polygon:
    """Return the frame of a PL-1992 sheet in EPSG:2180."""
    from kartograf import SheetParser

    frame = SheetParser(sheet).get_bbox(crs="EPSG:4326")
    projected: Polygon = area_2180(
        box(frame.min_x, frame.min_y, frame.max_x, frame.max_y)
    )
    return projected


def area_2180(area_wgs84: BaseGeometry) -> BaseGeometry:
    """Project an area in EPSG:4326 (``core.boundary.load_boundary``, a box) to 2180."""
    return shapely.transform(
        shapely.segmentize(area_wgs84, FRAME_SEGMENT_DEG),
        _TO_2180.transform,
        interleaved=False,
    )


def nmt_coverage(
    area_2180: BaseGeometry,
    sheets: Collection[str],
    *,
    scale: str,
    tolerance_m: float,
) -> NmtCoverage:
    """Measure what of the area the frames of the sheets leave uncovered.

    Parameters
    ----------
    area_2180 : BaseGeometry
        The area of the run in EPSG:2180.
    sheets : Collection[str]
        The codes of the sheets the mosaic is made of.
    scale : str
        The scale of the grid the missing sheets are named in (``1:10000``).
    tolerance_m : float
        Uncovered parts narrower than this are not counted.

    Returns
    -------
    NmtCoverage
        The uncovered area and the sheets of the grid that would cover it.
    """
    from kartograf import BBox, find_sheets_for_bbox

    # The closing joins frames that rounding leaves a hair apart, the opening drops
    # the slivers of the area narrower than the tolerance.
    half = tolerance_m / 2
    covered = (
        unary_union([sheet_frame(sheet) for sheet in sheets])
        .buffer(half, join_style="mitre")
        .buffer(-half, join_style="mitre")
    )
    enclosed = [Polygon(ring) for part in _polygons(covered) for ring in part.interiors]
    gap = unary_union([area_2180, *enclosed]).difference(covered)
    gap = (
        gap.buffer(-half, join_style="mitre")
        .buffer(half, join_style="mitre")
        .intersection(gap)
    )
    parts = list(_polygons(gap))
    if not parts:
        return NmtCoverage(uncovered_km2=0.0, missing_sheets=())

    present = set(sheets)
    missing: set[str] = set()
    for part in parts:
        min_x, min_y, max_x, max_y = part.bounds
        candidates = find_sheets_for_bbox(
            BBox(min_x, min_y, max_x, max_y, crs="EPSG:2180"),
            scale,
            sheet_system=SHEET_SYSTEM,
        )
        missing.update(
            sheet
            for sheet in candidates
            if sheet not in present
            and sheet_frame(sheet).intersection(part).area > tolerance_m**2
        )
    return NmtCoverage(
        uncovered_km2=sum(part.area for part in parts) / 1e6,
        missing_sheets=tuple(sorted(missing)),
    )


def check_nmt_coverage(
    area_2180: BaseGeometry,
    sheets: Collection[str],
    *,
    scale: str,
    resolution: str,
    allow_uncovered: bool,
) -> NmtCoverage:
    """Refuse a mosaic that leaves part of the area, or a hole inside it, uncovered.

    Parameters
    ----------
    area_2180, sheets, scale
        As for :func:`nmt_coverage`.
    resolution : str
        The NMT resolution of the run (``5m``, ``1m``): the tolerance is
        ``TOLERANCE_CELLS`` of its cells.
    allow_uncovered : bool
        Log a warning instead of refusing (``--allow-uncovered``).

    Returns
    -------
    NmtCoverage
        What the sheets leave uncovered (complete, or allowed).

    Raises
    ------
    NoDataError
        ``nmt_coverage_gap`` (``details["sheets"]``: the missing sheets) when part of
        the area is uncovered and ``allow_uncovered`` is false.
    """
    cell_m = float(resolution.removesuffix("m"))
    coverage = nmt_coverage(
        area_2180, sheets, scale=scale, tolerance_m=TOLERANCE_CELLS * cell_m
    )
    if coverage.complete:
        return coverage
    error = NoDataError(
        "nmt_coverage_gap",
        reason="nmt_coverage_gap",
        area_km2=round(coverage.uncovered_km2, 3),
        count=len(coverage.missing_sheets),
        sheets=list(coverage.missing_sheets),
    )
    if not allow_uncovered:
        raise error
    logger.warning("%s Allowed (--allow-uncovered).", error.text("en"))
    return coverage


def _polygons(geometry: BaseGeometry) -> Iterator[Polygon]:
    """Yield the non-empty polygons of a geometry."""
    if isinstance(geometry, Polygon):
        if not geometry.is_empty:
            yield geometry
        return
    for part in getattr(geometry, "geoms", ()):
        yield from _polygons(part)
