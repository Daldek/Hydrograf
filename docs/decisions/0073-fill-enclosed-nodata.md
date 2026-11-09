# ADR-073: Nodata that the DEM encloses is interpolated before the fill, on request

**Date:** 2026-11-07
**Status:** accepted (the author, 2026-11-09: opt-in `dem.fill_enclosed_nodata`, the default `false`
unchanged)

## Context

The depression fill (`fill_depressions_d8`: pyflwdir's `fill_depressions`, `outlets="edge"`, no
maximum depth) fills every depression and takes every cell next to nodata, or on the frame of the
raster, for an outlet. `fill_internal_nodata_holes` repairs small holes before it (at most three
passes, a cell with five valid neighbours or more). A larger nodata area inside the data stays, and the
cells around it are outlets: the land that drains to them is endorheic, and its streams and
sub-catchments have no downstream link, as if the area ended there.

The published Hydroni run (h07, set 2026, run 1 of 2026-11-07, `stream_burning: main`,
`--waterbody-mode none`) has one such area, and nothing else ends the flow inside the data (measured on
its VRT mosaics and in its database, read only):

- one nodata area enclosed by data: 195,403 cells (4.885 km²; 4 more nodata components reach the
  frame), the NMT sheet `N-33-120-D-a-3-3`, which the set does not pin; Kartograf's store holds it since
  2026-11-07 13:14 UTC (version `2021-06-04_74964`);
- 171 outlets on its rim drain 40.18 km², 31.41 km² of them inside the 223 MPHP catchments: 96.6 % of
  catchment 1883613 (26.12 of 27.03 km²), 11.3 % of 186174, 3.7 % of 1883617, less in two more; 27, 8,
  3 and 2 stream segments of the four thresholds (1 ha to 10 km²) end in it, upstream 39.96 to
  36.06 km²;
- no pit without nodata beside it, no drain point (`--waterbody-mode none`), no sink for
  `fix_sinks_of_fill`; the 6,933 other outlets lie on the outer edge of the data.

## Alternatives

- **Pin the missing sheet in a new set** (Archiwista): the right data, and outside Hydrograf. It does
  not answer for another mosaic with a gap; a decision of the author for h07.
- **Outlets on the outer edge only** (pyflwdir's `idxs_pit`): the enclosed nodata stays and is no
  outlet, so it is an obstacle that the fill must pass around: a gap across a valley dams it, and the
  land upstream is raised to the lowest pass of its rim. **Rejected.**
- **The gap as a flat at the lowest elevation of its rim**: the fill raises it to its outlet; 4.9 km²
  of slope 0 with directions of pyflwdir's queue order, and slope, TWI and the parameters of the
  catchments wrong there. **Rejected.**
- **Interpolated from the data around it** (GDAL's inverse distance weighting,
  `rasterio.fill.fillnodata`), then the usual fill: **chosen**. Against the sheet itself the
  interpolation of the h07 gap differs by +0.88 m on average (RMSE 4.19 m, 95th percentile 9.5 m,
  maximum 20.0 m): the gap drains through its own ground instead of ending the flow, without a claim to
  its relief.

## Decision

`dem.fill_enclosed_nodata: true` (bootstrap configuration; `process_dem(fill_enclosed_nodata=True)`):
before anything else, `core.hydrology.interpolate_enclosed_nodata` gives every nodata area that does not
reach the frame of the raster (8-connected, the neighbours of pyflwdir) the values interpolated from the
cells around it. The nodata that reaches the frame stays, so the outlets of the fill lie on the outer
edge of the data only. The filled cells are DEM cells of the run from then on: in a run by units they
get an owner, are routed and published in every mosaic, `01_dem` included; the whole-raster run saves
them in `01_dem` too, and both runs give the same rows and rasters. The setting is one of a run by units
only when on, so the runs of the default keep their fingerprint and resume as before;
`bootstrap_set.json` records it. The default changes nothing.

## Consequences

- No endorheic area is left in a run with the setting; the elevations in a filled gap are interpolated,
  not measured (RMSE about 4 m on the h07 gap), and so are the slope, the TWI and the depressions of
  step 7 there.
- A run of the same set with and without the setting differs only around the gaps; the alternative
  Hydroni data (`hydroni-alt`) is such a run.
