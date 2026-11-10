# Plan: a network of subcatchments, reaches and junctions delineated at control points

Approved: 2026-11-10 (the author's decisions B1 to B7 of 2026-11-10, recorded below; the
technical details by delegation, decided here with their reasons).

Requirements: the author's decisions B1–B7; Nogat plan
`docs/plans/2026-11-10-node-provenance-in-handoff.md` (`e133635`: the origin of each node in
`nogat-handoff/1`, whose D7 leaves the origin parameters to this plan); Hydrolog plan
`docs/plans/2026-11-10-network-wizard.md` (`5b115fa`: Sieć opens a network hand-off laid out,
A6); ADR-021, ADR-046, ADR-050, ADR-054, ADR-068, ADR-069, ADR-070; decision ADR-080. Scope:
the new `POST /api/delineate-network`, its core modules, the hand-off of a network and the
map mode „Sieć zlewni”; the cell measures of `scripts/export_catchment_parameters.py` move
into `core/`. Not in scope: routing and the cross-sections of the reaches (Hydrolog's, B4), a
hydrograph of the network or of one of its elements in Hydrograf, Nash by Lutz in the network
document (Hydrolog's A5). Five stages, each on its own branch (Stages).

## Goal

The person clicks the closing section A on a river and control points above it (tributaries at
their mouths, gauges), sees on the map the network Hydrograf builds (subcatchments, reaches,
junctions) with the parameters of each element, and copies it to Hydrolog's „Sieć i
trasowanie” as one hand-off that opens there laid out, with the origin of every node.

## The author's decisions (2026-11-10)

1. **B1.** The person clicks the closing section A and any points on tributaries (and points
   inside, such as gauges). The flow paths from the points to A form a tree; junctions are where
   the paths merge, at confluences.
2. **B2.** The elements of HEC-HMS: each tributary gets its catchment to its mouth; the main
   river above the first junction is a headwater subcatchment; each reach of the main river
   between junctions is a reach; each reach has its intermediate catchment (przyrzecze), the
   area draining to it without the catchments of the clicked points, entering the junction
   below it unrouted.
3. **B3.** A point inside a unit (not at its boundary) is split by the raster at once (pyflwdir
   basins of several outlets in a window); confluences are unit boundaries of the catchment
   graph and need no raster.
4. **B4.** Each subcatchment and przyrzecze gets the parameters of a delineation (area, CN, land
   cover, soil groups, morphometry, PMAXTP); the longest flow path of a przyrzecze is computed
   within it (it is closed downstream). A reach gets its length as the difference of the flow
   distances to the outlet of its ends (`CatchmentGraph._outlet_flow_dist_m`, D8 along the
   burned BDOT10k/MPHP lines) and its slope from the NMT elevations of its ends; the length of
   the vector line (MPHP/BDOT10k), where there is one, as a check. The cross-section (Manning's
   n, width) is left to Hydrolog.
5. **B5.** The areas of the elements sum to the area of A's catchment.
6. **B6.** `POST /api/delineate-network` (a list of points with ids), a map mode to place the
   points and see the tree, and the hand-off: one `nogat-handoff/1` with one
   `hydrolog-network/1` holding the whole network (subcatchments, reaches with length and
   slope, junctions, outlet).
7. **B7.** The origin of each node in the hand-off needs an additive change of Nogat first
   (producers before consumers): the Nogat plan above.

The order of the work: Nogat (the origin of each node) → Hydrolog's library (A5, A4) →
Hydrograf (this plan) and Hydrolog's GUI (A1–A3, A6).

## Where it starts (`develop` `b33594d`)

| Fact | Consequence |
|---|---|
| The catchment graph holds one sub-catchment per stream segment and threshold, each draining into one below (ADR-021); a segment ends at every confluence and change of Strahler order (`core/stream_extraction.py::vectorize_streams`), so it drains into the head cell of the segment below | every confluence of a network is a boundary of its sub-catchments: a junction needs no raster (B3) |
| The precise mode takes the cells draining to the clicked cell in a window of the saved rasters (`core/raster_service.py`, pyflwdir, at most `MAX_WINDOW_CELLS` = 40 M) and its statistics from the graph for the whole sub-catchment of the click (ADR-054, Consequences) | the sub-catchment of a point would be counted in two elements |
| `scripts/export_catchment_parameters.py` measures the panel's parameters from the cells of a polygon on the saved rasters; `test_a_delineated_watershed_gets_the_values_of_the_panel` finds them equal to `_build_watershed_response` for every whole-unit watershed of a synthetic `process_dem` run | measured from its cells, an element gets the parameters of a delineation (B4), the parts of split units included |
| `trace_main_channel` goes up at each confluence into the branch of the largest `upstream_area_km2` (ADR-046) | the main river of any point is defined without river names |
| `outlet_flow_dist_m` of a sub-catchment is the flow distance at the cell below its outlet, the head cell of the one below (ADR-054), from `04b_stream_distance` | the flow distance at a junction is in the graph, at a point in the same raster |
| `hydrolog-network/1` (Hydrolog `759d7ef`, pinned): subcatchment (`watershed`, `runoff`, optional `rainfall`), reach (`muskingum-cunge` requires `length_km` and `slope_m_per_m`, the section is optional), junction (`from` of one or more), outlet (`from` of exactly one), ids `^\w[\w.-]*$` up to 64 characters; `description` (up to 500 characters) and `position` came later (`46c743f`, in `develop` `055a433`) | the whole network fits; a node's `description` needs a pin at `46c743f` or later |
| `runoff {"model": "curve-number"}` is SCS with Kirpich's tc by default (the schema), which needs `cn`, `flow_path_length_km` and `flow_path_slope_m_per_m` | each subcatchment carries them where they can be measured |
| `nogat-handoff/1` gains the optional `node_provenance`, `{node id: {input: origin}}`, an entry winning over `provenance` (Nogat plan, D1–D4) | the origins below |
| Sieć opens a network hand-off without rainfall or positions, laid out from its structure (Hydrolog plan, D4, D7–D9); `route network` needs each reach's section from the person (Nogat plan, its example) | the hand-off carries neither |
| Production runs the API with 2 workers in 8 GB (`docker-compose.prod.yml`, `docker-compose.yml`); nginx gives `/api/` 120 s (`proxy_read_timeout`), Cloudflare's proxy gives up after 100 s | a budget per request and one network at a time per worker |
| Production's rasters: 7,194 × 8,143 cells of 5 m (58.6 M); six of them over a window of 24.0 M cells read in 3.2 s at 22 bytes a cell (measured, Performance) | the window of a whole network is affordable |

## Terms

- **Unit:** a sub-catchment of the graph at `DEFAULT_THRESHOLD_M2` (10,000 m², 1 ha): the cells
  draining to one stream segment, from its head cell (a confluence or a channel head) to its
  outlet cell, which drains into the head cell of the unit below.
- **Control point:** A or a point of the request, after snapping (D2, D3).
- **Trunk of a control point p:** its main river, from p's cell up its unit's segment, then up
  the units `trace_main_channel(u_p, …)` chooses (ADR-046).
- **Element:** a subcatchment (headwater or tributary) or a przyrzecze: the cells draining to
  one outlet cell (D5).
- **fd:** the flow distance to the outlet of the grid, `04b_stream_distance` [m].

## Decisions

### D1. Units of 1 ha; the points snap to the network drawn on the map

The elements are made of units. The request names the stream network the points snap to,
`threshold_m2`: the threshold of the map's streams (`Hydrograf.map.getStreamsThreshold()`), at
least 10,000 m². Why: a confluence of a coarser network is a confluence of the 1 ha network, so
every junction is a unit boundary whatever the map shows (B3); the precise mode measures at
1 ha too, so the elements get its parameters (B4); the person clicks the rivers drawn on the
map, not the 1 ha gullies beside them.

### D2. A point snaps to the nearest stream cell

Each point, A included, moves to the centre of the nearest cell within `NETWORK_SNAP_M` = 100 m
whose accumulation (`04_flowacc`, in cells) reaches `threshold_m2`, the larger accumulation on
a tie; read in a window of 100 m around the click. None → `network_point_off_stream` (404). A
stream cell of `threshold_m2` is a stream cell of 1 ha and carries its own segment's label in
`10_subcatchments_10000`, so its unit is that label and its fd the raster's value there. Why: a
click beside the channel would delineate a few cells of hillside, as the precise mode does with
the clicked cell; the largest accumulation within the radius (StreamStats' rule) would move a
point at a tributary's mouth onto the main river. The map shows each point where it snapped,
and a point on the wrong branch is dragged off it.

### D3. A point at a tributary's mouth delineates the tributary to its mouth

A point that lies off its parent's trunk (D4) and at most `MOUTH_TOLERANCE_M` = 50 m along the
flow above its junction moves to the outlet cell of the last unit above the junction on its
branch: its subcatchment (or its own junction, when points lie above it) enters the junction
directly, with no reach between (B2: „each tributary gets its catchment to its mouth”). Why: a
click at a mouth lands some cells above the confluence, and each tributary would bring a reach
of a few metres and a przyrzecze of a few cells; 50 m is the accuracy of a click at the zoom
the rivers are drawn at. The point moved is a unit boundary, so it needs no raster (B3); the
response marks it (`at_mouth`). A point on a trunk keeps its place: a gauge a few metres above a
junction gets a short reach.

### D4. The tree: each control point's trunk takes the junctions of the points above it

1. The parent of a point is the first control point on its flow path downstream: the nearest
   below it in its own unit (by fd), else the uppermost in the first unit below that holds one;
   A at the latest. A point whose path does not reach A → `network_point_outside` (400).
2. A point q whose parent is p joins p's trunk where its path first meets it: at q itself when
   q's unit is on the trunk (a gauge on the main river), else at the head cell of the trunk unit
   its path enters, a confluence: the junction J(q).
3. The nodes of p's trunk are the junctions and points it carries, ordered by fd. Its edges run
   between consecutive nodes and from the lowest node to p; a point off the trunk and more than
   50 m above its junction adds the edge from it to its junction, along its branch.
4. Every edge is a reach with its przyrzecze. The trunk above its uppermost node, when that node
   is a junction, is a headwater subcatchment. A point with no point above it is a
   subcatchment: a tributary when it lies off its parent's trunk, the headwater when on it.
5. Every junction and every control point with points above it is a junction of the network;
   A's junction flows into the outlet (`OUT`).

Why: B2 makes the main river above the first junction a headwater, and the paths of the points
alone carry no main river: with points at tributary mouths the first merge of two paths lies on
the main river below both, and the headwater, often most of the area, would fall into the
przyrzecze of the first reach and enter its junction unrouted. The main river of each control
point by the rule of the delineation (ADR-046) gives HEC-HMS's layout for points at tributary
mouths and the same layout nested for points above points (a gauge on a tributary with points
on its own tributaries). Every confluence as a junction would make hundreds of elements at
1 ha. ADR-080, option 1.

### D5. The cells of each element

Every element ends at one outlet cell and holds the cells whose first element outlet downstream
(the cell itself included) is it:

- a control point's cell ends the element that reaches it along its trunk: its own subcatchment
  when no point lies above it, else the przyrzecze of its trunk's lowest edge, or the headwater
  when no node lies on the trunk above it;
- a junction ends each element that reaches it on a branch (the headwater, the przyrzecze of an
  edge from above, a tributary at its mouth) at the outlet cell of that branch's unit above it;
- the junction's own cell, the cells draining into it from the side and the units that join
  there without a point belong to the element below the junction (the przyrzecze of its edge
  downward), as they belong to the unit below in the graph; the part of A's unit below A lies
  outside the network.

In the graph a unit belongs to the element of the first element outlet on its segment from its
head, else to the element its unit below receives at its head: one pass over the units of A's
catchment from A upward (`CatchmentGraph.upstream_tree`, new: the order of
`traverse_upstream` and the unit below each). An element without cells (an edge between two
neighbouring cells) is left out. Why: these are the boundaries the units have, except at
control points; every cell of A's catchment gets one element; no element is open downstream,
so the flow paths of a przyrzecze stay inside it (B4).

### D6. A unit with a control point inside is split by pyflwdir (B3)

A unit that holds a control point not at its outlet cell is split in the window of D7:
`pyflwdir` `basins` on the D8 of the unit's extent plus one cell (`d8_from_saved_flowdir`), with
an outlet at each control point in it and at its outlet cell; each cell of the unit takes the
element of the first outlet below it (checked: two outlets on a line of five cells give
`[1 1 2 2 2]`). Two or more points in one unit split it into three or more parts in the same
pass, so points on the same unit are no error; points that snap to one cell are
(`network_points_coincide`). Why: B3; one pass for any number of points; the other cells of the
window keep their units.

### D7. One window of the saved rasters over A's catchment

The units of A's catchment (`traverse_upstream` from A's unit) give the window: their extent
(`catchments_bounds`) and 50 m (`WINDOW_MARGIN_M`), grown as the precise mode grows its window
while a cell of these units lies on an edge that is not the edge of the rasters. It holds the six
rasters the measures read (`02_filled`, `05_slope`, `04_flowacc`, `03_flowdir`,
`04b_stream_distance`, `10_subcatchments_10000`, resolved through `Settings`, the active unit
run's mosaics first) and the element raster (int16), built from the labels by a table unit →
element and overwritten by D6 for the split units. A window of more than
`NETWORK_MAX_WINDOW_CELLS` = 60 M cells is refused before it is read
(`network_window_too_large`, 422). Why: 22 bytes a cell (measured) and 2 for the element raster
make about 1.4 GB at the cap, the precise mode's budget at its 40 M cells of 35 bytes; 60 M take
production's whole grid (58.6 M); pyflwdir runs only on the split units, and no flow directions
are computed: the rasters are the pipeline's, as for the precise mode and the flow paths.

### D8. Each element is measured from its cells

Stage S1 moves the measures of `scripts/export_catchment_parameters.py` (`_terrain`, `_outlet`,
`_baseline_m`, `_flow_path_columns`, `main_channel`, `_channel_columns`, the window of
`read_polygon_cells`) and `_overland_segments`, `d8_from_saved_flowdir` and
`INTERMEDIATE_SUFFIXES` of `scripts/process_dem.py` into `core/cell_parameters.py`, taking a
window of the rasters and a mask of the cells that drain to the outlet; the export (its polygon
and the pyflwdir basin of its outlet give the mask) and `process_dem` import them, no copies.
`_overland_segments` becomes a walk along the saved D8 directions from each head to the first
stream cell (numba, many heads at once), so no measure builds a pyflwdir object: an element's
bounding box can hold tens of millions of cells, and its cells drain to its outlet by D5, so it
needs no basin. The tests of the export and of `process_dem`'s flow paths guard that the walk
measures what pyflwdir's `path` measured. An element is measured with them:

- **Terrain:** `zonal_summary` over the element raster, one pass for all elements: area (cells ×
  cell area, km² to 6 decimals, exact to the cell), elevations, mean slope, the histograms of
  1 m bins the units have, normalized as `aggregate_hypsometric` does.
- **Outlet:** the element's outlet cell (D5), its elevation in the filled DEM, in WGS84.
- **Flow paths:** `watershed_flow_paths` on the element's cells, closed downstream (D5), from the
  fd of the cell below the outlet (ADR-054): the longest flow path and its slope from its head,
  the divide path, the overland segment down to the first 1 ha stream cell (ADR-070).
- **Main channel:** up from the outlet into the element's stream cell of the largest
  accumulation, as `trace_main_channel` goes up the element's units only; its length by D8
  steps, its slope from its source; its BDOT10k part from `stream_network.is_real_stream` of the
  units it crosses (`contiguous_real_length_km`); `length_to_centroid_km` is the centroid of the
  element's boundary projected on the channel's line (Snyder, Lutz). A przyrzecze's channel runs
  up its reach.
- **Drainage indices** (`drainage_density_km_per_km2`, `stream_frequency_per_km2`,
  `max_strahler_order`, `bdot_stream_length_km`, `bdot_stream_count`): from the graph's values
  of the element's units, a split unit's segment shared by the stream cells in each part.
- **From the boundary (D9):** perimeter and shape indices (`calculate_shape_indices`); land cover
  with the CN of the soil-cover complexes and the shares of forest and urban land, and the soil
  groups (`build_land_cover_stats`, `build_hsg_stats`, the boundary simplified 20 m above 5 km²,
  as the panel does); the PMAXTP Thiessen weights (`thiessen_cells`, ADR-069);
  `hydrograph_available` up to 250 km².

The result is a `WatershedResponse` per element, the panel's model: the front end shows an
element as it shows a watershed, and the hand-off takes its `morphometry` as ADR-068 does. Why:
the export's test proves these measures equal to the panel's for whole units, and they are exact
for the parts of split units; the graph's path would need pseudo-units in every function keyed
by `segment_idx`, and a precise delineation per element would read a window each (ADR-080,
option 3).

### D9. The boundaries are one coverage

The element raster is vectorized once (`rasterio.features.shapes`), its rings are noded so that
each meeting point of three elements is a vertex of every ring through it (a valid coverage),
and the elements are simplified together at 5 m (`shapely.coverage_simplify`; `uv.lock` has
shapely 2.2.0, whose GEOS 3.14 has it). A's boundary is their union. Why: the precise mode's
smoothing of each polygon alone (Chaikin) would leave gaps and overlaps along the shared edges;
the coverage keeps them shared, so the map shows the tree without slivers and no land is counted
twice. Measured: 2.3 s to vectorize and node 40 elements of 24 M cells, 0.34 s to simplify them
(148,181 to 44,775 vertices, a valid coverage).

### D10. Reaches

For the edge from node n down to node m:

- `length_km` = (fd(n) − fd(m)) / 1000 (B4): fd at a junction is `get_outlet_flow_dist_m` of the
  units draining into it, at a control point the raster at its cell; both come from
  `04b_stream_distance`, and a test checks that they agree at junctions.
- `slope_m_per_m` = (z(n) − z(m)) / (1000 · `length_km`), z the NMT (`01_dem`,
  `resolve_dem_path`) at the two cells (B4). Where it is not positive,
  `MIN_REACH_SLOPE_M_PER_M` = 0.0001 (0.1 ‰), with the origin `"slope": "minimum"` and a
  notice. Why the NMT and not the filled DEM: the filled DEM carries the 2 m of the burning and
  the strict descent of ADR-072 and ADR-077 on burned lines only, so a reach with one burned end
  gets 2 m wrong; the floor, because Hydrolog refuses a slope that is not positive and a lowland
  reach of a few cells can show none.
- `vector_length_km` (the check of B4): the reach's D8 line is sampled every 10 m; each sample
  takes the nearest line of `bdot_streams` within 25 m (`BDOT_BUFFER_M`, the matching buffer of
  ADR-044); the length is the sum, over consecutive samples, of the distance along their line
  when they share it, else between their projections. Null when a sample has no line within
  25 m. `vector_source` is `"bdot10k"`: the table holds BDOT10k's SWRS, SWKN and SWRM lines, the
  MPHP watercourses among them without their identifiers. Why: the BDOT10k lines split at every
  tributary, so a merged line rarely spans a reach, and the lines inside a corridor count the
  tributaries crossing it.
- The line of the reach is the centres of its D8 cells (`path_coords`).
- No section (B4); `"method": "muskingum-cunge"` in the hand-off.

### D11. The check of B5

The cells of the elements (the element raster) must equal the cells of A's catchment counted from
the graph: the sum over the units of A's catchment of `round(area_km2 / cell area)`, less the
cells of A's unit below A. Any difference is a defect: 500 `internal_error` with the reason
`network_area_mismatch`, never a network whose areas do not add up. The response gives both
sums (`area_check`). Why: two independent counts, the preprocessing's unit areas and the
window's labels, catch a unit missing from the window and a label missing from the graph;
compared in cells, since the graph keeps `area_km2` as float32.

### D12. Errors

Problem documents of the registry's codes (ADR-059); the new message IDs with English and Polish
texts in `core/messages.py`; `details` names the point (`point_id`, `point_ids`), so the map
marks it.

| Case | Status and code | Message ID (reason) |
|---|---|---|
| Invalid request: coordinates, no point, more than 30 points, an id not `^[A-Za-z0-9][A-Za-z0-9_-]{0,15}$`, two ids equal without regard to case, `threshold_m2` below 10,000 | 400 `validation_error` | `invalid_request` (pydantic, `errors[].pointer`) |
| A point (or A) with no stream cell of `threshold_m2` within 100 m, or off the rasters: „Punkt {point_id} leży dalej niż 100 m od cieku sieci {threshold}.” | 404 `not_found` | `network_point_off_stream` |
| A point that does not drain to A: „Punkt {point_id} nie odwadnia się do przekroju zamykającego {outlet_id}.” | 400 `validation_error` | `network_point_outside` |
| Points, or a point and A, on one cell after D2 and D3: „Punkty {point_ids} trafiają w tę samą komórkę cieku.” | 400 `validation_error` | `network_points_coincide` |
| The window of A's catchment above 60 M cells: „Zlewnia przekroju zamykającego jest za duża dla sieci: …” | 422 `unsupported` | `network_window_too_large` (`cells`, `max_cells`) |
| The catchment graph not loaded | 503 `store_unavailable` | `catchment_graph_unavailable`, as `delineate-watershed` |
| A raster missing, or the rasters not on one grid | 503 `store_unavailable` | `network_rasters_missing`, `raster_grids_differ` |
| Another network still running in this worker after 15 s (D13) | 503 `store_unavailable` | `network_delineation_busy` |
| The elements do not add up to A (D11) | 500 `internal_error` | `network_area_mismatch` |
| Any other failure | 500 `internal_error` | `network_delineation_failed` |

Points on the same unit are no error (D6). An element above 250 km² is no error: its
`hydrograph_available` is false and a notice names it, since SCS-CN's limit applies to each
subcatchment, not to the network.

### D13. One network at a time per worker

The endpoint runs under a lock of its process (`threading.Lock`); a second request waits up to
15 s, then gets 503 `network_delineation_busy`. With production's two workers at most two
networks run at once, about 4 GB of the 8 GB at the cap. The nginx limits of `/api/` stay (10
requests a second, burst 20): the lock and the window cap bound the cost. Why: a network reads
up to 1.4 GB of rasters, several times the precise mode's usual window, and the endpoint is
public.

### D14. The hand-off

`core/handoff.py` gains `build_network_handoff` beside `build_handoff`, with the same envelope
constants (ADR-068):

- **Envelope:** `schema`, `created_at`, `producer` (Hydrograf and its version), `subject`;
  `provenance` `{"watershed": {"source": "hydrograf", "point": "A", "latitude": …,
  "longitude": …, "threshold_m2": …}}`, A's snapped place (Nogat D4: the network's origin);
  `node_provenance` with an entry for every subcatchment, reach and junction (Nogat D7), none for
  `OUT`.
- **Payload** `hydrolog-network/1`: `name` (= `subject`), `description`, and the `nodes` in the
  order of D15. No `rainfall`, `timestep_min` or `result`, as the hand-off of
  `delineate-watershed`: the person sets the network's rainfall first, in Sieć's step „Sieć”
  (Hydrolog's A2).
- **Subcatchment:** `watershed` = `watershed_parameters(morphometry, name)` (the keys of
  `WatershedParameters`, the area to 6 decimals, so the subcatchments sum to A in Hydrolog too),
  `runoff` `{"model": "curve-number"}` (Hydrolog's defaults, as the delineation's hand-off),
  `description`.
- **Reach:** `method` `muskingum-cunge`, `from` (one node), `length_km`, `slope_m_per_m`,
  `description`; no section: the person gives Manning's n and a width in Sieć before the network
  is routed (B4).
- **Junction:** `from` (its inflows: the trunk's first, then the branches by upstream area),
  `description`. **Outlet** `OUT`: `from` A's junction.
- **Names and descriptions** (Polish, at most 500 characters, no control characters): `subject`
  is A's `name`, else `watershed_name` of A, then „, sieć” and the number of subcatchments
  („3 zlewnie”, „5 zlewni”); headwater „Zlewnia górna powyżej J1” or „… do punktu P3 (name)”;
  tributary „Dopływ do punktu P1 (name)”, at its mouth „Dopływ do ujścia przy P1 (name)”;
  przyrzecze „Przyrzecze odcinka R1”, each with its area; reach „Odcinek od J1 do J2: 5,07 km,
  spadek 0,98 ‰ (NMT)” or „(minimalny)”; junction „Zbieg: dopływ P1 (name)”, „Punkt P3 (name)” or
  „Przekrój zamykający A (name)”.
- **The origin parameters** (Nogat D7 leaves them here), `source` `"hydrograf"` in each:
  - subcatchment, input `watershed`: `element` (`"headwater"`, `"tributary"`,
    `"intermediate"`), `point` (the request's id of the point it ends at, if any), `reach` (of a
    przyrzecze), `at_mouth` (true when D3 moved its point), `latitude`, `longitude` (its outlet);
  - reach, input `node`: `element` `"reach"`, `length` `"flow_distance"`, `slope` `"nmt"` or
    `"minimum"`, `upstream_elevation_m`, `downstream_elevation_m` (the NMT at its ends),
    `vector_length_km` and `vector_source` `"bdot10k"` when there is a check length;
  - junction, input `node`: `element` (`"confluence"`, `"point"`, `"outlet"` for A's), `point`
    (its point's id, if any), `latitude`, `longitude`.
- **Copies and pins:** S3 copies Nogat's envelope of its step 1 into
  `schemas/nogat/handoff-1.schema.json`, its commit and SHA-256 in `schemas/nogat/README.md` and
  the CHANGELOG (as for `8727f6e`), and pins Hydrolog at the commit of Nogat's release set then
  current, at `46c743f` or later (the schema with `description`; after Hydrolog's library stages
  W1 and W2, HUB-5.2).

No `position`: Sieć lays a network without positions out from its structure (Hydrolog plan, D7,
D8). The single-watershed hand-offs of `delineate-watershed` and `generate-hydrograph` do not
change (Nogat D7).

### D15. Ids and order

A walk of the tree from A, each node after everything it receives: at a node the incoming
branches in descending order of the accumulation of their last cell (the trunk first); a branch
that is an edge brings its upper node's elements and junction (or its subcatchment), then its
reach, then its przyrzecze; a branch without a reach brings its headwater, or the tributary at its
mouth (its subcatchment, or its junction with everything above it); then the node's junction.
Subcatchments are numbered `Z1`, `Z2`, … in that order, reaches `R1`, …, junctions `J1`, …; the
outlet is `OUT`. The hand-off lists the nodes in that order, so a node follows every node it
receives from; for one tributary at its mouth: `Z1` (headwater), `Z2` (tributary), `J1`, `R1`,
`Z3` (its przyrzecze), `J2` (at A), `OUT`, the order of Nogat's example. The same points in any
order give the same network.

## The algorithm, in order

1. Validate the request (D12); take the lock (D13); load the graph (`loaded_catchment_graph`).
2. Snap A and each point (D2) in a window of 100 m around each click; their units and fd.
3. A's catchment: `upstream_tree` of A's unit. Each point's unit must be in it, and a point in
   A's unit above A by fd, else `network_point_outside`.
4. The mouth rule (D3) for every point off the trunk of the first control point below it; then,
   on the moved points and from A upward, the parents, the trunks (`trace_main_channel` of each
   control point with points above it), the junctions and the nodes and edges of every trunk
   (D4); points on one cell → `network_points_coincide`.
5. Element outlets, the unit → element table and the split units (D5, D6); ids and order (D15).
6. The window (D7), refused above the cap; the element raster; the splits (D6).
7. The check of B5 (D11).
8. The measures of every element (D8), the coverage (D9), the reaches (D10).
9. The response and its hand-off (D14); release the lock.

## API

`POST /api/delineate-network` (`api/endpoints/network.py`, registered in `api/main.py` with the
problems of the watershed routes: 404, 422, 503; `operationId` `delineate_network`). The models
are in `models/schemas.py`.

Request (`DelineateNetworkRequest`):

```json
{
  "outlet": {"id": "A", "latitude": 51.128, "longitude": 15.909, "name": "Kaczawa"},
  "points": [
    {"id": "P1", "latitude": 51.01538, "longitude": 15.890496, "name": "Kamiennik"},
    {"id": "P2", "latitude": 51.0712, "longitude": 15.8021}
  ],
  "threshold_m2": 100000
}
```

- `outlet` (`NetworkPoint`): the closing section A; `id` defaults to `"A"`.
- `points` (`NetworkPoint`, 1 to 30): `id` `^[A-Za-z0-9][A-Za-z0-9_-]{0,15}$`, the ids of the
  outlet and the points unique without regard to case; `name` optional, 1 to 100 characters,
  names the elements and nodes in the hand-off.
- `threshold_m2`: the stream network the points snap to, at least 10,000 (D1).

Response (`DelineateNetworkResponse`, 200):

```json
{
  "threshold_m2": 100000,
  "unit_threshold_m2": 10000,
  "area_km2": 238.712375,
  "area_check": {"watershed_km2": 238.712375, "elements_km2": 238.712375},
  "boundary_geojson": {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": []}},
  "points": [
    {"id": "A", "name": "Kaczawa", "latitude": 51.12801, "longitude": 15.90897,
     "snap_distance_m": 7.1, "at_mouth": false, "node": "J3"},
    {"id": "P1", "name": "Kamiennik", "latitude": 51.0155, "longitude": 15.88991,
     "snap_distance_m": 4.0, "at_mouth": true, "node": "Z2"}
  ],
  "subcatchments": [
    {"id": "Z1", "kind": "headwater", "to": "J1", "point": null, "reach": null,
     "watershed": {"area_km2": 61.3, "morphometry": {}, "land_cover_stats": {}}}
  ],
  "reaches": [
    {"id": "R1", "from": "J1", "to": "J2", "length_km": 5.0712, "slope_m_per_m": 0.00981,
     "slope_method": "nmt", "upstream_elevation_m": 281.4, "downstream_elevation_m": 231.66,
     "vector_length_km": 4.87, "geojson": {"type": "Feature"}}
  ],
  "junctions": [
    {"id": "J1", "kind": "confluence", "point": null, "latitude": 51.0157,
     "longitude": 15.8901, "inflows": ["Z1", "Z2"]}
  ],
  "notices": [{"code": "reach_slope_minimum", "ids": ["R3"]}],
  "handoff": {"schema": "nogat-handoff/1"}
}
```

- `area_km2` and `area_check`: A's catchment, from the cells (D11), to 6 decimals.
- `points[]`: each point where it snapped (WGS84), its distance from the click, `at_mouth`
  (D3) and its node: its subcatchment when nothing lies above it, else its junction.
- `subcatchments[]`: `kind` (`headwater`, `tributary`, `intermediate`), the node it flows into
  (`to`), the point it ends at, the reach of a przyrzecze, and its `WatershedResponse` (D8).
- `reaches[]`: D10, with the line in WGS84; `from` is the JSON name of the field `from_node`.
- `junctions[]`: `kind` (`confluence`, `point`, `outlet`), place, inflows.
- `notices[]`: `over_scs_cn_limit` (subcatchments above 250 km²) and `reach_slope_minimum`, with
  the ids; the front end words them.
- `handoff`: D14.

## Front end

Files: `js/network.js` (new IIFE `Hydrograf.network`: the points, their markers, the request,
the layers of the result and the panel section), `js/api.js` (`delineateNetwork(body)`),
`js/app.js` (the mode `network` in `setClickMode`, `onMapClick` and `MODE_HINTS`),
`js/handoff.js` (the contents of a network's hand-off; the section serves the mode that shows),
`index.html` (the button „Sieć zlewni” in `#mode-toolbar` after „Wybierz zlewnię”, the panel
section, the script), `css/app.css` (colours only from `tokens.css`, ADR-065), `js/info-texts.js`
(the (i) of the element kinds, a reach's length, slope and check length),
`instrukcja/index.html`; `python3 scripts/bump_asset_versions.py` before each commit.

1. „Sieć zlewni” opens the results column with its section and the hint „Kliknij przekrój
   zamykający A na cieku, potem punkty: dopływy przy ujściach i wodowskazy.”; the section names
   the network the points snap to („Punkty dociągane do cieków progu 10 ha”).
2. The first click places A, the next ones P1, P2, …: numbered markers that can be dragged; the
   section lists them with a name field and „Usuń”.
3. „Wyznacz sieć” (with A and at least one point) sends the request, with the loading state of
   the panel; a change of the points afterwards marks the result outdated.
4. The result: every marker moves to its snapped cell („przy ujściu” on a point D3 moved); the
   elements filled by kind (zlewnia górna, dopływ, przyrzecze), the reaches as lines with their
   ids, the junctions as dots, A's boundary. The section lists the tree from A upward, indented
   (J2 ← R1 ← J1 ← Z1, Z2; Z3), each element with its area and CN, each reach with its length and
   slope; the check „Suma elementów = zlewnia A” with both areas; the notices (elements above
   250 km², reaches with the minimum slope).
5. A click on an element, on the map or in the list, shows its parameters in the sections of
   „Wybierz zlewnię” (basic, shape, relief, drainage, land cover, soil groups, with their (i));
   a reach shows its length, slope and its source, the NMT at its ends and the BDOT10k check
   length. The hydrograph and the single watershed's hand-off are not offered for an element.
6. „Przekazanie do Hydrologa”: „Kopiuj do Hydrologa” and „Plik przekazania”
   (`<subject>.handoff.json`), with „Zawiera sieć: 5 zlewni, 2 odcinki, 3 węzły, bez opadu (opad
   sieci ustawisz w Hydrologu, w kroku „Sieć”) i bez przekrojów odcinków (n Manninga i szerokość
   uzupełnisz w Hydrologu).”
7. An error shows in the panel's error box (`showError`, `problemMessage`); with
   `details.point_id` or `details.point_ids` the markers and list rows are marked.
8. On a phone the section is the right bottom sheet (`shell.js`); the markers drag by touch.
9. Leaving the mode hides the network's layers and section, coming back shows them; „Wyczyść”
   removes the points and the result.

## Performance budget

Measured on 2026-11-10 with throwaway scripts on production's rasters (read only, a window of
4,000 × 6,000 cells, the 10 km² sub-catchments of the window standing for 40 elements);
estimated from them and from the single delineation where marked.

| Step | Measured | Budget at the cap (60 M cells) |
|---|---|---|
| Graph: snapping windows, trunks, elements of up to 50,000 units | — | < 1 s |
| Reading the six rasters | 3.2 s for 24 M cells (local GeoTIFF), 22 bytes a cell | ≤ 9 s on production; Hydroni's mosaics on the NAS are slower (a 500 km² watershed's flow paths read 6.1 s there) |
| Element raster and splits | lookup unit → element 0.42 s for 24 M cells | < 2 s |
| `zonal_summary` of all elements | 0.21 s for 24 M cells | < 1 s |
| Flow paths of all elements | 0.88 s for 40 elements | < 3 s |
| Coverage: vectorize, node, simplify | 2.7 s for 40 elements | < 8 s |
| Land cover, soils and Thiessen weights of all elements | — | about the single delineation of A's area (Wełna, 500 km², Hydroni: land cover 7.7 s, Thiessen 3.2 s) |
| Reaches: NMT at the ends, check lengths | — | < 2 s |
| **Whole request** | — | ≤ 30 s for 250 km² and 10 points on production, ≤ 75 s at the cap, within nginx's 120 s and Cloudflare's 100 s |
| **Memory** | 888 MB resident for 24 M cells with the interpreter | ≤ 2 GB a request; one per worker (D13) |
| **Response** | 44,775 vertices for 40 elements at 5 m | ≤ 3 MB |

Measured again in stage S5 (Results), on production's data, for both of its networks.

## Tests

Stage S1 (`refactor/cell-parameters`): the tests of the export
(`tests/unit/test_export_catchment_parameters.py`, among them
`test_a_delineated_watershed_gets_the_values_of_the_panel`) and of the flow paths of
`process_dem` (`tests/unit/test_flow_path.py`) pass unchanged; the tests of the moved functions
move with them.

Stage S2, unit, synthetic graphs (`tests/unit/test_network_tree.py`): a `CatchmentGraph` built
from arrays as `small_graph` of `tests/unit/test_catchment_graph.py`, a main river of eight
units with three tributaries, one of them with a tributary of its own:

1. Points at the three mouths: a junction at each confluence, the headwater above the uppermost,
   a reach and its przyrzecze between junctions and down to A, A's junction and `OUT`; every unit
   in exactly one element; the ids and order of D15 (Nogat's example for one tributary).
2. A point 200 m up a tributary: the edge to the mouth is a reach with its przyrzecze; at 40 m it
   moves to the mouth (D3), no reach.
3. A gauge on the main river between two junctions: a junction of kind `point` splits the reach;
   a gauge above every junction: the headwater ends at the gauge.
4. Points on a tributary's tributary and at the tributary's mouth: the tributary's own trunk,
   headwater and junction.
5. The trunk takes the larger upstream area (ADR-046): a point on the smaller branch of a
   confluence is a tributary, on the larger a gauge.
6. Two points in one unit, and a point in A's unit: the split specifications (the outlets of each
   unit in the order of the flow); a point that does not reach A → `network_point_outside`; two
   points on one cell, or two moved to one mouth → `network_points_coincide`.
7. The same points in another order give the same network.

Stage S2, unit, synthetic rasters (`tests/unit/test_network_delineation.py`): a synthetic DEM of
a main river with three tributaries processed by `process_dem` with saved intermediates (the
fixture of `test_export_catchment_parameters.py`, moved to a shared fixture module):

8. Snapping: the nearest stream cell of the threshold within 100 m, the larger accumulation on a
   tie; beyond 100 m → `network_point_off_stream`.
9. A unit split by one point gives two parts, by two points three, and the parts partition the
   unit.
10. The element raster partitions A's cells (B5); with a unit left out of the window →
    `network_area_mismatch`.
11. Every element of whole units has the panel's parameters: `_build_watershed_response` on the
    graph with the element's units, the fields and tolerances of the export's test.
12. A przyrzecze's longest flow path starts and ends inside it and is as long as the fd of its
    head less the fd of the cell below its outlet; its main channel runs up its reach.
13. Reaches: the length is the fd difference and equals `get_outlet_flow_dist_m` at the
    junctions; the slope is the NMT's; a reach whose NMT does not fall gets 0.0001 and
    `"slope": "minimum"`.
14. The boundaries are a valid coverage after the simplification and their union is A's; the
    areas are exact to the cell and sum to A's.

Stage S3, unit:

15. The hand-off validates against the copied envelope with `node_provenance` and against the
    pinned Hydrolog's `hydrolog-network/1`; every key of `node_provenance` names a node of the
    payload, every subcatchment, reach and junction has an entry and `OUT` none (Nogat's step 2);
    the nodes are in the order of D15; reaches and the outlet have one inflow; there is no
    rainfall, time step or result; every `description` has at most 500 characters and no control
    character.
16. The endpoint (`TestClient`, `DEM_DIR` at the synthetic run's rasters, the graph and the
    queries faked as in `test_export_catchment_parameters.py`): the problem documents of D12
    with `details.point_id`; `Accept-Language: pl` gives the Polish texts.
17. A request while the lock is held waits, then gets 503 `network_delineation_busy`.
18. Contract: `tests/contract/test_openapi.py` finds `delineate_network` with its problems;
    `tests/contract/test_messages.py` the new message IDs.

Stage S3, database (`tests/integration/test_network_delineation_db.py`, marker `db`):
`process_dem` of the synthetic DEM into a scratch PostGIS (`tests.scratch_db`, as
`tests/integration/test_unit_run_db.py`), with land cover, soil groups and BDOT10k lines
inserted:

19. B5 and the parameters through the real queries; the land cover of the elements sums to that
    of A's boundary within 0.1 %.
20. A reach along a straight BDOT10k line has the line's length between its ends within 1 % as
    `vector_length_km`; a reach with a gap in the lines has none.
21. The response's hand-off validates as in 15.

The front end has no test runner (ADR-068): it is checked in a browser in S5;
`scripts/bump_asset_versions.py --check` runs in the gate.

**Smoke on real data (S5)**, on production's Kaczawa, read only: a throwaway stack
(`docker compose -p network-smoke`, the branch's image, a database restored from a `pg_dump` of
`hydro_db`, production's `data/nmt` mounted read only, a free port), removed afterwards.

- Network 1: A on the Kaczawa at its 238.7 km² node (51.128° N, 15.909° E, ADR-069); P1 on the
  Kamiennik at 51.01538° N, 15.890496° E (37.23 km² as one watershed, store-migration plan, S2);
  two more tributary mouths and one gauge on the Kaczawa between them, chosen on the map at the
  smoke and recorded in Results.
- Network 2: the same points with A at the outlet of production's area (51.222825° N,
  16.179380° E, 790.6 km², a window of 58.6 M cells, near the cap).
- Accepted when: B5 holds to the cell; the Kamiennik's element equals the precise delineation of
  its snapped point (or the Kamiennik to its mouth, D3) within its unit's area; every
  subcatchment has its CN, flow path length and slope; every reach a positive slope, and its
  check length, where given, is within 15 % of its length; network 1 takes at most 30 s and
  1 GB, network 2 at most 75 s and 2 GB; both hand-offs validate against both schemas and, with
  Hydrolog's W5 merged, open in Sieć laid out with the origin of each node (the Hydrolog plan's
  risk „Hydrograf's real hand-offs”).
- The front end in a browser against that stack, on a desktop and a phone-sized window: the
  steps of the Front end section; screenshots with the Results.

## Documentation

- `docs/decisions/0080-network-delineation-at-control-points.md` and its row in
  `docs/DECISIONS.md` (with this plan).
- `docs/ARCHITECTURE.md`: §2.2 the endpoint (request, response, errors), §2.4 the modules
  `core/network_tree.py`, `core/network_delineation.py` and `core/cell_parameters.py`, the front
  end's module map (`js/network.js`).
- `docs/COMPUTATION_PIPELINE.md`: the network (the tree, the cells, the measures, the reaches,
  B5).
- `docs/SCOPE.md`: the network delineation in scope (routing stays out); `docs/PRD.md` if it
  lists the endpoints.
- `docs/integrations/HYDROLOG.md`: the network hand-off and the pin; `schemas/nogat/README.md`:
  the new copy and its SHA-256.
- `docs/CHANGELOG.md` `[Unreleased]` `### Added`: the endpoint (S3), the mode (S4).
- `docs/INFO_TEXTS_SOURCES.md`: the sources of the new (i) (HEC-HMS Technical Reference Manual
  for the elements, Ponce's Muskingum–Cunge for the reach's length and slope).
- `frontend/instrukcja/index.html`: slides of the mode.
- `backend/scripts/README.md`: the export and `process_dem` take their measures from
  `core/cell_parameters.py`.
- `docs/PROGRESS.md` at each stage.

## Stages

Each later branch starts from the previous one; merged into `develop` with a merge commit when
its gate passes and the coordinator schedules it. No release is cut for this work now (the
coordinator, 2026-11-10: the author has not settled the versions, and no tag is set): S1 and S2
merge when green, S3 and S4 merge into `develop` in the usual way after S5.

| Stage | Branch | Content | Needs | Merged |
|---|---|---|---|---|
| S0 | `plan/network-delineation` | this plan, ADR-080 | — | fast-forward, 2026-11-10 |
| S1 | `refactor/cell-parameters` | `core/cell_parameters.py` (D8), the export and `process_dem` importing it; no change of behaviour | — | when green |
| S2 | `feat/network-delineation-core` | `core/network_tree.py` (pure, on the graph: D3–D5, D15), `core/network_delineation.py` (snapping D2, window D7, splits D6, element raster, B5, measures D8, coverage D9, reaches D10), `CatchmentGraph.upstream_tree`; tests 1–14 | S1 | when green (no change users see) |
| S3 | `feat/network-delineation-api` | endpoint, models, messages, `build_network_handoff`, the envelope's copy, the Hydrolog pin, tests 15–21, ARCHITECTURE, COMPUTATION_PIPELINE, SCOPE, HYDROLOG, CHANGELOG | S2; Nogat's step 1 merged; a Nogat release set with Hydrolog at or after its W2 | with S4, after S5 |
| S4 | `feat/network-delineation-ui` | front end, guide, (i) texts and their sources, CHANGELOG | S3 | after S5 |
| S5 | on S4's branch | the smoke, Results, PROGRESS | S4 | with S4 |

Deploying is the coordinator's: a new image, no migration and no data change. After S3 is in
`develop`, Nogat adds the registry edge of its D10.

## Results

None yet.

## Not in this plan

- Routing, the reach sections and a hydrograph of the network or of an element in Hydrograf:
  Hydrolog's (SCOPE keeps routing out).
- A network whose window exceeds 60 M cells is refused, not computed on coarser units (the
  coordinator, 2026-11-10). A stage that delineates such a network on coarser units is later
  work, not part of S1–S5.
- Positions of the nodes (Sieć lays the network out); `nash_estimation` in the runoff
  (Hydrolog's A5, optional for producers); a network handed back from Hydrolog.
