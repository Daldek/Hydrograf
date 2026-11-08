# ADR-072: The stream smoothing follows the digitized direction and descends strictly

**Date:** 2026-11-07
**Status:** accepted (by delegation of the author, 2026-11-07; plan
`docs/plans/2026-11-07-crossing-river-direction.md`); amends ADR-041

## Context

A user of the Hydroni instance reported that the short stretch of the Noteć in the north of
the area h07 flows the wrong way: the Noteć flows west, towards Ujście and Czarnków. In the
published run (5 m, 708 sheets, `main` burning, ADR-071) the BDOT10k line of the Noteć runs
14.6 km inside h07, entering at (390,856, 581,622) and leaving at (378,236, 581,466)
(EPSG:2180). Of 591 samples of the D8 directions every 25 m along it, 562 point upstream
(east), 7 downstream; the flow accumulation grows eastwards and the river leaves the data
at its upstream end.

The smoothing of ADR-041 (`smooth_streams_monotonic`) orients every burned line from one
outlet per connected component of the line network: the line end at the frame of the
raster with the lowest DEM value, read at the end's cell clamped into the frame. Four
defects compound:

1. **The outlet is a tie of nodata.** The Hydroni grid is the rectangle around 708 sheets;
   every line end at its frame lies in nodata, so all candidates read -9999 and the first
   node of the component wins. For the Noteć network (639 lines, 508 km, nine ends at the
   frame) that is the first point of the Kanał Bydgoski at (422,899, 587,328), where water
   enters the data. The running minimum then pushed the network towards it; the Noteć
   became a flat at the lowest value of its western reach (46.48 m in the filled DEM) and
   drained east. The outlets of 42 of the 72 components of the main lines sat on nodata
   cells; 557 of 3,201 lines (364 of 2,224 km, 16%) were smoothed against their direction
   of flow as this ADR takes it, among them the lower Wełna network (oriented towards the
   point where the Ryga enters at the west edge). Which node wins depends on the order of
   the lines in the domain: in a 26 km window around the Noteć the same code happened to
   orient it right.
2. **The smoothing walked beside the burned cells.** `_rasterize_line_ordered` rounded pixel
   coordinates, whose integers are cell corners, so a vertex went to the next cell in half
   of the cases: of the 397,677 cells the smoothing walked on the Hydroni main lines only
   64.4% were burned cells (94.4% with the cell that contains the vertex). On the other
   cells it lowered the banks and left the burned channel as burned.
3. **A running minimum leaves flats.** Even oriented right, a channel whose upstream
   crossing is as low as the rest becomes one flat from one edge of the data to the other.
   pyflwdir's fill (`outlets="edge"`) queues cells by (float32 elevation, boundary flag,
   row, column) and drains a flat towards the cell it takes first: on a synthetic valley
   with the upstream edge 0.3 m lower, or level, the oriented but non-strict smoothing
   drained 98 of 99 channel cells upstream.
4. **A gap between two features ends the descent in a pit.** Where BDOT10k leaves a gap
   between two features of a watercourse (the Wełna 5 km after it enters h07: 20 m), the
   next feature starts at its own level; the descent before the gap ends in a pit, which
   the fill raises until it spills, here out at the upstream crossing: in the published
   run the first 5 km of the Wełna inside h07 drain south out of the area, and they still
   did with only the three fixes above on a window of the sheets.

Not causes: the fill takes every cell at the edge of the data as an outlet, and a channel
that descends strictly drains its upstream crossing into the data; the uniform burn depth
(2 m) orients nothing.

BDOT10k digitizes a watercourse downstream: 1,424 of 1,505 features longer than 500 m
whose ends differ by more than 0.5 m in the DEM start higher (94.6%; 96.4% of the main
lines at 1 m); 98 of the 99 features whose ends lie in two MPHP catchments of their own
river follow the downstream order of the catchment codes; 51 of the 2,751 nodes of the main
network that join two lines join two inflows or two outflows (1.9%). The errors cluster:
four lines in the county of Nakło (TERYT 0410), the Kcynka among them, 2.3 to 6.9 km long,
rise 9.7 to 10.9 m the way they are digitized. The MPHP identifier of a line
(`IDENTYFIKATORMPHP`, 188 on every feature of the Noteć) names the river and carries no
direction; the MPHP catchment codes do order a river's catchments downstream (the Polish
codes number from the source: 188519 'Noteć od dopł. z Kaźmierzewa do Kcynki' lies
upstream of 188531 'Noteć od Kcynki do Młynówki Borowskiej'), but only for catchments in
the input, and the catchment beyond a crossing is not.

## Options considered

The direction of a burned river:

- **One outlet per component from the DEM** (ADR-041 as implemented), with nodata left
  out of the choice: rejected. On a flat valley the two crossings of the Noteć differ by
  centimetres of water-surface noise, and a component can have several exits (two rivers
  joined by a canal) and loops.
- **The digitized exit as the outlet** (a line end at the edge that ends a line), the lines
  oriented by their distance from it: rejected. It fixes the Noteć, but orients loops and
  networks with several exits by counts of nodes, not by flow.
- **Each line in its digitized direction, in the order of the flow; the DEM overrides only
  a clear contradiction**: chosen.
- **The MPHP catchment codes**: rejected as the rule. They need the catchments, which a
  single-raster run does not have, and say nothing beyond the area's own catchments, that
  is at the crossings; used as a check of BDOT10k above.

Keeping the fill from draining a river out at its upstream crossing:

- **A drain point at the downstream crossing and raised edge cells at the upstream one**:
  rejected. A drain point (as for the endorheic lakes) makes its neighbours edge cells at
  their own elevations, so a flat that reaches both crossings is still split by pyflwdir's
  queue order; raising the upstream crossing needs the crossings of every line with the
  edge of the data found and treats only the flats that reach them.
- **A strictly descending profile along every burned line**: chosen. It removes every flat
  of the burned lines, at the crossings and inside the data, without finding crossings.
- For gaps between features: a wider snapping of every line end (it would merge the ends
  of different streams at confluences: rejected); splitting lines where another line ends
  on their middle (15 cases on the Hydroni main lines: not worth the machinery now);
  bridging only a dead end to a nearby line that begins where nothing ends: chosen (9
  gaps of 11 to 45 m on the Hydroni main lines).

Inflow at the upstream crossing (the area of the river beyond the data added at the cell
where it enters): not adopted. The pipeline does not know that area (it would need the MPHP
catchments beyond the area), and the accumulation drives the stream thresholds, the
Strahler orders and the sub-catchments of every product; a decision of its own.

## Decision

`core.hydrology.smooth_streams_monotonic`:

- The direction of a line is the one it is digitized in. A line is taken the other way when
  the lowest DEM value of its last quarter exceeds the lowest of its first quarter by more
  than `REVERSED_LINE_RISE_M` (2 m) on a profile of at least `REVERSED_LINE_MIN_LENGTH_M`
  (200 m), whose quarters are longer than an embankment (`_rises_downstream`). No outlet is
  chosen.
- The lines are taken in the order of the flow: Kahn's algorithm over the nodes joining
  their ends (`_line_nodes`, `_flow_order`); a directed cycle, which has no such order, is
  taken from its lowest-numbered line. A line begins below the lowest value that the lines
  ending at its first node reached.
- A line that ends inside the data where no line goes on (a dead end) continues into the
  nearest line within `LINE_GAP_M` (50 m) that begins where no line ends and does not lead
  back to it (`_gap_joins`); the cells between them are smoothed as a line of their own.
  A stream that ends without such a line stays a dead end. A line that ends on the middle
  of another (15 of the 6,584 line ends of the Hydroni main lines) is not joined.
- Along a line every cell with data ends strictly below the cell before it
  (`_descend_strictly`): a cell higher than the lowest value before it is cut to just below
  the cell before it (a bridge, an embankment); a cell not below the cell before it is
  lowered by one float32 step, the resolution at which pyflwdir queues elevations.
- The cells of a line are those that contain its vertices, joined by Bresenham
  (`_rasterize_line_ordered`, `_cell_of`): the cells the burning lowers.

Unchanged: the burning (`dem.stream_burning`, 2 m), the fill with outlets at the edge of the
data, the lake drain points, the one fill of ADR-071. `--no-smooth-streams` still leaves the
burned channel without a direction.

## Consequences

- A river that crosses the edge of the data leaves it at its downstream crossing, whatever
  the elevations at the two crossings and whatever the domain: the area, the sheets, a
  window. On a window of the Hydroni sheets (x 372.0–422.1 km, y 575.0–588.2 km,
  26.4 M cells, `main` burning) the code before this ADR sent 565 of 595 samples of the
  Noteć inside h07 upstream; with this ADR 593 point downstream and none upstream, and the
  accumulation at the western crossing is 124.7 km² instead of 24.5 km².
- No trench from a line smoothed against its flow: the largest correction of the smoothing
  on a 26 km window around the Noteć fell from 57.5 m to 7.1 m, the mean from 7.9 m to
  0.5 m.
- A line digitized upstream along which the DEM rises by less than 2 m keeps the wrong
  direction: the smoothing cuts it by up to that rise and the fill decides its flow. Of the
  110 burned lines of h07 whose published directions run against the new ones, 11 (14 km)
  rise 0.6 to 1.6 m the new way; BDOT10k decides there. The lowering of the strict steps
  is negligible: one float32 step is 3.8 µm at 50 m.
- A loop has no flow order; it is broken at its lowest-numbered line. A gap of more than
  50 m (a lake between two features is bridged by its burned surface) or a line ending on
  the middle of another still ends a descent in a pit, which the fill raises.
- The published Hydroni run changes: the full area must be processed again. The run by
  units and the run of the whole raster stay equal (the same function on the same prepared
  DEM). The diagnostics of the smoothing gain `segments_reversed`,
  `segments_out_of_order`, `gaps_bridged` and `cells_stepped`, lose
  `disconnected_components`; `cells_smoothed` counts the cut cells only.
