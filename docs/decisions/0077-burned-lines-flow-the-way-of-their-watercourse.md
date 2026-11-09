# ADR-077: A burned line flows the way of its watercourse: to its mouth, else down the DEM of the whole watercourse

**Date:** 2026-11-09
**Status:** accepted (by delegation of the author, 2026-11-09; plan
`docs/plans/2026-11-09-stream-directions.md`); amends ADR-072

## Context

ADR-072 takes every burned BDOT10k line in its digitized direction and reverses it only
where the DEM rises along it by more than 2 m over at least 200 m (`_rises_downstream`).
On the Hydroni area h07 (5 m NMT, `main` burning) that reverses 10 lines (20.0 km).

An analysis of the whole BDOT10k network of h07, now the diagnostic
`backend/scripts/check_stream_directions.py`, finds many more lines digitized upstream.
It reads the 20,279 lines of OT_SWRS_L, OT_SWKN_L and OT_SWRM_L within 1 km of h07,
splits the 1,029 lines on whose middle another line ends (23,266 pieces) and joins the
ends within 0.5 m into 24,868 nodes. A watercourse is the lines of one MPHP identifier
(`IDENTYFIKATORMPHP`), else of one name (`NAZWA`), joined end to end where exactly two of
them meet: 283 watercourses, inside which the digitizing turns 41 times (21 nodes where
two of their lines begin, 20 where two end). For each line it weighs the DEM along it,
the DEM along its whole watercourse (more than 0.5 m between the lowest values of the
first and of the last quarter decides the downstream end), the order of the MPHP
catchment codes and runs of lines between a node where only lines begin and one where
only lines end. All numbers below are of the 3,884 burned pieces of `main` (1,445.1 km).

- The verdict reverses 70 lines (40.6 km), the 10 of ADR-072 among them, and sets apart 8
  more (2.9 km): artificial connectors through lakes (`CECHAGEOMETRII = 'sztuczny
  łącznik'`), along which the DEM is a water surface.
- The mouth test needs neither the DEM nor the digitizing: a watercourse with the MPHP
  identifier K flows to where it meets its receiver, a line whose identifier is a proper
  prefix of K, so along K's lines a line flows from its end farther from that node to the
  nearer one. It orients 2,600 lines (943.6 km). Of the 70 it checks 49 and confirms all
  of them; it contradicts none of the reversed lines, and it finds 18 more lines (9.7 km)
  digitized upstream that the verdict left as suspect (11), contradictory (5) or right
  (2).
- The author reviewed the map of the result (2026-11-09): right, except two doubtful
  cases: the artificial connectors and the networks detached from the main watercourses
  (closed drainage, partly ending in endorheic basins; `main` does not burn them).
- The lines that ADR-072 misses lie in lowland valleys and channels where the DEM along
  one line rises by less than 2 m or the line is shorter than 200 m. In the mountains the
  per-line rule does the work: on the production Kaczawa (`stream_burning: all`) it
  reverses 109.5 of the 110.1 km that the analysis finds digitized upstream.

## Options considered

- **The per-line rule only** (ADR-072, the status quo): rejected. On h07 it misses 60 of
  the 70 lines digitized upstream (20.6 km).
- **The DEM of the whole watercourse only**: rejected as the first rule. A flat valley
  gives no direction: along the 12.7 km of the Noteć in h07 the DEM changes by 0.20 m
  between the quarters, below any threshold that noise leaves; and the DEM along a
  connector is a lake surface.
- **The MPHP catchment codes as the rule**: rejected. They order only a river's own
  catchments of the input, and on h07 they tell the direction of 25 lines.
- **The mouth first, then the DEM of the whole watercourse for the lines digitized
  against the rest of it, then the per-line rule**: chosen.

## Decision

`core.hydrology.smooth_streams_monotonic` takes the direction of each burned line by the
first of these rules that decides it:

1. **The mouth.** Where the MPHP watercourse of the line meets its receiver inside the
   data (a node of the watercourse's lines where a burned line whose MPHP identifier is a
   proper prefix of the watercourse's begins or ends), the line flows from its end
   farther from that node, along the watercourse's lines, to the nearer one. With several
   such nodes, to the nearest; a line whose ends are as far, or not connected to such a
   node, is left to the next rules.
2. **The DEM of the whole watercourse.** A watercourse (the lines of one MPHP identifier,
   else of one name, joined where exactly two of them meet) whose lines are digitized
   both ways has blocks: runs of lines digitized the same way. When the DEM along the
   whole watercourse, without its artificial connectors, rises or falls by more than
   0.5 m between the lowest values of its first and last quarter (on a profile of at
   least 200 m), its downstream end is the lower one, and every block digitized the other
   way is reversed; the lines of the blocks digitized downstream keep their direction by
   this rule. A block whose own DEM, without connectors, falls by more than 2 m the way it
   is digitized keeps its direction and goes to the next rules: the same 2 m by which the
   DEM of a line overrides its digitizing in ADR-072. A watercourse digitized one way
   throughout is not decided by this rule.
3. **The DEM of the line** (ADR-072): a line along which the DEM rises by more than 2 m
   over at least 200 m is reversed.
4. **The digitized direction.**

An artificial connector never takes its direction from the DEM along it: rules 1 and 2
orient it by the topology of its watercourse (rule 2 reads the DEM of the other lines),
rule 3 does not apply to it, and otherwise it keeps its digitized direction.

Unchanged: the order of the flow, the strict descent and the bridging of gaps of ADR-072,
the burning, and the classification of the lakes (`_in_flow_order` keeps the per-line rule
of ADR-072 for every line of the three layers). The diagnostic stays outside the pipeline.

## Consequences

- On h07 (the vector reference of the plan: the lines and nodes of the diagnostic, the
  DEM every 5 m) the rules reverse 96 burned lines (53.7 km) instead of 10 (20.0 km): the
  mouth 73 (44.2 km) of the 2,600 lines it decides, the DEM of the watercourse 23 (9.6 km)
  of the lines of the 23 watercourses digitized both ways, the per-line rule none (its 10
  lines are among those of the first two rules). 69 of the 70 lines of the verdict are
  reversed; the other, a flat line of 318 m (MPHP 18669232) whose watercourse changes by
  0.37 m between the quarters and has no mouth in the data, keeps its direction. The mouth
  test contradicts no line. No line of the Noteć (MPHP 188, 25 lines, 18.2 km) is
  reversed: it still flows west.
- The rules reverse 27 lines (13.4 km) that the verdict did not: the 18 lines of the mouth
  test, the 8 connectors and one line of MPHP 188522 (0.8 km) in a block whose other 7
  lines the verdict reverses. Some lines that the mouth reverses fall the way they are
  digitized: five lines of 200 m or more by 0.5 to 2.4 m (the Sipiórka, MPHP 18617652; the
  Mielneńska Struga, 186176912; the Kanał Wrończyński, 186658), a line of 152 m of the
  Mielneńska Struga by 4.1 m. In each of the three the DEM along the whole watercourse
  rises away from the mouth (by 13.2 m, about 1.2 m and 12.9 m); along a narrow channel
  the 5 m DEM may read the banks. The smoothing cuts these lines by up to that fall.
- The guard of rule 2 is measured on one block of h07: line 7547 of MPHP 186656 (the
  stream of jez. Głębokie, 1.63 km). It begins at a node where two lines of the
  watercourse begin, a divide, and its DEM falls by 4.35 m the way it is digitized, while
  the DEM along the whole watercourse falls 14.0 m towards its other end. Without the
  guard the strict descent would cut a channel up to about 4.4 m deep across the divide.
  Every other block of a watercourse digitized both ways that the rules reverse falls by
  at most 1.67 m the way it is digitized.
- A watercourse with two contacts with its receiver flows to the nearer one: on h07 the
  Nielba (MPHP 18652) and the Bielawka (186352) meet the Wełna twice; where the mouth test
  and the verdict both tell, they agree, but for a connector of 12 m in the Nielba. A side
  arm that leaves its receiver and returns to it would be split between its two ends.
- The mouth must be a node: a tributary that ends on the middle of its receiver gets no
  mouth (on h07 two main lines end on the middle of another), and the smoothing still
  splits no line (ADR-072).
- The nodes of the smoothing are cells (`_line_nodes`, ends within one cell join), not the
  0.5 m of the diagnostic: on h07 with ends joined within 7.5 m the mouth reverses 74
  lines (46.1 km) and contradicts the mouth test of the diagnostic on one line of a few
  metres.
- Networks detached from the main watercourses are oriented by the same rules where they
  are burned (`all`): the diagnostic sets their reversed lines apart
  (`odwrocony_siec_oderwana`) for review.
- The classification of the lakes may take a burned line the other way than the
  smoothing: it reverses a line only by its own rise of more than 2 m, read on the
  smoothed DEM. Open in the plan.
- The smoothing reports which rule reversed how many lines (the plan lists the keys).
  The Hydroni area must be processed again for the published run to follow. On the
  production Kaczawa the verdict finds 0.6 km beyond ADR-072; the rules of this ADR were
  not computed there.
