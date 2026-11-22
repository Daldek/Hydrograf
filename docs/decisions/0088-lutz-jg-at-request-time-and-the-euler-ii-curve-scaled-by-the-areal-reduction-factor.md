# ADR-088: Lutz's Jg measured at request time on the traced flow path; Euler II's PMAXTP curve scaled by the areal reduction factor

**Date:** 2026-11-21
**Status:** proposed (implemented in Hydrograf 0.6.0 by commit `86fb9d6` of the branch
`feat/hydrolog-0.9.0`, step 2 of Nogat's plan `2026-11-19-hydrolog-0.9.0-consumers`; the
author has not accepted it yet)

## Context

Hydrolog 0.9.0 changes two inputs that Hydrograf gives it.

1. **Lutz's Jg** (Hydrolog ADR-0053). Lutz's estimation of Nash's n and K reads
   `flow_path_equal_area_slope_m_per_m`, the equal-area slope of the longitudinal profile of
   the longest flow path: S = 2A/L², A the area of the profile above the elevation of its
   outlet (by the trapezoid rule), L its length (KZGW 2017, annex 2, p. 97; TM61 of New
   Zealand). Hydrolog refuses a watershed without the field (`missing_field`) even when it has
   the end-point slope `flow_path_slope_m_per_m`, which is another quantity: on a concave
   profile it overestimates Jg and so the peak. Hydrolog's ADR-0053 (point 4) asks for the
   profile of the same D8 path as `flow_path_length_km`: from the path's end cell, whose flow
   distance is the baseline of `hydraulic_length_km`, upstream; x the flow distance minus the
   end cell's, z the filled DEM.

   Hydrograf measured the path and its ends (ADR-070: per sub-catchment, in the preprocessing,
   the elevation of the head and the overland segment), not the area under its profile. The
   longest flow path of a delineated watershed is traced at request time already:
   `core/divide_flow_path.py` reads one window of the saved label, flow distance and flow
   direction rasters around the watershed and follows D8 from its farthest cell to the outlet,
   for the line on the map and for `flow_path_length_km` (ADR-048; since 2026-11-05 instead of
   the stored path of the head sub-catchment, which was 2.21 km of the 16.05 km of the
   Kamiennik). The elements of a network and the parameters export measure each element from
   its cells on the saved rasters, the filled DEM among them (`core/cell_parameters.py`,
   ADR-080).

2. **Euler II from the depth–duration curve** (Hydrolog ADR-0042). The storm is built from the
   depths of every duration at one probability; its total is h(D), and Hydrolog refuses a total
   that differs from h(D) by more than 0.005 mm. Its ADR rejects scaling the curve inside the
   library: "the storm of one probability holds h(D); another total is another probability, so
   the curve is to be scaled by whoever chose that total". Hydrograf's design depth is the mean
   of the PMAXTP grid over the watershed by Thiessen polygons (IDW at the point without a
   boundary), times the user's own areal reduction factor, none by default (ADR-069).

## Options considered

Where Jg is measured:

- **A. At request time, on the traced path** (chosen). The window that the flow paths read
  also reads the filled DEM `dem_mosaic_02_filled`, which the pipeline saves, and Hydrolog's
  `equal_area_slope` takes the elevations of the cells of the path already traced. No
  migration and no backfill; the profile is exactly that of `flow_path_length_km`; the
  elements of a network and the export get it from the cells they read already.
- **B. A column of the preprocessing and a backfill.** Each sub-catchment would store the
  trapezoid integral of z along its stretch of the path and its length, and the catchment graph
  would add them, S = 2(Σ∫z dx − z_outlet·L)/L² (Hydrolog ADR-0053, point 4). The path of a
  watershed is not a chain of the sub-catchments' own longest paths: it enters a sub-catchment
  where the one above drains into it, not at its head, so the stored pieces would be pieces of
  other paths unless they were stored per entry cell. It needs a migration, a change of
  `process_dem`, a backfill of the existing data from the same saved rasters (as ADR-070's), and
  the network and the export would still read the rasters.
- **C. The end-point slope.** Refused by Hydrolog (above).

The Euler II curve with a reduction factor:

- **A. Scale the whole curve by the factor** (chosen). Each duration's depth is weighed as the
  design depth (Thiessen or IDW) and multiplied by the same factor, so h(D) is the reduced
  design depth and each window around the peak keeps the shape of the curve.
- **B. The unreduced curve.** Hydrolog refuses the reduced total (`total_mismatch`); dropping
  the factor for Euler II alone would make it the one shape that ignores the user's value.
- **C. A factor per duration** (the reduction grows as the duration shortens, DVWK's curves).
  Hydrograf computes no factor (ADR-069); the user gives one value for the storm.
- **D. Refuse the factor with Euler II.** It takes a valid use away.

## Decision

1. **Jg is measured at request time.** `compute_flow_paths` (`core/divide_flow_path.py`) reads
   the window of `dem_mosaic_02_filled` (`Settings.resolve_pipeline_raster("02_filled")`: the
   VRT of the active unit run, else the GeoTIFF of a run of the whole raster in DEM_DIR) beside
   the label, flow distance and flow direction rasters, on their grid (a DEM on another grid
   gives no value, with a warning in the log). `profile_equal_area_slope` takes the cells of the
   traced longest flow path from its end cell, which lies outside the watershed (without an
   elevation or a flow distance there, from the cell above it), up to its head: x the flow
   distance minus that of the first cell, z the filled DEM. Hydrolog's `equal_area_slope` gives
   S, rounded to 6 decimals. Fewer than two cells, a cell without a value or a profile without
   positive area give no value (`null`), never 0, which Hydrolog's watershed refuses. The
   elements of a network and the export use the same function on their cells
   (`core/cell_parameters.py::flow_path_parameters`). The morphometry of a delineation, of each
   element and of the export, and the watershed of every hand-off carry
   `flow_path_equal_area_slope_m_per_m`; the `formula_versions` of a delineated watershed name
   `equal_area_slope` when it gave a value.
2. **Lutz reads it.** L is `flow_path_length_km` and Jg `flow_path_equal_area_slope_m_per_m`
   (`api/endpoints/hydrograph.py::_estimate_nash_params`); a morphometry without either, or
   without Lc, gets 422 `lutz_parameters_missing`. Kirpich and Kerby–Kirpich keep
   `flow_path_slope_m_per_m`, which their sources define.
3. **The Euler II curve is weighed like the design depth and scaled by the factor.**
   `_depth_duration_mm` (`api/endpoints/hydrograph.py`) gives the depths of the 16 PMAXTP
   durations at the probability, each by `_design_depth` and times the factor (1 without one);
   the storm's total is the reduced design depth, h(D) of that curve. The hand-off's rainfall
   carries the reduced curve as `depth_duration_mm`, its origin the `areal_reduction_factor`.

## Consequences

- Each delineation reads one more window, the filled DEM (float32) over the watershed's bounding
  box: on the production data (5 m, LZW, tiles of 256) about 16 MB in 0.27 s for 2000 × 2000
  cells (100 km²) and 41 MB in 0.34 s for 3200 × 3200 cells (256 km²).
- **Without the saved filled DEM, Jg is null and Lutz's estimation is refused** (422
  `lutz_parameters_missing`) until the pipeline runs again with its rasters saved (the bootstrap
  and a run by units save them; a run of the whole raster needs `process_dem
  --save-intermediates`) or the user gives Jg: the advanced mode's field „Spadek wyrównany
  najdłuższej drogi spływu”, or `morphometry` of the request. The other methods do not read it.
- The instances checked on 2026-11-21 (read only) have it: the DEM directory of the production
  instance holds `dem_mosaic_02_filled.tif` of its run of 2026-11-17 on the grid of its label
  rasters (8142 × 7196 cells of 5 m), and Hydroni's active unit run `dem_mosaic_02_filled.vrt`
  (its 27 unit sources present) on the grid of its labels (16302 × 14302 cells). After the
  deployment of this change both compute Lutz's estimation.
- Lutz's results change wherever the profile is not straight; a concave profile has a lower Jg,
  so a later and lower peak (Hydrolog ADR-0053: the Kamiennik's K 92.1 → 104.3 min, peak
  35.0 → 32.2 m³/s).
- Every Euler II storm changes (Hydrolog ADR-0042: the peak block 1.3 to 2.9 times the old one);
  with a factor the curve and the storm are reduced alike. An Euler II request reads the depths
  of 16 durations instead of one.
- The API reads one more raster that the preprocessing saved, beside those of ADR-048's lines;
  it computes nothing on the DEM but the profile of one path (CLAUDE.md, ADR-001).
