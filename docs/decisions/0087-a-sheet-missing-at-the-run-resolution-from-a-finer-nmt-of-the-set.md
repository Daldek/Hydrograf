# ADR-087: A sheet the source lacks at the run's resolution comes from a finer NMT of the set

**Date:** 2026-11-15
**Status:** accepted
**Amends:** ADR-067 (decision 4)

## Context

ADR-067 requires every sheet of the project's area among the NMT pins of the segment of the run's
resolution, `nmt/pl_1992_<resolution>_evrf2007`. GUGiK does not publish every sheet at every
resolution: in the scenario test of 2026-11-15 the area of the Bóbr's first part (412 sheets) had
21 sheets in the Karkonosze and the Izera Mountains (69.4 km², 4.1 % of the area) without NMT 5 m
EVRF2007. GUGiK's sheet index has them only as NMT 1 m (EVRF2007 and KRON86); Kartograf skips
them at 5 m (`no_coverage_some`, with the hint `--resolution 1m`). A set built from everything the
source publishes at 5 m could therefore never be bootstrapped (`set_sheets_missing`, exit 14), and
`--allow-uncovered` does not apply to it: it is the switch of the ADR-076 check that follows.

The pipeline already averages finer sheets onto the 5 m grid: GUGiK delivers some 5 m sheets of
2021 as 1 m grids, and step 3 averages each such sheet onto the lattice of the 5 m sheets
(`utils.raster_utils.align_to_cellsize`, `gdalwarp -r average`) before the mosaic (Hydroni: 20 of
its sheets).

## Options considered

- **A. A missing sheet from a finer NMT segment pinned in the set.** The set stays the whole input
  (ADR-067); the sheet has data of the same provider and vertical datum, averaged as the 1 m
  deliveries are.
- **B. `--allow-uncovered` also accepts missing set sheets.** The mosaic gets a nodata gap, which
  ADR-076 reports and ADR-073 may interpolate; the headwaters of the gap would be lost.
- **C. A smaller area.** It cuts the headwaters off the basin.

## Decision

Option A.

1. A sheet of the project's area that the segment of the run's resolution lacks is taken from the
   segment of a finer resolution pinned in the set, the nearest finer one first (for `5m`:
   `nmt/pl_1992_1m_evrf2007`). Only those sheets are taken: a finer pin of a sheet the run's
   segment has, or of a sheet beyond the area, stays unused. A run at `1m` takes no coarser sheet.
2. One version per sheet holds there too: two versions of a sheet that is used are refused
   (`set_unit_ambiguous`).
3. The sheets of the mosaic are the sheets of the run's segment and these; the frames of all of
   them make the mosaic's box (the counties of decision 5, the HSG coverage of decision 6) and the
   ADR-076 coverage. Step 3 averages the finer sheets onto the cells of the run as before.
4. The run says which sheets came from where: a warning in the log, the dry-run's line „NMT
   `<finer segment>` zamiast `<segment>` (N ark.): codes” and „w tym N ark. z `<finer segment>`
   (uśrednione do 5m)” in step 2, and `inputs.nmt.finer_sheets` (finer segment → sheet codes) in the
   logged identity of the set and in `bootstrap_set.json`.
5. The hint of `set_sheets_missing` says that a sheet the source lacks at the resolution can be
   pinned at a finer one.

## Consequences

- A set of the Bóbr's first part is the 5 m sheets plus the 1 m versions of the 21 sheets
  (`elevation download --resolution 1m` of those sheets, pinned into the set).
- The NMT of those sheets is the mean of 1 m cells, not GUGiK's 5 m product; the record names them.
- A 1 m sheet is about 25 times the cells of a 5 m one: step 3 reads and averages each once
  (`<data>/nmt/aligned/`).
