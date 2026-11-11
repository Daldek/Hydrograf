# ADR-080: A network of subcatchments, reaches and junctions delineated at control points

**Date:** 2026-11-10
**Status:** accepted (the author's decisions B1 to B7 of 2026-11-10; the details by delegation);
amended 2026-11-11 (the mouth rule at every junction; the preview of ADR-081)

> **Amended 2026-11-11 (the coordinator, after the smoke S5):** the mouth rule of decision 2
> applies wherever the paths of two control points merge, at every junction, not only where a
> point enters its parent's trunk. A point at most 50 m above such a junction (its tributary's
> mouth, the merge of its path with another point's, the confluence below a gauge on the trunk)
> moves to the outlet cell of the last unit above the junction on its own branch and enters it
> directly; two points moved to one cell are refused. S5's network 2 had a reach of 34 m and a
> przyrzecze of 0.0004 km² where a point near its tributary's mouth met a gauge's path off A's
> trunk. The plan's D3 records the rule.

> **Amended 2026-11-11 (the author, ADR-081):** the map mode composes the network in a preview
> on the catchment graph (`POST /api/delineate-network/preview`: the snapping, the tree and the
> ids of this ADR, the areas and reach lengths of the units, outlines of their polygons) after
> every change of the points, and runs this delineation on „Oblicz charakterystyki” (formerly
> „Wyznacz sieć”); only its result gives the parameters and the hand-off (decision 8), and a
> change of the points makes it stale.

## Context

On 2026-11-10 the author decided that Hydrograf delineates a network for Hydrolog's „Sieć i
trasowanie” (plan `docs/plans/2026-11-10-network-delineation.md`, which records B1 to B7). The
person clicks the closing section A and points on tributaries and on the rivers (gauges); the
flow paths from the points to A form a tree joined at confluences (B1). The elements are those
of HEC-HMS: a tributary's catchment to its mouth, the main river above the first junction as a
headwater subcatchment, a reach between junctions and, for each reach, its intermediate
catchment (przyrzecze), the area draining to it without the catchments of the points, which
enters the junction below it unrouted (B2). A point inside a unit is split by the raster at
once; confluences are unit boundaries of the catchment graph (B3). Every subcatchment and
przyrzecze gets the parameters of a delineation; a reach gets the difference of the flow
distances of its ends as its length, the NMT elevations of its ends for its slope and the length
of the vector line as a check, and its section stays Hydrolog's (B4). The areas sum to A's (B5).
`POST /api/delineate-network`, a map mode and one hand-off of the whole network (B6) carry the
origin of every node, which Nogat adds to `nogat-handoff/1` first (B7; Nogat plan
`docs/plans/2026-11-10-node-provenance-in-handoff.md`, `e133635`).

What the construction can build on:

- The catchment graph (ADR-021) holds, per threshold, one sub-catchment per stream segment,
  each draining into one below. Segments end at every confluence and at every change of
  Strahler order (`core/stream_extraction.py::vectorize_streams`), so a sub-catchment drains
  into the head cell of the one below, and every confluence of a threshold's network is a
  boundary of its sub-catchments. The units below are the sub-catchments of 1 ha
  (`DEFAULT_THRESHOLD_M2`); a confluence of any coarser network is one of theirs.
- A delineation merges whole sub-catchments (precomputed) or takes the cells draining to the
  clicked cell in a window of the saved rasters (precise, ADR-050), with its statistics from the
  graph for the whole sub-catchment of the click (ADR-054, Consequences): the unit of a point
  would be counted in two elements.
- `scripts/export_catchment_parameters.py` measures the panel's parameters from the cells of a
  polygon on the saved rasters, and its test finds them equal to the panel's for every
  whole-unit watershed of a synthetic run
  (`test_a_delineated_watershed_gets_the_values_of_the_panel`).
- `hydrolog-network/1` carries subcatchments, reaches (Muskingum–Cunge needs `length_km` and
  `slope_m_per_m`; its section is optional in the schema and needed to route), junctions with
  any number of inflows and one outlet with one inflow.
- The API runs two workers within 8 GB; nginx gives a request 120 s, Cloudflare's proxy 100 s.
  Measured on 2026-11-10 on production's rasters (read only, a window of 24.0 M cells): the six
  rasters a network reads take 3.2 s and 22 bytes a cell (888 MB resident with the
  interpreter); `zonal_summary` by 39 elements 0.21 s; the flow paths of 40 elements 0.88 s;
  the 40 vectorized elements noded into a valid coverage 2.3 s, simplified as a coverage at 5 m
  in 0.34 s (148,181 to 44,775 vertices, still valid). Production's grid has 58.6 M cells.

## Options considered

1. **How the tree gets its junctions.**
   - **A. The flow paths of the points alone**, junctions where two of them merge. With points at
     tributary mouths the first merge lies on the main river below both mouths: the main river
     above the first tributary carries no path, so the headwater, often most of the area, falls
     into the przyrzecze of the first reach and enters its junction unrouted, against B2.
   - **B. Every confluence of the stream network a junction** (HEC-GeoHMS's split at a
     threshold): hundreds of elements at 1 ha, most of them not clicked; B2 lists the clicked
     tributaries only.
   - **C. The main river of each control point (the rule of ADR-046) takes a junction where the
     path of each point above it joins it.** HEC-HMS's layout for points at tributary mouths, the
     same layout nested for points above points, and no river names needed.
2. **Where a clicked point lies.** As clicked (the precise mode): a click beside the channel
   delineates a few cells of hillside. The cell of the largest accumulation within a radius
   (StreamStats' rule): it moves a point at a tributary's mouth onto the main river. **The
   nearest stream cell of the network drawn on the map, within 100 m**, with a point at most
   50 m above its tributary's mouth taken at the mouth, so a click at a mouth delineates the
   tributary to its mouth (B2) and brings no reach of a few metres.
3. **How an element is measured.**
   - **A. The panel's graph path per element**, with pseudo-units for the parts of split units:
     every function keyed by `segment_idx` (the stream lines, the outlet, the label raster of the
     flow paths) would have to know them.
   - **B. A precise delineation per element:** a window read per element, and the unit of a
     point counted in two elements.
   - **C. One window over A's catchment; whole units assigned to elements from the graph, the
     units of points split by pyflwdir (B3); every element measured from its cells by the
     export's measures, moved into `core/`.** Exact for split units, equal to the panel for whole
     units, one implementation and one read.
4. **Boundaries.** Each element smoothed as the precise mode smooths its polygon (Chaikin) leaves
   gaps and overlaps along the shared edges. **The vectorized elements noded into one coverage
   and simplified as a coverage at 5 m.**
5. **The slope of a reach.** The filled DEM carries the 2 m of the burning and the strict descent
   of ADR-072 and ADR-077 on burned lines only, so a reach with one burned end gets 2 m too much
   or too little. A regression along the reach is not B4. **The NMT at the two ends**, with a
   floor of 0.1 ‰ where it does not fall, since Hydrolog refuses a slope that is not positive.
6. **The check length.** A merged BDOT10k line rarely spans a reach (the lines split at every
   tributary); the lines inside a corridor count the tributaries that cross it. **Samples every
   10 m along the reach, each on its nearest BDOT10k line within 25 m.**
7. **Where the API puts it.** A third mode of `POST /api/delineate-watershed` (ADR-050): its
   request and response are one watershed's. **A route of its own,
   `POST /api/delineate-network`** (B6).

## Decision

Option C of 1 and 3 and the options in bold of 2 and 4 to 7:

1. **Units and snapping.** The elements are made of units (1 ha). Each point, A included, moves
   to the nearest cell within 100 m whose accumulation reaches the request's `threshold_m2` (the
   network drawn on the map, at least 10,000 m²).
2. **The tree.** A point's parent is the first control point on its flow path downstream (A at
   the latest). The trunk of a control point is its main river (ADR-046). A point joins its
   parent's trunk at itself when it lies on it, else at the confluence where its path enters it,
   a unit boundary. The nodes of a trunk bound its edges, and every edge is a reach with its
   przyrzecze; the trunk above its uppermost junction is a headwater subcatchment; a point with
   no point above it is a subcatchment (a tributary, or the headwater when it lies on its
   parent's trunk); a point off its parent's trunk at most 50 m above its junction is taken at
   its mouth and enters the junction directly (*amended 2026-11-11:* any point at most 50 m above
   a junction where its path meets another branch of the network, above). Every junction, every
   control point with points above it and A are junctions of the network; A's flows into the
   outlet.
3. **Cells.** An element holds the cells whose first element outlet downstream is its own: a
   control point's cell for the element that reaches it along its trunk, the outlet cell of the
   unit above a junction for an element that reaches the junction on a branch. A unit with a
   point inside is split by pyflwdir basins with an outlet at each of its points and at its
   outlet cell; any number of points per unit, two points on one cell refused.
4. **One window** of the six saved rasters over A's catchment, at most 60 M cells; the element
   raster from the labels through a table unit → element. No flow directions are computed.
5. **Measures.** Every element from its cells with the export's measures, moved into
   `core/cell_parameters.py`: the panel's parameters (a `WatershedResponse`) at 1 ha, as the
   precise mode takes them, the areas exact to the cell. The boundaries are one coverage
   simplified at 5 m.
6. **Reaches.** The length is the difference of the flow distances of the ends (the graph's
   `outlet_flow_dist_m` at junctions, the same raster at points); the slope comes from the NMT
   at the ends, 0.0001 where it is not positive; the BDOT10k check length by sampling; no
   section.
7. **B5** is compared in cells against the graph's units of A's catchment; a difference is a
   defect (500).
8. **The hand-off** is one `nogat-handoff/1` around one `hydrolog-network/1` of subcatchments
   (the `curve-number` runoff with Hydrolog's defaults), Muskingum–Cunge reaches without a
   section, junctions and the outlet; no rainfall, time step or result; `node_provenance` for
   every subcatchment, reach and junction.
9. **One network at a time per worker**; a second request waits 15 s, then gets 503.

## Consequences

- The API reads the saved rasters of A's whole catchment for a network, as the precise mode does
  for one watershed (ADR-050), and runs pyflwdir only on the units of the points: about 2 GB at
  the cap of 60 M cells, at most two networks at once with two workers. A network whose window
  exceeds 60 M cells is refused (422): production's whole Kaczawa (58.6 M) fits, the largest
  rivers of Hydroni's h07 do not.
- An element has the parameters of the precise mode at 1 ha, not those of the precomputed mode
  at the threshold of its cascade, so an element and the same watershed delineated in the
  precomputed mode may differ as the two modes differ today. The export and the network share
  the measures, and the export's test keeps them equal to the panel's.
- The boundaries tile A without gaps or overlaps. Simplified at 5 m without the Chaikin
  smoothing of the panel, a perimeter is a few per cent longer than a smoothed one.
- The 250 km² of SCS-CN apply to each subcatchment: an element above it is flagged, the network
  is not refused.
- Hydrolog opens the reaches incomplete until the person gives their sections, and the network
  without rainfall until the person sets it (Hydrolog plan `2026-11-10-network-wizard`, A2).
- The hand-off needs Nogat's `node_provenance` (a new copy of the envelope) and a Hydrolog pin
  whose schema has `description` (Hydrolog `46c743f` or later).
- Points snap to the network drawn on the map, so a point at a confluence can land on the other
  branch: the map shows where each point went, and the person moves it.
