"""Whether the NMT sheets cover the area (ADR-076), on Kartograf's real sheet grid.

The block is the 4 × 4 sheets at 1:10000 of the 1:50000 sheet ``N-34-131-C-c``; the
area lies 100 m inside its frame, so every sheet of the block holds part of it.
"""

import logging

import pytest
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.errors import NoDataError
from utils.nmt_coverage import check_nmt_coverage, nmt_coverage, sheet_frame

SCALE = "1:10000"
TOLERANCE_M = 15.0
BLOCK = [
    f"N-34-131-C-c-{quarter}-{sheet}"
    for quarter in range(1, 5)
    for sheet in range(1, 5)
]
CORNER = "N-34-131-C-c-1-1"


def _union(sheets: list[str]) -> BaseGeometry:
    """The frames as one shape: rounding leaves hairlines between projected frames."""
    frames = unary_union([sheet_frame(sheet) for sheet in sheets])
    return frames.buffer(1, join_style="mitre").buffer(-1, join_style="mitre")


@pytest.fixture(scope="module")
def area() -> BaseGeometry:
    return _union(BLOCK).buffer(-100, join_style="mitre")


@pytest.fixture(scope="module")
def inner() -> str:
    """A sheet with neighbours of the block on every side."""
    block = _union(BLOCK)
    return next(s for s in BLOCK if sheet_frame(s).buffer(100).within(block))


def _without(sheet: str) -> list[str]:
    return [s for s in BLOCK if s != sheet]


def test_the_whole_block_covers_the_area(area):
    coverage = nmt_coverage(area, BLOCK, scale=SCALE, tolerance_m=TOLERANCE_M)

    assert coverage.complete
    assert coverage.missing_sheets == ()


def test_a_missing_inner_sheet_is_named_with_its_area(area, inner):
    coverage = nmt_coverage(area, _without(inner), scale=SCALE, tolerance_m=TOLERANCE_M)

    assert coverage.missing_sheets == (inner,)
    assert coverage.uncovered_km2 == pytest.approx(
        sheet_frame(inner).area / 1e6, rel=1e-3
    )


def test_a_hole_the_sheets_enclose_counts_outside_the_area(area, inner):
    # h07: the missing sheet lay in a notch of the area, enclosed by the mosaic
    notched = area.difference(sheet_frame(inner).buffer(10, join_style="mitre"))

    coverage = nmt_coverage(
        notched, _without(inner), scale=SCALE, tolerance_m=TOLERANCE_M
    )

    assert coverage.missing_sheets == (inner,)
    assert coverage.uncovered_km2 == pytest.approx(
        sheet_frame(inner).area / 1e6, rel=1e-3
    )


def test_a_missing_sheet_on_the_frame_counts_its_part_of_the_area(area):
    coverage = nmt_coverage(
        area, _without(CORNER), scale=SCALE, tolerance_m=TOLERANCE_M
    )

    assert coverage.missing_sheets == (CORNER,)
    assert coverage.uncovered_km2 == pytest.approx(
        sheet_frame(CORNER).intersection(area).area / 1e6, rel=1e-3
    )


@pytest.mark.parametrize(("beyond_m", "complete"), [(5, True), (50, False)])
def test_an_area_beyond_the_frame_counts_from_the_tolerance(beyond_m, complete):
    area = _union(BLOCK).buffer(beyond_m, join_style="mitre")

    coverage = nmt_coverage(area, BLOCK, scale=SCALE, tolerance_m=TOLERANCE_M)

    assert coverage.complete is complete


def test_the_check_refuses_an_uncovered_area_with_the_sheets(area):
    with pytest.raises(NoDataError) as raised:
        check_nmt_coverage(
            area,
            _without(CORNER),
            scale=SCALE,
            resolution="5m",
            allow_uncovered=False,
        )

    error = raised.value
    assert error.code == "no_data"
    assert error.details["sheets"] == [CORNER]
    assert error.details["area_km2"] == pytest.approx(
        sheet_frame(CORNER).intersection(area).area / 1e6, abs=1e-3
    )
    assert CORNER in error.text("pl")


def test_allow_uncovered_warns_and_goes_on(area, caplog):
    with caplog.at_level(logging.WARNING, logger="utils.nmt_coverage"):
        coverage = check_nmt_coverage(
            area,
            _without(CORNER),
            scale=SCALE,
            resolution="5m",
            allow_uncovered=True,
        )

    assert coverage.missing_sheets == (CORNER,)
    assert CORNER in caplog.text
