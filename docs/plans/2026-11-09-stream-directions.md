# Plan: a burned line flows the way of its watercourse

Approved: 2026-11-09 (by delegation of the author: the Nogat coordinator's assignment of
the author's recommendations of 2026-11-09; the guard of rule 2 decided by the
coordinator the same day).

Requirements: ADR-072 (the smoothing of the burned lines), the author's review of the map
of the h07 network (2026-11-09), decision ADR-077. Scope: the direction of the burned
lines in `core/hydrology.py` (`smooth_streams_monotonic` and the loading of the burned
lines), its unit tests and the diagnostic `scripts/check_stream_directions.py`; no API,
database or configuration change. Branch `feat/stream-directions`: ADR-077, this plan and
the diagnostic first; the change of `core/hydrology.py` follows on it.

## Findings

All on h07 (5 m NMT, `main` burning, 3,884 burned pieces, 1,445.1 km); details in
ADR-077.

- ADR-072 reverses 10 lines (20.0 km). The analysis of the whole network (now the
  diagnostic) reverses 70 (40.6 km), the 10 among them, and sets apart 8 connectors
  through lakes (2.9 km); the mouth test confirms the 49 of the 70 it can check,
  contradicts none and finds 18 more (9.7 km). The author: right, except the connectors
  through lakes and the networks detached from the main watercourses.
- The rules of ADR-077 on the lines and nodes of the diagnostic (the vector reference,
  computed with its functions on the burned pieces only, ends joined within 0.5 m, the DEM
  every 5 m):

  | Rule | Decides (lines, km) | Reverses (lines, km) |
  |---|---:|---:|
  | 1 mouth | 2,600 / 943.6 | 73 / 44.2 |
  | 2 DEM of the watercourse (23 watercourses digitized both ways) | 247 / 118.3 | 23 / 9.6 |
  | 3 DEM of the line (ADR-072) | 0 | 0 |
  | 4 digitized | 1,037 / 383.2 | 0 |
  | all | 3,884 / 1,445.1 | 96 / 53.7 |

  69 of the 70 lines of the verdict are reversed (40.3 km); 27 more (13.4 km): the 18 of the
  mouth test, the 8 connectors, one line of MPHP 188522 (0.8 km). The guard of rule 2 keeps
  one block: line 7547 of MPHP 186656 (1.63 km, falls 4.35 m the way it is digitized). The
  mouth test of the diagnostic contradicts no line. The Noteć (MPHP 188, 25 lines,
  18.2 km): none reversed, it flows west. With the ends joined within 7.5 m (closer to the
  cells of the smoothing) the mouth reverses 74 lines (46.1 km) and contradicts the mouth
  test on one line of a few metres.

## The diagnostic (done)

`backend/scripts/check_stream_directions.py` (`--hydro`, `--dem`, `--area GPKG[:layer]`,
`--catchments GPKG[:layer]`, `--burning main|all`, `--out`): the throwaway analysis and its
mouth test as functions (`split_at_t_junctions`, `join_ends`, `node_kinds`,
`sample_profiles`, `line_relief`, `dem_classes`, `catchment_order`, `conflict_runs`,
`trace_watercourses`, `orient_watercourses`, `verdicts`, `mouth_test`, `strahler_orders`,
`categories`, `analyze`). Layers `odcinki`, `wezly`, `cieki` with the Polish columns of
the throwaway, plus `wypalany` (burned with `--burning`), `test_ujscia` and `kategoria`.
On h07 (`main`) it gives the throwaway's three layers column by column (23,266 pieces,
24,868 nodes, 283 watercourses) in 49 s. 20 unit tests on synthetic networks
(`tests/unit/test_check_stream_directions.py`).

## Algorithm for `core/hydrology.py`

### 1. The burned lines with their attributes

`_load_stream_geometries` drops the attributes. New:

```python
# The attributes of a burned feature that the direction of a line reads (ADR-077)
STREAM_ATTRIBUTES = ("IDENTYFIKATORMPHP", "NAZWA", "CECHAGEOMETRII")


def _load_stream_features(
    streams_path: str | Path,
    transform: Affine,
    dem_shape: tuple[int, int],
    stream_burning: str = "all",
) -> gpd.GeoDataFrame: ...
```

- The reading, the check of `stream_burning`, the selection (`_select_burned_features`),
  the reprojection to EPSG:2180 and the filter by the DEM extent of today's
  `_load_stream_geometries`, in the same order: layer by layer, feature by feature, part
  by part. One row per LineString part (two or more coordinates), per polygon and per
  other geometry, as the list is today.
- Columns: `geometry` and `STREAM_ATTRIBUTES` as stripped text, `''` where the value or
  the column is missing (OT_SWRM_L has neither `IDENTYFIKATORMPHP` nor
  `CECHAGEOMETRII`); the parts of a MultiLineString keep the attributes of their feature.
  CRS EPSG:2180; an empty frame with these columns when nothing is selected.
- `_load_stream_geometries(...)` becomes `list(_load_stream_features(...).geometry)`: the
  burning gets the same list as today.

### 2. The direction of each line

```python
# Below this rise or fall between the quarters the DEM along a watercourse is flat
WATERCOURSE_RISE_M = 0.5
# CECHAGEOMETRII of an artificial connector, a line drawn through a lake
CONNECTOR = "sztuczny łącznik"


def _line_directions(
    ends: dict[int, tuple[int, int]],
    values: dict[int, np.ndarray],
    lengths_m: dict[int, float],
    mphp: Sequence[str],
    names: Sequence[str],
    connector: Sequence[bool],
    spacing_m: float,
) -> tuple[dict[int, tuple[bool, str]], list[list[int]]]: ...
```

Pure (no raster), so the diagnostic can call it with its own nodes and samples.
`ends`: `{line: (node of its first point, node of its last point)}` as digitized
(`_line_nodes`); `values`: the DEM values of the line's cells with data in the digitized
order (what `_rises_downstream` reads today); `lengths_m`: the length of each geometry;
`mphp`, `names`, `connector` by line index; `spacing_m`: the cell size. Returns, for every
line of `ends` whose two nodes differ, `(reversed, rule)` with rule `"mouth"`,
`"watercourse"`, `"rise"` or `"digitized"`, and the blocks kept by the guard of rule 2,
each as its lines (the smoothing counts them, the diagnostic marks their lines). The lines
whose two nodes are one are not returned (the smoothing skips them).

Helper: `_quarter_rise(values, spacing_m) -> float | None`: `None` when
`values.size < 2` or `values.size * spacing_m < REVERSED_LINE_MIN_LENGTH_M`, else the
lowest value of the last quarter less the lowest of the first (`quarter =
max(values.size // 4, 1)`). `_rises_downstream` becomes `rise is not None and rise >
REVERSED_LINE_RISE_M`, the same answers as today.

**Rule 1, the mouth** (`_mouth_directions(lines, ends, mphp, lengths_m) -> dict[int,
bool]`, `lines` the sorted lines whose nodes differ):

1. `codes_at[node]`: the non-empty MPHP identifiers of every line of `ends` at its two
   nodes.
2. For each identifier K: the undirected graph of K's lines (weight: the length);
   the mouths are its nodes where some `c` of `codes_at[node]` has `c != K` and
   `K.startswith(c)` (the receiver; a tributary, whose code K is a prefix of, is not).
   No mouth: K is not decided.
3. Distances from all mouths at once (Dijkstra, `heapq`). A line of K whose two nodes are
   reached at different distances is decided: reversed when its first node is the nearer.
   A line not reached, or with its nodes as far, is not.

**Rule 2, the DEM of the watercourse** (`_watercourse_directions(lines, ends, mphp,
names, values, connector, spacing_m) -> tuple[dict[int, bool], list[list[int]]]`, the
second item the blocks kept by the guard, each as its lines):

1. The key of a line: `M:<mphp>`, else `N:<name>`, else none (no rule 2).
2. A node joins two lines of one key when exactly two lines of that key have an end at
   it. Walk each chain, the lines in index order: from a line not yet walked go back
   through the joins to a free end (or round the loop until a line repeats), then forward
   to the other free end, recording for each line whether it is digitized the way of the
   walk (`forward`).
3. A chain whose lines are all `forward` or all not is not decided. Otherwise its profile
   is the concatenation, in the walk order, of `values[line]` (reversed for a line that
   is not `forward`), connectors left out; `rise = _quarter_rise(profile, spacing_m)`.
   With `rise` None or `abs(rise) <= WATERCOURSE_RISE_M` the chain is not decided; else
   the walk runs downstream when `rise < 0`.
4. The blocks: maximal runs of consecutive lines of the walk with the same `forward`. A
   block digitized downstream: its lines are decided, not reversed. A block digitized
   upstream: its own profile is the concatenation of `values[line]` of its non-connector
   lines in the block's digitized order (the walk order for a `forward` block, else the
   reversed walk order, each line in its digitized order); when `_quarter_rise` of it is
   below `-REVERSED_LINE_RISE_M` (it falls more than 2 m the way it is digitized) the
   block is not decided and counts as kept by the guard; else its lines are decided,
   reversed. Connectors take the decision of their block.

**Rules 3 and 4**: a line that rules 1 and 2 leave, not a connector, is reversed when
`_quarter_rise(values[line], spacing_m) > REVERSED_LINE_RISE_M` (rule `"rise"`); every
other line keeps its direction (`"digitized"`). A line decided by rule 1 keeps that
decision whatever rule 2 says of its chain.

### 3. In `smooth_streams_monotonic`

1. `features = _load_stream_features(...)`; the LineString rows in their order give
   `geoms` and the lists `mphp`, `names` and `connector` (`CECHAGEOMETRII == CONNECTOR`).
2. `ends, node_cells = _line_nodes(geoms, transform)` as today. The first loop computes
   the cells of every line in the digitized order and `values[line] = vals[vals !=
   nodata]`, without reversing anything.
3. `directions, kept = _line_directions(ends, values, {line: geoms[line].length for line
   in ends}, mphp, names, connector, cellsize_m)`; each reversed line gets its cells
   reversed and `ends[line] = (last, first)`. Then the bridges of the gaps, the flow order
   and the strict descent as today.
4. It returns `(smoothed, flow_lines, diag)`: `flow_lines` are the burned LineStrings in
   their order, each in the direction of its flow (reversed where a rule reverses it).

The lines are the burned ones of `stream_burning`: with `main` a mouth is found only where
the receiver is burned, which the selection guarantees for the MPHP watercourses and the
rivers.

The classification of the lakes takes the burned lines in those directions (the open
point, decided by the coordinator on 2026-11-09): `classify_endorheic_lakes(...,
flow_lines=None)` looks each of its lines up among `flow_lines` by the normalized geometry
(`shapely.normalize(line).wkb`; both read the same file the same way) and takes the
direction of the burned line it finds; any other line keeps `_in_flow_order`, the
per-line rule of ADR-072 on the DEM it is given. `process_dem` and `process_dem_units`
pass the lines of the smoothing; without the smoothing (`--no-smooth-streams`) every line
keeps `_in_flow_order`.

### 4. Diagnostics of the smoothing

Kept: `segments_reversed` (every line taken against its digitized direction, now by any
rule). New: `segments_by_mouth`, `segments_by_watercourse` (lines decided by rules 1 and
2, reversed or not); `segments_reversed_by_mouth`, `segments_reversed_by_watercourse`,
`segments_reversed_by_rise` (their sum is `segments_reversed`); `blocks_kept_by_fall`
(the guard); `connectors` (artificial connectors among the lines). The log line of the
smoothing names the reversals by rule. The classification of the lakes adds
`streams_burned` (the lines near the lakes that take the direction of `flow_lines`).

## Tests to write

In `tests/unit/test_monotonic_smoothing.py`, through a helper that builds the frame of
`_load_stream_features` from LineStrings and attributes (blank by default):

1. **A block digitized upstream inside a watercourse**: three lines of one name in a row
   on a DEM falling 2–3 m along them, the middle one digitized against the others and
   rising less than 2 m along its digitizing: `segments_reversed_by_watercourse == 1` and
   the smoothed cells descend strictly over all three lines. Fails today (ADR-072 keeps
   the middle line).
2. **A connector through a flat lake**: (a) the middle line of a watercourse, a
   connector digitized against the rest, its cells flat: reversed by rule 2;
   (b) a connector digitized with its watercourse whose cells rise more than 2 m the way it
   is digitized: not reversed (`segments_reversed == 0`; today ADR-072 reverses it).
3. **A flat watercourse with its mouth**: a flat DEM, MPHP `18852` in two lines, one
   digitized away from a line of `188` at its end: `segments_reversed_by_mouth == 1`; with
   the receiver coded `189` (no prefix) or a tributary coded `188521`: not reversed.
4. **Nothing changes when all lines agree**: a branched network digitized downstream with
   MPHP identifiers and names gives the same smoothed DEM as without attributes and
   `segments_reversed == 0`. The existing tests patch `_load_stream_features` instead of
   `_load_stream_geometries` with blank attributes and keep their assertions.
5. **The guard**: a watercourse falling one way overall whose block from a divide falls
   more than 2 m the way it is digitized: `blocks_kept_by_fall == 1`, nothing reversed.
6. `_line_directions` alone (pure): rule 1 before rule 2 when they disagree; two mouths,
   each line to the nearer; a line with its nodes as far from the mouth is left to the
   other rules; a loop of one key is walked once.
7. `_load_stream_features` on the GeoPackage of `test_stream_burning.py`: stripped
   attributes, `''` for OT_SWRM_L, the parts of a MultiLineString with the attributes of
   their feature; `test_stream_burning.py`, `test_lake_drain.py` and
   `test_unit_equivalence.py` pass unchanged.
8. **The lakes take the directions of the smoothing** (`tests/unit/test_lake_drain.py`):
   a burned line given in `flow_lines` flows that way whatever its own DEM says; a
   watercourse through a lake whose outflow is digitized towards the lake, rising 0.7 m
   along it, is smoothed out of the lake by rule 2 and the lake is exorheic.

## Acceptance on h07

1. The tests above and the existing tests of the smoothing, the burning, the lakes and the
   unit equivalence pass.
2. The diagnostic gains the columns `regula` (`ujscie`, `nmt_cieku`, `nmt_odcinka`,
   `digitalizacja`) and `odwraca` from `_line_directions`, run on the burned pieces only
   (their nodes by `join_ends`, their 5 m samples), in place of `hydrograf_odwraca`. On h07
   (`main`): no burned line with `test_ujscia` against `odwraca`; the counts of the table
   above; the guard keeps line 7547 only; no line of MPHP 188 reversed.
3. `process_dem` on windows of the instance's `dem_mosaic.vrt` (single raster, dry run,
   `main` burning, smoothing, no lakes, as in the plan of ADR-072): the Noteć window
   (x 372.0–422.1 km, y 575.0–588.2 km) keeps 593 of the 595 D8 samples along the Noteć
   downstream and none upstream; along the Mielneńska Struga (186176912), the Sipiórka
   (18617652) and the Kanał Wrończyński (186658) the D8 samples run the way of their
   mouth. The diagnostics of the whole h07 grid give reversals by rule within a few lines
   of the table.
4. The full Hydroni area again: scheduled by the coordinator, not in this branch.

## Steps

1. ✅ ADR-077, its line in `docs/DECISIONS.md`, the amendment note of ADR-072.
2. ✅ `scripts/check_stream_directions.py`, its tests, `backend/scripts/README.md`
   (`8252a5e`).
3. `core/hydrology.py`: `_load_stream_features`, `_quarter_rise`, `_mouth_directions`,
   `_watercourse_directions`, `_line_directions`, the wiring and the diagnostics.
4. The tests above.
5. The columns `regula` and `odwraca` of the diagnostic; its README entry.
6. Acceptance 2 and 3; `docs/CHANGELOG.md` (the smoothing changes the published flow),
   `docs/PROGRESS.md`.

## Open

- ~~The classification of the lakes (`_in_flow_order`) reads every line of the three
  layers with the per-line rule of ADR-072 on the smoothed DEM, so it may take a burned
  line that rules 1–2 reversed its digitized way.~~ Decided by the coordinator on
  2026-11-09: one source of the directions, the classification takes the burned lines
  from the smoothing (above, and ADR-077, Consequences).
- A tributary ending on the middle of its receiver gets no mouth; a side arm with two
  contacts with its receiver is split between them (none on h07).
- The networks detached from the main watercourses are burned with `all` and follow the
  same rules; the diagnostic sets their reversed lines apart.
- The rules were not computed on the production Kaczawa (`all`), where ADR-072 already
  reverses 109.5 of the 110.1 km the analysis finds.
