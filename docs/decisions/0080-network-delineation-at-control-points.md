# ADR-080: A network of subcatchments, reaches and junctions delineated at control points

**Date:** 2026-11-10
**Status:** accepted (the author's decisions B1 to B7 of 2026-11-10; the details by delegation);
amended 2026-11-11 (the mouth rule at every junction; the preview of ADR-081; short and flat
reaches, D10a; two kinds of subcatchment for the person; the trunk of a branch; a node at a
confluence; every control point a node, named by where it lies); noted 2026-11-11 (the network
an option of „Wybierz zlewnię”)

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

> **Amended 2026-11-11 (the coordinator, after the author's report on kaczawa2; D10a):** a point
> 50.4 m above the confluence where another point's tributary joins made a reach of 50 m at the
> minimum slope (the NMT rose 400.11 → 400.58 m) and a przyrzecze of 0.0012 km², which Hydrolog's
> Muskingum-Cunge refuses at any time step (`unstable_timestep`: no division of the reach keeps its
> weights non-negative). The points still move only by the 50 m mouth rule; instead the preview
> and the full run give the notice `reach_short_or_flat` for every reach shorter than 200 m
> (`SHORT_REACH_M`) or of the minimum slope, the preview with the full run's slope (the NMT at
> the same end cells). A reach from a point into a confluence carries `move_to`, the outlet cell
> of the last unit above the confluence on its branch, and the map mode offers „Przesuń P… do
> zbiegu”: the point goes there, the preview runs again and the mouth rule takes it into the
> confluence without the reach. The hand-off keeps short reaches, but a reach of the minimum slope
> is written as `method: "lag"` with `lag_min` = max(1, round(length / 0.5 m/s / 60)), its
> length and slope in `node_provenance` with `method: "lag"` and `method_reason: "flat"`, since
> Muskingum-Cunge cannot route a flat reach. The notice `reach_slope_minimum` is replaced.

> **Amended 2026-11-11 (the author, after reviewing kaczawa2):** the headwater and the uppermost
> tributary meet in one junction, and which of them is the headwater follows the larger upstream
> area, often not the river the person expects; it changes nothing in the computation. The map,
> its legend, the tree, the (i) texts and the hand-off's Polish names therefore know two kinds,
> dopływ and przyrzecze: a headwater shows and is named as a dopływ („Dopływ do punktu P2”,
> „Dopływ powyżej J1”), and a confluence's description names its point too. A's catchment is
> marked only as a whole, its outline „Zlewnia A (całość)” and the area in the tree's row of its
> closing section. The kind `headwater` of the API and of `node_provenance` stays.

> **Amended 2026-11-11 (the coordinator, after the author's report on kaczawa2, „Z12 zostało
> oznaczone jako przyrzecze”):** the points whose paths enter a trunk through one unit form a
> branch, and the branch has a trunk of its own: its main river from that unit up, by the rule of
> every trunk (`trace_main_channel`, the larger upstream area at every confluence, ADR-046). Each
> point of the branch joins that trunk as a point joins its parent's trunk, at itself or at the
> confluence where its path enters it, and the points whose paths enter it through one unit form a
> branch of the branch. Before, such points met only where their paths merged (the plan's S2,
> decision 1: option A of decision 1 inside a branch), so the main river of a branch without a
> point at its mouth fell into the przyrzecze of its first reach, against B2. On the author's
> network (A at the confluence of the Nysa Szalona and the Kaczawa, nine points; the Kaczawa,
> 316.5 km² there, is the smaller branch, so it enters A's junction with no point at its mouth),
> P8 lay 5 m above the mouth of the Bukowica (19.58 km²) into the Kaczawa (50.94 km² above it),
> and its path met another point's only 1.84 km lower, at the mouth of the Świerzawa (P4): the
> reach R6 ran from P8 to that confluence with a przyrzecze of 52.29 km², the upper Kaczawa in
> it. Now the upper Kaczawa is the headwater of a junction at the Bukowica's mouth, which P8
> enters at its mouth (D3), and the reach from there runs down the Kaczawa to the Świerzawa's
> mouth with a przyrzecze of 1.36 km². Every reach runs down a main river: a river that joins it
> inside its przyrzecze drains no more than the river the reach brings to that confluence. The
> rule of the trunks is unchanged (it already took the larger upstream area), and the tree did
> not depend on the order of the points, before or after. A point with no point above it at the
> top of a branch's trunk is a tributary (it lies off its parent's trunk), and a confluence of the
> hand-off names it as it names the point of a headwater. The plan's D4 records the rule.

> **Amended 2026-11-11 (the coordinator, after the author's report on kaczawa2: a reach of 7 m from
> P1 to A at a confluence):** a point at most 50 m above a node whose cell is a confluence of the
> network (A, a control point with points above it, any junction) moves to the outlet cell of the
> last unit above that confluence on its own branch and enters the node directly, as a tributary
> does, also when no other point's path enters there: no reach is made. A control point's cell is
> such a confluence when a branch of points or a river joins its trunk there; a river is a stream of
> the request's `threshold_m2` (its upstream area reaches it). Every river without a point that
> joins at a junction's cell, beside the trunk and the branches of points, is a subcatchment of its
> own (kind `headwater`; „Dopływ do przekroju A” at A, „Dopływ powyżej J…” at another junction) that
> enters the junction, instead of falling into the przyrzecze of a reach; a smaller stream stays in
> the element its cells drain to. When the trunk enters a control point at its mouth, no przyrzecze
> ends at the point's cell, so its own cells (the cell, those draining into it from the side and the
> smaller streams joining there) go to the largest branch beside the trunk that ends in a river or
> in the przyrzecze of an edge, which then ends at that cell; without one they are an element of
> their own. On the author's network (A at the confluence of the Nysa Szalona and the Kaczawa, P1
> 7.1 m above A on the Nysa Szalona, A's trunk, no point on the Kaczawa; threshold 10 ha) the tree
> was Z1 „Dopływ do punktu P1” (430.72 km²), the reach R1 of 7.1 m from P1 to A and its przyrzecze
> Z2 of 316.55 km², the whole Kaczawa with A's own cells; it is now Z1 „Dopływ do ujścia przy P1”
> (430.72 km²) and Z2 „Dopływ do przekroju A” (316.55 km², the Kaczawa with A's own 14 cells), both
> entering J1 = A, no reach. The tree tests check on every network they build that each such river
> enters its junction alone. The plan's D3 and D5 record the rule.

> **Amended 2026-11-11 (the author, after the kaczawa2 network of A at the confluence of the Nysa
> Szalona and the Kaczawa with P1 7 m above A; plan `docs/plans/2026-11-11-network-nodes.md`, N1 to
> N8):** every control point is a node of the network, the closing section included, and a node's
> id says where it lies, not who placed it. A node of the network is a stream cell of the request's
> `threshold_m2` into which two or more such streams drain. After its snapping every control point
> moves to the nearest node along the stream within 50 m of flow distance, below it or above it
> (the head cell of its own unit), the nearer on both and the lower on a tie (`at_node`, which
> replaces `at_mouth`); this supersedes the mouth rule of decision 2 and its amendments above. A
> point at a node is that confluence, `J<n>`: every branch that joins there enters it, the main
> river first, a branch without a point as a headwater with no reach, a branch with points through
> its lowest node and a reach. A point elsewhere is `P<n>` and splits its river: the element above
> it enters it, and it enters the next node down by a reach with its przyrzecze. A junction the
> network makes where a point's path enters a trunk is a `J` too. The closing section alone is a
> network (`points` may be empty): one headwater per branch into its `J`, or one into its `P`. At
> a point at a node each branch's element ends at the outlet cell of its unit above the node, and
> the node's own cell and side cells belong to the element below it, so no unit is split by such a
> point; for the closing section at a node they lie outside the network, and B5 compares the
> elements with the sum of its branches (the cells of A at a confluence given to its largest
> branch, amended above, are superseded). Two points drawn to one node are refused
> (`network_points_coincide`, with a text saying that one point at a node already splits the
> catchment). The kind `tributary` goes: a subcatchment is a `headwater` („Dopływ”) or an
> `intermediate` („Przyrzecze”). The ids are the network's, numbered by a walk from the closing
> section upward (`J1` or `P1`), each kind on its own; the request's ids are the client's handles,
> `NetworkOutlet.id` has no default `A` and is required, and no handle reaches the hand-off, whose
> outlet is `O` (was `OUT`). On the author's network P1 is refused beside A; without it the closing
> section is `J1`, which the Nysa Szalona and the Kaczawa enter. The plan records the rules and
> amends D3, D4, D5, D11, D12, D14 and D15 of the plan `2026-11-10-network-delineation.md`.

> **Noted 2026-11-11 (the author):** „Sieć zlewni” is no longer a mode of its own on the mode bar
> but an option of the mode „Wybierz zlewnię”: while that mode is on, the radio group „Co
> wyznaczyć” over the map chooses „Jedna zlewnia” (the default) or „Sieć zlewni”, and the mode
> returns to the option chosen last in the page. The delineation, the preview of ADR-081, the
> panel and the hand-off do not change; where this ADR and ADR-081 say „the mode „Sieć zlewni””
> or „the map mode”, read this option.

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
   a unit boundary (*amended 2026-11-11:* the points whose paths enter it through one unit form a
   branch, which has a trunk of its own that they join in the same way, above). The nodes of a
   trunk bound its edges, and every edge is a reach with its przyrzecze; the trunk above its
   uppermost junction is a headwater subcatchment; a point with no point above it is a
   subcatchment (a tributary, or the headwater when it lies on its parent's trunk); a point off
   its parent's trunk at most 50 m above its junction is taken at its mouth and enters the
   junction directly (*amended 2026-11-11:* any point at most 50 m above a junction where its
   path meets another branch of the network, also above a control point at a confluence of the
   network, above). Every junction, every control point with points above it and A are
   junctions of the network; A's flows into the outlet (*amended 2026-11-11:* a river without a
   point that joins at a junction's cell enters it as a subcatchment of its own, above).
   (*Amended 2026-11-11, N1 to N4, N7, N8:* every control point is a node, drawn to a node of the
   network within 50 m below or above it; a node at a confluence is `J<n>`, any other `P<n>`; no
   subcatchment is a tributary; the ids are numbered from the closing section upward, and the
   closing section's node flows into the outlet `O`, above.)
3. **Cells.** An element holds the cells whose first element outlet downstream is its own: a
   control point's cell for the element that reaches it along its trunk (*amended 2026-11-11:*
   or, when the trunk enters it at its mouth, the largest branch beside the trunk that ends in a
   river or a przyrzecze, above), the outlet cell of the unit above a junction for an element
   that reaches the junction on a branch. A unit with a point inside is split by pyflwdir basins
   with an outlet at each of its points and at its outlet cell; any number of points per unit,
   two points on one cell refused (*amended 2026-11-11, N5:* a point at a node takes the place of
   the confluence, its own cell and side cells go to the element below it, and the closing
   section at a node leaves them out of the network, above).
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
   defect (500) (*amended 2026-11-11, N5:* for the closing section at a node, against the sum of
   its branches, above).
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
