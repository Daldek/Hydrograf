# ADR-081: The network composed on the catchment graph, its characteristics on confirmation

**Date:** 2026-11-11
**Status:** accepted (the author's design of 2026-11-11; the details by delegation)

## Context

In the mode „Sieć zlewni” of ADR-080 the person places the closing section A and the points
above it and presses „Wyznacz sieć”; only the full run (`POST /api/delineate-network`) shows
where each point snapped, which moved to a mouth, how the tree joins and which elements it
makes. That run reads the saved rasters of A's whole catchment: 3 s for the Kamiennik (37 km²),
5–8 s for the Kaczawa node (240 km²), 14–24 s and 1.8 GB for production's whole area (792 km²,
plan `2026-11-10-network-delineation`, Results). A point on the wrong branch, off the streams
or outside A shows only after it, and every correction costs another run.

The author decided on 2026-11-11 that the mode works in two stages:

1. **Composition on the graph, live.** Every change of the points sends a light request that
   returns in a fraction of a second: the snapped points (with `at_mouth`), the tree (junctions,
   reaches, subcatchments with the Z/R/J ids the full run will give), the area of each element
   from the units of the graph, the length of each reach from the flow distances, outlines of the
   elements from the polygons of the units (no vectorizing of a raster), and the errors of the
   composition at once (a point outside A, too far from a stream, points on one cell).
2. **Characteristics after confirmation.** The full run, named „Oblicz charakterystyki” in the
   panel, alone gives the parameters and the hand-off; any change of the points makes its result
   stale and the mode returns to the preview.

Recomputing only the changed elements is not part of it. A point inside a unit, which the full
run splits by the raster, is shown with the unit's outline and a mark that the exact boundary
comes with the characteristics.

What the preview can build on:

- The catchment graph (ADR-021) holds, for each unit of 1 ha, its area (exact in cells, D11 of
  ADR-080), the unit below it, the upstream area and the flow distance at its outlet cell, and the
  same for the sub-catchments of 10 ha, 1 km² and 10 km². A confluence of a coarser network is a
  confluence of every finer one, so a coarser sub-catchment is made of whole units of 1 ha.
- `stream_catchments` holds the polygon of each sub-catchment (simplified by the preprocessing at
  twice the cell size; 180 vertices a unit of 1 ha on production) and `stream_network` the line of
  its stream, smoothed by Chaikin with its ends kept (the junction cell is the last vertex of the
  line above it).
- The snapping of ADR-080 (D2) takes the cell of the largest accumulation, its unit, flow distance
  and the path below it from five rasters around the click; the graph holds none of them per cell.
- Measured on 2026-11-11 on production's database (read only): `ST_Union` of 1,000 units of 1 ha
  takes 1.4 s, of 10,000 units 23 s; the whole area holds 41,515.

## Options considered

1. **Where the points snap.**
   - **A. To the stream lines of the graph** (`stream_network`), reading no raster: the cell, its
     accumulation and the path down that the mouth rule follows are not in the database, so a
     point would land elsewhere than in the full run and the ids could change on confirmation.
   - **B. As the full run (`snap_point`)**: the windows of about 160 m around each click (five
     rasters, some 4,000 cells each), 8 ms a point; the same cells, units and paths, so
     `build_network_tree` builds the same tree.
2. **The area of an element.**
   - **A. Its units; a unit split by a point goes whole to one element** (the unit-level
     approximation): an element made of a part of a split unit alone (two points in one unit)
     would have none, and A's area would hold the part of its unit below A.
   - **B. Its units, and in a split unit the accumulation at each point less the cells of the units
     above it** (the units drain into the head of the unit below, so everything above a point in
     its unit enters at the unit's head): exact to the cell, the full run's areas.
3. **The outlines.**
   - **A. `ST_Union` of each element's units of 1 ha**: tens of seconds for a large network.
   - **B. Vectorizing a raster of the elements**, as the full run: needs the window of A's
     catchment, which the design excludes.
   - **C. The units' polygons sent to the browser**: tens of megabytes for the whole area.
   - **D. A cover of A's catchment by the largest sub-catchment of any threshold that one element
     holds whole**, the units of 1 ha only around the outlets of the elements, united by element
     in PostGIS on a grid of 10 m. A coarser sub-catchment is found at the unit of 1 ha whose
     outlet cell it shares (the same flow distance and upstream area there) and taken when its
     units add up to its cells and belong to one element whole. The whole area: 91 polygons
     instead of 41,515, united in 0.17 s.
4. **The line of a reach.** The full run follows the D8 directions of its window. **The stream
   lines of the reach's units (`stream_network`), cut at the cells of its control points**: within
   1.2 m of the D8 path on production.
5. **Where the API puts it.** **`POST /api/delineate-network/preview`**: the request of the full
   run, a response of its own without the parameters and the hand-off.

## Decision

Option B of 1 and 2, D of 3 and the options in bold of 4 and 5:

1. **Two stages** in „Sieć zlewni”: a preview after every change of the points (added, removed,
   moved; not a renamed point), debounced in the browser; the full run on „Oblicz
   charakterystyki” (until now „Wyznacz sieć”). Only the full run gives the parameters of the
   elements and the hand-off; a change of the points makes its result stale, and the map and the
   panel show the preview of the new points until it runs again.
2. **The same composition.** The preview snaps with `snap_point` and builds the tree with
   `build_network_tree` (ADR-080, D2 to D5, D15): the ids, kinds and inflows of the elements, the
   places of the points and junctions, the mouth rule and the errors of the composition are the
   full run's. It reads no window of A's catchment, so it has no 422; it takes no lock (D13 stays
   the full run's) and its other failures are 500 `network_preview_failed`.
3. **Areas** exact to the cell (option 2B); a subcatchment above 250 km² is the notice
   `over_scs_cn_limit`, as in the full run.
4. **Reaches:** the difference of the flow distances of the ends (ADR-080, D10), equal to the full
   run's; the line from the stream lines, simplified at 1 m.
5. **Outlines** from the cover of option 3D, simplified, snapped and united on a grid of 10 m,
   without the slivers between the units. A unit split by a point goes whole to the element with
   most of its cells: the point is marked `inside_unit` and the elements with a part of such a unit
   `outline_approximate`, whose exact boundary comes with the characteristics.

## Consequences

- The preview gives the tree, the places, the areas and the reach lengths of the full run: equal
  on production's three networks of the plan (the Kamiennik, the Kaczawa node and the whole area,
  read only) and on the synthetic run of the tests, where a test compares them. Its outlines differ
  from the full run's coverage by the split units and the grid (intersection over union 0.93 to
  0.999 on production).
- Production, warm, over HTTP: the Kamiennik 0.08 s, the Kaczawa node 0.18 s, the whole area
  0.37 s (0.41 MB); the first request of a worker adds about 0.1 s (the match of the thresholds,
  computed once per loaded graph). The full run is unchanged.
- The preview reads the snapping windows, the graph, a few hundred polygons and the stream lines
  of the reaches; it holds no raster of A's catchment and runs while a full run holds its worker's
  lock.
- A graph without coarser thresholds draws every element from its units of 1 ha: correct, slower
  for large networks.
- The person sees where each point snapped and whether it moved to a mouth while placing it, and
  the hand-off is offered only for characteristics that answer the points on the map.
- `trace_main_channel` reads the upstream neighbours from the arrays of the sparse matrix instead
  of building a row matrix per step: the same choice, and the trunks of the whole area take 7 ms
  instead of 62 ms.
