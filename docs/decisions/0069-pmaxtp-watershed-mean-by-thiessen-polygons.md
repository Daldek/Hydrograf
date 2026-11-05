# ADR-069: The PMAXTP design depth is the watershed mean by Thiessen polygons

**Date:** 2026-11-05
**Status:** accepted (the author, 2026-11-05; plan
`docs/plans/2026-11-05-pmaxtp-watershed-mean.md`)

## Context

User report #40 (feedback table, 2026-11): the explanation of the rainfall duration said
the PMAXTP depth is „interpolowany w klikniętym punkcie z 4 najbliższych punktów siatki
danych metodą odwrotnych odległości (IDW)” and asked why from the clicked point and not
from the whole watershed with a buffer. The code did what the text said:
`get_precipitation(point_2180, …)` in `api/endpoints/hydrograph.py` interpolated the
four nearest grid points of `precipitation_data` (the PMAXTP quantiles sampled every
2 km) at the point of the request, the click near the outlet, by inverse distance
weighting with the power 2.

The Polish methodology for design floods (Banasik, Wałęga, Węglarczyk, Więzik 2017,
„Aktualizacja metodyki obliczania przepływów i opadów maksymalnych…”, KZGW, chapter II,
p. 15) requires the mean rainfall of the watershed for empirical formulas and for
rainfall–runoff models of hypothetical hydrographs, „określenie wysokości opadu średniego
w zlewni”, and names the method of equal-rainfall polygons (Thiessen, eq. 2.1:
P = (1/A) Σ Pᵢ·Aᵢ) and isohyets as the most common. The point value is representative only
of very small watersheds, about 10 km² (p. 105, after DVWK 1984). A clicked point is the
outlet, the lowest place of a watershed; in the Sudetes PMAXTP grows with elevation, so the
point value understates the design storm of larger watersheds. Measured on the production
data (12 h, p = 1 %, the Kaczawa to its 238.7 km² node at 51.128° N, 15.909° E): 99.62 mm at
the point, 106.02 mm as the watershed mean of 86 grid points (+6.4 %, the grid points range
from 99.5 to 122.2 mm); a 25.0 km² watershed (1 h, p = 10 %): 29.36 → 29.07 mm; a 0.09 km²
one: 28.35 mm both ways.

The fast path of `POST /api/generate-hydrograph`, which the front end always uses, gets
the delineation's `morphometry` and not the boundary, so the hydrograph request does not
know the watershed. The boundary of a 240 km² watershed is about 1.2 MB of GeoJSON
(28 000 vertices), and the hydrograph is recomputed on every change of the form.

## Options considered

- **A. Keep the depth at the point and only correct the text.** No change of results, but
  the method stays contrary to the methodology for every watershed above ~10 km².
- **B. Arithmetic mean of the grid points inside the watershed (plus a buffer).** Simple,
  but a watershed smaller than a grid cell has no point inside it, the buffer is arbitrary
  and the result jumps when the boundary passes a point.
- **C. Mean of the IDW surface over a raster of the watershed (Hydrolog's
  `areal_precipitation_idw`).** Smooth, but Hydrolog returns no weights (nothing to
  export, report #39), and its loop over cells and points is slow for 250 km².
- **D. Thiessen polygons of the grid points clipped to the watershed, the mean by
  Hydrolog's `thiessen_polygons`.** The method of the methodology; continuous in the
  boundary; for a watershed inside one polygon it is that grid point's value; gives each
  point a weight (its share of the area) to show and export. The polygons need the
  boundary, so the weights are computed with the delineation and travel with the
  morphometry.
- **E. As D with an areal reduction factor of the point depths.** The methodology reduces
  point rainfall for watersheds above ~10 km² (up to 10 % for 10–100 km², DVWK 1984; the
  curves of Chow et al. 1988, fig. 6.6 of KZGW 2017). It needs a choice of curve the
  methodology does not make, and it changes every result again.

## Decision

Option D, with option E as the user's own input: the author approved the Thiessen
watershed mean on 2026-11-05 and decided that the areal reduction is optional, entered by
the user, and absent by default (no curve or formula of Hydrograf).

`core/precipitation.py`: `thiessen_cells(boundary, db)` takes the distinct grid
points within 5 km of the watershed's bounding box (every place lies at most half a cell
diagonal from its nearest point, so a margin of the grid spacing is enough), builds their
Voronoi polygons (`shapely.voronoi_polygons`, ordered by point) and keeps the area of
each polygon inside the watershed; `areal_depth(cells, duration, probability, db)` reads
the scenario's depth at those points and averages it by Hydrolog's `thiessen_polygons`.
`POST /api/delineate-watershed` returns the cells as `watershed.pmaxtp_grid` (easting,
northing in EPSG:2180, area in km²; about 90 cells for 250 km²); the front end sends them
back as `pmaxtp_grid` of the hydrograph request with the `morphometry`. The full path of
the hydrograph request (without `morphometry`) computes them from its own boundary. A
request with its own morphometry and without `pmaxtp_grid` keeps the inverse distance
weighting at the point (`point_depth`, now Hydrolog's `inverse_distance_weighting` of the
four nearest points, power 2), the only value without a boundary. A cell of `pmaxtp_grid`
that is not a grid point (none within 1 m) is a 400 `validation_error`
(`pmaxtp_grid_point_unknown`). The response tells which method made the depth
(`precipitation.interpolation`: `thiessen` or `idw`) and lists the grid points with their
depths, weights and areas or distances (`precipitation.pmaxtp_points`), which the front
end shows in the Hietogram section and exports (report #39); the hand-off's rainfall
provenance carries the same `interpolation`.

The areal reduction (E) is the user's: the hydrograph request takes an optional
`areal_reduction_factor` (0 < ARF ≤ 1; null by default, no reduction; out of range a 400
`validation_error` with the Polish message of the field), which multiplies the PMAXTP
depth (the watershed mean or IDW at the point; a custom series ignores it). The response
`precipitation` gives `pmaxtp_depth_mm` (unreduced), `areal_reduction_factor` (or null)
and `total_mm` (the depth used); the hand-off's rainfall provenance carries
`areal_reduction_factor` when one was given, and its `total_mm` is the reduced depth. The
front end has the empty field „Współczynnik redukcji obszarowej (własny)” in the
Hietogram section; its (i) cites the methodology (KZGW 2017, p. 105) and says the value
is the user's own; the exports carry the factor.

## Consequences

- Design depths of watersheds above a few km² change, mostly upwards in the hills
  (+6.4 % for 240 km² of the Kaczawa above); for small watersheds they stay within the
  differences between neighbouring grid points.
- The delineation response grows by about 9 kB for 250 km² (86 cells); the hydrograph
  request by the same, its response by the points (about 20 kB).
- `get_precipitation`, `get_precipitation_wgs84` and `get_all_scenarios` are removed (the
  last two had no callers).
- A grid of another spacing or origin (a new preprocessing) invalidates the `pmaxtp_grid`
  of delineations made before it; such a request gets the 400 with the hint to delineate
  again.
