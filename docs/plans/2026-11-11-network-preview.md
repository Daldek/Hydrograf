# Plan: the network previewed on the catchment graph, its characteristics on confirmation

Approved: 2026-11-11 (the author's design of two stages in „Sieć zlewni”, recorded in
ADR-081; the technical details by delegation, decided here with their reasons).

Requirements: ADR-081; the network of ADR-080 and its plan
[`2026-11-10-network-delineation.md`](2026-11-10-network-delineation.md) (D2 to D5, D10, D15).

## Goal

While the person places A and the points, the map shows the network those points make, in a
fraction of a second after each change: where each point snapped (and whether it moved to a
mouth), the elements with their ids, areas and outlines, the reaches with their lengths, the
junctions, and an error of the composition at once. „Oblicz charakterystyki” (until now
„Wyznacz sieć”) runs the full delineation; its result, with the parameters and the hand-off,
holds while the points stay as they were, and any change returns the mode to the preview.

## Decisions

### P1. One route of its own

`POST /api/delineate-network/preview` takes the request of `POST /api/delineate-network`
(`DelineateNetworkRequest`) and answers `DelineateNetworkPreviewResponse`
(`models/schemas.py`): no parameters, no hand-off, no `area_check` and no boundary of A.
`api/endpoints/network.py` runs it without the lock of D13; the router keeps the problems 404
and 503, the full run's route adds its 422. Why: the request is the same, so the browser sends
the body it would confirm; the full run's response model would need every parameter.

### P2. The same composition (ADR-081, decision 2)

`core/network_preview.py::preview_network` opens the rasters with `open_network_rasters`, snaps
every point with `snap_point` and builds the tree with `build_network_tree`. Why: the ids and the
places must be those of the full run; only the rasters around the clicks are read (the windows of
D2), no window of A's catchment.

### P3. Areas exact to the cell

An element holds the cells of its units (`round(area_km2 / cell area)`, as D11 counts them) and,
in a unit that a point splits (`NetworkTree.splits`), the accumulation at its point less the cells
of the units above that unit (`Place.accumulation_cells`, read by the snapping; the units drain
into the head of the unit below them, D5), the next point the difference of the two
accumulations, the unit's outlet the rest; the part of A's unit below A stays outside. Why: an
element made of a part of a unit alone (two points in one unit) would otherwise have no area, and
A's area would hold the part below A; the full run's areas follow, so `over_scs_cn_limit` is the
full run's notice already.

### P4. The outlines

Every unit of A's catchment is drawn by the largest sub-catchment of a coarser threshold that one
element holds whole, else by itself (`outline_cover`). `CatchmentGraph.coarser_at_outlets` finds,
once per loaded graph, each coarser sub-catchment at the unit of 1 ha whose outlet cell it shares
(equal `outlet_flow_dist_m` and `upstream_area_km2`; a pair two units share is not matched), and
the cover takes it when the units that drain to it within A's catchment add up to its cells and
belong to one element. A split unit goes whole to the element with most of its cells. PostGIS
unites the chosen polygons by element (`ST_Simplify` at 10 m, `ST_MakeValid`,
`ST_ReducePrecision` and `ST_Union` on a grid of 10 m); holes and parts narrower than 30 m (the
gaps between neighbouring units simplified apart) are dropped. Why: the union of the units of
1 ha takes tens of seconds for a large network (23 s for 10,000 on production); the cover of the
whole area holds 91 polygons.

### P5. Reaches and junctions

A reach's length is the difference of the flow distances of its ends (D10: the graph's
`outlet_flow_dist_m` at a junction, the raster at a control point, as snapped); its line joins the
stream lines of its units (`stream_network`, 1 ha), cut at the projections of the cells of its
control points and simplified at 1 m. A junction at a confluence lies at the last vertex of the
stream line above it (Chaikin keeps the ends: the junction cell), at a control point at its cell.
Why: no flow direction of a window; the lengths and places equal the full run's.

### P6. The front end

`js/network.js`: a preview after every change of the points (added, removed, dragged; not a name)
or of the threshold, debounced (300 ms), older answers dropped; the markers move to their snapped
places (as after the full run, without a new preview: the answer's key holds the snapped places);
the elements filled by kind, a dashed outline where `outline_approximate`, the reaches, the
junctions, the ids; the tree from A upward with areas and lengths; a point `inside_unit` marked;
an error marks its points and disables „Oblicz charakterystyki”. The full result shows while it
answers the points on the map; a change makes it stale: the preview of the new points takes the
map and the panel, a notice asks for „Oblicz charakterystyki” again and the hand-off is disabled.

## Tests

- `tests/unit/test_network_preview.py` (the synthetic run of the network tests with
  sub-catchments of 1 ha and 20 ha, the fake database): for three networks (at the mouths; a gauge
  and two points in one unit; A inside its unit and a point up a tributary) the preview names the
  points, elements, reaches and junctions as the full run, puts its points and junctions where the
  full run does, and gives its areas (the hand-off's, 6 decimals) and reach lengths; its outlines
  overlap the full run's elements (intersection over union above 0.95) and use the 20 ha
  sub-catchments; its reach lines lie within a cell of the full run's; `inside_unit` and
  `outline_approximate`; the errors of the composition equal the full run's in both languages; the
  notice above 250 km²; any other failure is 500 `network_preview_failed`.
- `tests/unit/test_catchment_graph.py`: `coarser_at_outlets` matches the coarser sub-catchment at
  the unit that ends at its outlet cell, and no unit where two share the values.
- `tests/contract/test_openapi.py`: the preview documents 400, 404, 500 and 503, not 422.
- `tests/integration/test_network_delineation_db.py` (marker `db`; the run now with
  sub-catchments of 1 ha and 20 ha): the preview through the real queries equals the full run for
  two networks, its outlines and reach lines follow the full run's.
- Production, read only: the preview against the full run for the three networks of the network
  plan, and the timing over HTTP (Results).

## Documentation

ADR-081 and its row in `docs/DECISIONS.md`, the amendment note of ADR-080; `docs/ARCHITECTURE.md`
(§2.1, §2.2.2c, §2.4.10, §4), `docs/COMPUTATION_PIPELINE.md`, `docs/SCOPE.md`, `README.md`;
`docs/CHANGELOG.md` (the route, the mode); the guide and the presentation (chapter 06);
`docs/PROGRESS.md`.

## Stages

One branch, `feat/network-preview` from `develop` `c5e0bb8`: this plan and ADR-081, the route,
the front end. Merged when the author or the coordinator schedules it, after the gate.

## Results

Filled in when the branch is done.

## Not in this plan

- Recomputing only the elements a change touches (the author, 2026-11-11).
- Outlines exact at the points before the characteristics (they need the raster split).
