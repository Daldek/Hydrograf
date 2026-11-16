# PMAXTP design depth as the watershed mean, with an optional areal reduction: plan

**Approved:** 2026-11-05, the author (scope: the Thiessen watershed mean of ADR-069 for
the PMAXTP design depth; an optional areal reduction factor entered by the user, absent by
default, no formula of Hydrograf; branch `feature/v050-gui-reports` for the v0.5.0
candidate); design details by delegated authority, to be reviewed at the merge.

**Goal:** the design storm of a watershed uses the mean rainfall of the watershed, as the
Polish methodology for design floods requires (KZGW 2017, ch. II, p. 15), instead of the
PMAXTP depth at the clicked point (tester report #40); the person may reduce the point
depths to an areal depth with a factor of their own choice.

**Interface changes (public API):**

1. `POST /api/delineate-watershed`: `watershed.pmaxtp_grid`, the PMAXTP grid points with
   the areas of their Thiessen polygons inside the watershed.
2. `POST /api/generate-hydrograph` request: optional `pmaxtp_grid` (with `morphometry`)
   and optional `areal_reduction_factor` (0 < ARF ≤ 1, null = no reduction).
3. `POST /api/generate-hydrograph` response `precipitation`: `interpolation`
   (`thiessen` | `idw`), `pmaxtp_points`, `pmaxtp_depth_mm` (unreduced),
   `areal_reduction_factor`; `total_mm` stays the depth used. The hand-off's rainfall
   provenance gains `interpolation` and, when given, `areal_reduction_factor`.

**Steps:** `core/precipitation.py` (Thiessen cells, areal depth, IDW at a point through
Hydrolog); the endpoints; the front end (form field, balance row, exports of report #39);
the (i) texts with sources; ADR-069; CHANGELOG, guide and presentation; unit tests for the
mean, the grid validation and the factor (none, applied, out of range).

**Not in scope:** a default areal reduction curve (the author's decision: none).
