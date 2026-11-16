# Plan: rivers that cross the edge of the data flow the way they are digitized

Approved: 2026-11-07 (by delegation of the author: the Nogat coordinator's assignment of
the Hydroni user report on the Noteć).

Requirements: the user report (the short stretch of the Noteć in the north of h07 flows the
opposite way; the Noteć flows west, towards Ujście and Czarnków); ADR-041 (smoothing),
ADR-071 (one fill of the whole grid); decision ADR-072. Scope: the preparation of the DEM
(`core/hydrology.py`, used by `process_dem` and its unit path alike); no API, database or
configuration change. Branch `fix/crossing-river-direction`.

## Findings

All on the published Hydroni run (`unit_runs/67d6842a…`, 5 m, 708 sheets, `main` burning,
code `3cd48a5`), read only; details and numbers in ADR-072.

- **The reversal.** The BDOT10k line of the Noteć runs 14.6 km inside h07, from
  (390,856, 581,622) to (378,236, 581,466) (EPSG:2180). 562 of 591 D8 samples along it
  point east (upstream), 7 west; the accumulation grows eastwards and the river leaves the
  data at its upstream end.
- **Causes.** (1) The smoothing chose one outlet per network, the line end at the raster
  frame with the lowest DEM value; every end at the frame of the Hydroni rectangle lies in
  nodata, so the first node won: for the Noteć network the entry of the Kanał Bydgoski in
  the north-east corner. (2) It walked the cells beside the burned ones (rounded pixel
  coordinates: 64.4% of its cells were burned cells). (3) A running minimum leaves flats,
  which the fill drains towards whichever outlet it reaches first. (4) A gap between two
  features ends a descent in a pit that can spill out at the upstream crossing (the Wełna).
  Not causes: the fill's outlets at the edge of the data and the burn depth.
- **BDOT10k direction.** Digitized downstream (94.6% of 1,505 features > 500 m with > 0.5 m
  relief; 98 of 99 features crossing MPHP catchments of their own river follow the
  catchment codes); errors are few but cluster (four lines in the county of Nakło rise
  ~10 m the digitized way). The MPHP identifier of a line carries no direction; the MPHP
  catchment codes do, but only inside the input's catchments.

## Method (for any watercourse that crosses the edge of the data)

1. Each burned line descends in its digitized direction; the DEM overrides it only where it
   rises by more than 2 m that way over at least 200 m (a line digitized upstream).
2. The lines are smoothed in the order of the flow (Kahn's algorithm over the nodes of
   their ends; a cycle is broken at its lowest-numbered line); a line starts below the
   lowest value of the lines ending at its first node.
3. Every cell with data ends strictly below the cell before it on its line (one float32
   step at least), so no flat is left on a burned line: the fill drains the river out of
   the data at its downstream crossing, and its upstream crossing drains into the data.
4. The cells of a line are those that contain its vertices: the burned cells.
5. A dead end inside the data is bridged to the nearest line within 50 m that begins where
   no line ends and does not lead back to it.
6. No outlet is chosen, no drain point is added at the downstream crossing and no edge cell
   is raised at the upstream one: with 1 and 3 the crossing cells already order the fill,
   and a drain point would leave the tie of a flat to pyflwdir's queue (ADR-072, options).
7. Inflow at the upstream crossing is not added (the area beyond the data is unknown to the
   pipeline and would change the accumulation of every product): a decision for the author.

## Steps

1. ✅ `core/hydrology.py`: `smooth_streams_monotonic` with `_line_nodes`, `_gap_joins`,
   `_rises_downstream`, `_flow_order`, `_descend_strictly`; `_rasterize_line_ordered` on
   the containing cells (`_cell_of`).
2. ✅ Tests (`tests/unit/test_monotonic_smoothing.py`): a river across a 5 m domain with the
   upstream edge 0.3 m lower or level, frame or nodata edges, the line a quarter or three
   quarters into its cells (8 cases), and split by a 15 m gap (4 cases). All 12 fail on
   `3cd48a5` (or with the gaps not bridged) and pass; the equivalence of the unit run and
   the whole raster (`test_unit_equivalence.py`) passes unchanged.
3. ✅ ADR-072, the amendment note of ADR-041, CHANGELOG, `backend/scripts/README.md`.
4. ✅ Verification on windows of the Hydroni sheets (below).
5. The full Hydroni area again: scheduled by the coordinator, not in this branch.

## Results (2026-11-07)

Windows cut from the instance's `dem_mosaic.vrt` with `gdal_translate -of VRT`,
`process_dem` (single raster, dry run, `main` burning, smoothing, no lakes, no catchments),
code `3cd48a5` and this branch, on the host; scratch on the NAS, removed afterwards. Peak
RSS 0.7–1.5 GB, 36–105 s per run.

| Window (EPSG:2180, km) | Cells | River (inside h07) | D8 samples with / against the flow, `3cd48a5` | this branch |
|---|---:|---|---|---|
| x 372.0–422.1, y 575.0–588.2 | 26.4 M | Noteć | 7 / 565 of 595 | 593 / 0 of 595 |
| x 400.0–416.0, y 524.0–541.0 | 10.9 M | Wełna from its entry to jez. Zioło | 0 / 504 of 512 | 512 / 0 of 512 |
| x 382.0–397.0, y 506.7–520.0 | 8.0 M | stream MPHP 1859232 at its exit | 163 / 0 of 164 | 164 / 0 of 164 |
| x 372.0–398.0, y 567.0–588.2 | 22.0 M | Noteć; streams of 1885222 'Dopływ z Wydartowa' | 578 / 1 of 595; 455 / 2 of 484 | 593 / 0; 481 / 0 |

The old code's outlet depends on the order of the lines in the domain: it oriented the
Noteć right in the 26 km window and wrong in the 50 km one, and the MPHP 1859232 stream
right in its window and wrong in the published run. In the north window the accumulation
at the western crossing of the Noteć is 124.7 km² (24.5 km² before), at the eastern one
12.3 km² (136.2 km²). The largest cut of the smoothing in the 26 km window fell from
57.5 m to 7.1 m.

**Crossings of the h07 boundary where the change matters.** The burned main lines cross
the boundary at 52 points (49 lines). The orientation of the smoothing changes at 12 of
them; the published D8 near the crossing runs against the corrected direction at five
rivers, which the full run will turn:

| River | Crossing (x, y) | Flows | Published D8 within 1 km inside h07, with / against |
|---|---|---|---|
| Noteć (188) | 390,856, 581,622 and 378,236, 581,466 | enters / leaves | 0 / 100 at the entry; the whole 14.6 km reversed |
| Wełna (186), at the Gnieźnieńska Struga | 408,381, 529,178 | enters | first 5 km inside drain back out (0 / 205 on its lines) |
| stream MPHP 1859232 (Główna basin) | 389,667, 512,872 | leaves | 0 / 118 |
| Dopływ z Wydartowa (MPHP 1885222, named Kcynka in BDOT10k), its last 310 m an unnamed river line | 395,369, 568,901 | leaves | 1 / 227 |
| Kcynka (18852) | 393,523, 568,705 | enters / leaves | 164 / 100 (partly reversed) |

At the other changed crossings the published D8 already runs the right way and only the
burned profile changes: the Kcynka at (391,465, 572,737), a line digitized upstream that
the old smoothing cut into a 10 m trench, and the Kcynka at (392,079, 570,856),
(391,501, 571,274) and (393,273, 569,045).

**Area-wide.** Inside h07 the published D8 runs mostly against the corrected direction on
110 of the 1,580 burned line pieces (80 km of 1,213 km); 105 of them (78 km) were smoothed
the other way by the old code: the Noteć (14.4 km), the stream of jez. Głębokie (MPHP
186656, 11.5 km), the Mała Wełna (7.9 km), the streams of 1885222 (8.4 km), the Wełna
(5.4 km), the Mielneńska Struga (4.5 km), the Kanał Wrończyński (4.3 km), the Ulga Druga
(3.5 km), the Sipiórka (3.1 km) and smaller ones. Of the 110, 19 (23.5 km) fall more than
0.5 m the new way, 80 (42.9 km) are flat within 0.5 m and 11 (13.9 km) rise 0.6–1.6 m the
new way, where BDOT10k decides.

## Open

- Inflow at the upstream crossings (method, point 7): the author's decision.
- Lines digitized upstream with less than 2 m of relief, gaps over 50 m and lines ending on
  the middle of another stay as described in ADR-072.
