# ADR-070: Flow path heads, overland segments and channel sources measured in preprocessing

**Date:** 2026-11-05
**Status:** accepted

## Context

The time of concentration methods take the inputs their primary sources define (Nogat plan
`docs/plans/2026-11-05-official-tc-inputs.md`, decision D5): Kirpich's slope is
(elevation of the head of the longest flow path on the divide − elevation of the outlet) /
the length of that path, and FAA, Kerby and Kerby–Kirpich time the overland segment of
that path, from its head to the stream network. Hydrograf measured neither: the
preprocessing knew the head cell of each sub-catchment's longest flow path but stored only
its flow distance. The main channel slope took the highest point of the head
sub-catchment instead of the source of the channel, so a short channel in a large
sub-catchment got slopes above 90% (user report #13). Users asked for networks and
sub-catchments of 1 km² and 10 km² (report #27).

Rasters are processed only by the preprocessing pipeline (CLAUDE.md); the API reads
PostGIS and the in-memory catchment graph. The production data come from the bootstrap of
2026-10-30, cut on 2026-11-01 to the Kaczawa above 51.222825 N, 16.179380 E: the database
rows to the upstream closure of that outlet, the rasters of `data/nmt` to its boundary
with nodata outside. The rasters of the run before the cut are in the backup
`/data/nmt/hydrograf-backup-2026-11-01/data.tar.zst`.

## Options considered

- **Where the values are measured.** At request time from the rasters (the API would read
  the DEM and the flow directions for every delineation, against the rule above) or per
  sub-catchment in the preprocessing, where the head cell and the flow paths are already
  traced (chosen).
- **The source of the main channel (#13).** The highest point of the head sub-catchment
  (the old value), the highest point of the watershed, or the upstream end of the stream
  segment of the head sub-catchment, i.e. the channel head of the DEM network at the
  threshold (chosen): the channel the length is measured along starts there.
- **Where the overland segment ends.** At the first cell of the DEM stream network of the
  delineation threshold (chosen; D5) or at a BDOT10k stream, which is not the "well-defined
  channel" of Kerby and TxDOT and gives segments far beyond Kerby's 366 m.
- **How production gets the values and the new thresholds.** A full run of the DEM on the
  cut rasters, or the saved rasters of the run (chosen). A full run takes about 45 minutes
  at a peak of about 6 GB, turns the cut boundary into outlets (the cells of the divide
  then drain out of the area, so the heads of the flow paths move), and numbers the
  segments anew, so every tile and every stored `segment_idx` changes. The saved rasters
  give the values the pipeline computes, in less than a minute and below 2 GB for the
  backfill and a few minutes for the new thresholds, and leave the existing rows and
  tiles as they are.

## Decision

`stream_catchments` gets `flow_path_head_elev_m`, `overland_length_m`, `overland_drop_m`
and `stream_head_elev_m` (migration 004), measured on the filled DEM of the zonal
statistics by `scripts/process_dem.py::_enrich_catchments_with_flow_paths`: the elevation
of the head (farthest cell) of the sub-catchment's longest flow path; the length (along the
D8 path) and the drop of its overland segment down to the first cell where the
accumulation reaches the sub-catchment's threshold; the elevation of the upstream end of
the sub-catchment's stream segment. What cannot be measured stays NULL. `CatchmentGraph`
takes them from the node with the largest `max_flow_dist_m` (the node of
`hydraulic_length_km`) and from the head node of the main channel. The morphometry gains
`flow_path_length_km` (= `hydraulic_length_km`), `flow_path_slope_m_per_m`,
`overland_length_km` and `overland_slope_m_per_m`; a slope that is not positive or lacks
an elevation is None, never 0 or a default. `channel_slope_m_per_m` is (elevation of the
source − elevation of the outlet) / `channel_length_km`.

The preprocessing thresholds are 10000, 100000, 1000000 and 10000000 m²
(`core.constants.PIPELINE_THRESHOLDS_M2`). Existing data get the columns from the rasters
their run saved (`scripts/backfill_flow_path_heads.py`, which stops when a head does not lie
in its sub-catchment or its flow distance differs from `max_flow_dist_m`) and new
thresholds from the same rasters (`scripts/process_dem.py --from-intermediates`, which
rebuilds pyflwdir's D8 grid from the saved flow directions and flow distances and refuses
thresholds already in the database). The production procedure is
`docs/runbooks/2026-11-v050-reprocessing.md`.

## Consequences

- Until the backfill the new columns are NULL: the flow path slope, the overland segment
  and the main channel slope are empty, and Lutz's estimation refuses a watershed without
  a channel slope. The production procedure fills them before the API with the new code
  starts.
- On the production data the backfill needs the rasters from before the cut: the cut set 62
  cells of the divide to nodata, and the heads of 19 sub-catchments of the threshold 10000 and
  of 11 of the threshold 100000 lie among them. The new thresholds use the cut rasters, so
  they end at the boundary of the data.
- The overland segment depends on the threshold: at 1 km² and 10 km² it also covers reaches
  where a stream flows, and Kerby's range check flags it.
- The intermediate rasters of a run (`save_intermediates`, which the bootstrap sets) are
  what later columns and thresholds can be computed from; deleting them means a full run.
