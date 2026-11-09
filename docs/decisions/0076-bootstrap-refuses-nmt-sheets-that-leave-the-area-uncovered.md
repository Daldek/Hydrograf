# ADR-076: The bootstrap refuses NMT sheets that leave the area, or a hole of their mosaic, uncovered

**Date:** 2026-11-09
**Status:** accepted (by delegation of the author, 2026-11-09)

## Context

Step 3 of the bootstrap mosaics the NMT sheets it is given. A sheet that is missing is nodata in the
mosaic: inside the area it cuts the area off, and where the other sheets enclose it the depression
fill takes its rim for outlets, so the land around it drains into it (ADR-073). The h07 set `2026`
pinned the 708 sheets that `find_sheets_for_geometry` gives for the project's area, and the bootstrap
accepted it: `N-33-120-D-a-3-3` lies in a notch of the area outline (10 m outside it), so it is not a
sheet of the area, yet its eight neighbours are, and it became a 4.885 km² nodata hole that drained
40.18 km² around it. The check of ADR-067 (`set_sheets_missing`) compares sheet codes with the
sheets of the area; it cannot see a hole that the mosaic encloses outside the area. A download run
has the same blind spot for a sheet that GUGiK has no data for (`no_coverage`), which step 2 only
logs.

## Alternatives

- **Compare the sheet codes with the sheets of the area only** (ADR-067 as it is): misses h07.
  **Rejected.**
- **Measure the nodata of the mosaic** (the valid cells of every sheet): exact, but it needs the
  rasters, so a set could be checked only in step 3 after the mosaic is built, and a sheet with
  nodata of its own (the border, a lake GUGiK left out) is no missing sheet. **Rejected.**
- **Measure on the sheet grid**: the frames of the sheets against the area and against the holes the
  frames enclose, before anything is read: **chosen**.
- **Interpolate the hole** (ADR-073) instead of refusing: the elevations of a missing sheet are not
  measured, and a gap on the frame of the area is not interpolated at all; it stays an opt-in for the
  holes that remain.

## Decision

`utils.nmt_coverage`: the frames of the sheets (their meridians and parallels,
`SheetParser.get_bbox` in EPSG:4326, segmentized and projected to EPSG:2180) are unioned and closed
by half the tolerance (rounding leaves hairlines between projected frames). What lies outside the
union, of the area or of a hole the union encloses, is uncovered; it is opened by half the tolerance,
so parts narrower than the tolerance (three cells of the resolution: 15 m at 5 m) do not count. The
missing sheets are the sheets of Kartograf's grid at the scale of the run (`find_sheets_for_bbox`)
that overlap the uncovered part by more than the tolerance squared.

The area is the outline of the project (a set), of `--boundary-file` or of `--bbox`, or the frames of
`--sheets`. A set is checked before step 1 with the other checks of ADR-067, on its NMT sheets; a
download run at the start of step 3, on the sheets step 2 got. An uncovered part is refused with
`no_data` (exit 14), reason `nmt_coverage_gap`, the km² (`details.area_km2`) and the sheets
(`details.sheets`) in the text; `--allow-uncovered` logs the same text as a warning and goes on.

## Consequences

- The h07 set `2026` is refused before step 1: 9.751 km², `N-33-118-B-a-4-2` and `N-33-120-D-a-3-3`.
  The set `2026-2` of the published Hydroni data adds `N-33-120-D-a-3-3` and is still refused for
  `N-33-118-B-a-4-2` (4.866 km², 232 m outside the area, seven of its eight neighbours pinned: in the
  raster its nodata reaches the frame through one corner, so ADR-073 does not fill it); a new set with
  that sheet, or `--allow-uncovered`, runs it.
- A download run near the border of Poland, whose sheets GUGiK has no data for, is refused unless
  `--allow-uncovered`.
- The frames are the sheets' extents, not their valid data: nodata inside a sheet is not seen here.
- With `dem.fill_enclosed_nodata` (ADR-073) the holes allowed by `--allow-uncovered` that do not
  reach the frame of the raster are interpolated; a gap on the frame of the area stays nodata.
