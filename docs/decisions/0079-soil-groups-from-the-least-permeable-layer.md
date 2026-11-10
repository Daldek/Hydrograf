# ADR-079: The soil groups are those of the least permeable SoilGrids layer of 0–100 cm

**Date:** 2026-11-10
**Status:** accepted (the author's decision of 2026-11-10; the details by delegation)
**Amends:** ADR-075 (the HSG data of `soil_hsg`: the 0–5 cm layer), ADR-067 (decision 3:
the segment of the HSG pin of a set)

## Context

ADR-075 took the hydrologic soil groups of `soil_hsg` from Kartograf's
`calculate_hsg(depth="0-5cm")`: the USDA texture of the SoilGrids clay, sand and silt of the
0–5 cm layer, classified by the texture table of Kartograf's ADR-025. NEH 630 chapter 7
(USDA-NRCS 2009, p. 7-1 to 7-3, table 7-1) assigns the group by the water transmitting layer
with the lowest saturated hydraulic conductivity (Ksat) within 100 cm and by the depth to an
impermeable layer or a water table. ADR-075 measured on h07 (set h07/2026-2) that the 0–5 cm
layer gives B 95.1 % and A 4.8 % of the area, while the least transmissive layer of 0–100 cm
gives B 98.5 % and C 1.5 % with the class Ksat of Rawls, Brakensiek and Saxton (1982), and
named that layer the first improvement of the HSG, a request to Kartograf.

Kartograf's ADR-061 (2026-11-09; in the pin `d0990c8` since `e49eaad0`) answers it:
`calculate_hsg(depth_rule="least-permeable")`, on the command line
`kartograf soil hsg --depth-rule least-permeable`, reads clay, sand and silt at 0–5, 5–15,
15–30, 30–60 and 60–100 cm, takes in every cell the layer with the lowest class Ksat of Rawls
et al. (1982) and gives the cell the group of that layer's texture by the table of the
one-layer call. The raster is a version of the store segment
`hsg/global_soilgrids_0-100cm_least-permeable_mean`; Kartograf takes exactly one of `depth`
and `depth_rule`. After the raster, bootstrap step 5 makes the soil under the wetlands of
BDOT10k group D (ADR-078).

The author decided on 2026-11-10: Hydrograf takes the soil group of the least permeable
SoilGrids layer of 0–100 cm, by default on every instance; the wetlands stay group D after it.

## Options considered

The soil groups:

- **The 0–5 cm layer (status quo of ADR-075):** rejected as the default. It ignores a less
  permeable layer under the surface, against NEH 630 chapter 7, and makes group A of the
  loamy sand of the surface over sandy loam (4.8 % of h07). It stays available as the rule
  `topsoil`, which gives the groups of before.
- **The thresholds of NEH 630 table 7-1 applied to the Ksat directly** (A > 10, B 4–10,
  C 0.40–4, D ≤ 0.40 µm/s for a profile deeper than 100 cm): rejected, as in Kartograf's
  ADR-061 (its option c and its consequences, decided by Kartograf's coordinator on
  2026-11-09). With the Ksat of Rawls et al. (1982) they put loam, silt loam and silt into C,
  while the texture table that classifies one layer puts them into B, so a uniform loam
  profile would get one group from the profile and another from its layer. Hydrograf takes
  Kartograf's rule as it is and does not classify the textures itself (ADR-057).
- **The continuous Ksat of Saxton and Rawls (2006):** not offered by Kartograf (its ADR-061,
  option b: it needs organic matter, and it moved 2.1 % of h07 to group A).
- **The least permeable layer of 0–100 cm, `depth_rule="least-permeable"` (chosen, the
  author's decision).**

How a run takes the rule:

- **A setting that keeps the old rule (chosen):** `soil.hsg_depth_rule` of `config.yaml`,
  `least-permeable` by default and `topsoil` for the call of before, so that earlier results
  can be made again. Only the new rule: rejected, it would lose them.
- **A set without the raster of the rule is refused (chosen)**, with the segment it lacks and
  the Kartograf command that computes the raster. Taking the raster of the other rule when
  the set has only that one: rejected; the soil groups of an instance would follow what a set
  happens to hold instead of its configuration, and nothing would show it.

## Decision

1. **The setting.** `soil.hsg_depth_rule` (`core/config.py`, `backend/config.yaml.example`):
   `least-permeable` (the default) or `topsoil`; another value is refused before step 1
   (`validation_error`, exit 2). `HSG_DEPTH_RULES` of `utils/kartograf_store.py` gives each
   rule its arguments of `calculate_hsg` and its store segment:

   | Rule | `calculate_hsg` | Store segment | SoilGrids inputs |
   |---|---|---|---|
   | `least-permeable` | `depth_rule="least-permeable"` | `hsg/global_soilgrids_0-100cm_least-permeable_mean` | clay, sand and silt at 0–5, 5–15, 15–30, 30–60 and 60–100 cm (15) |
   | `topsoil` | `depth="0-5cm"` | `hsg/global_soilgrids_0-5cm_mean` | clay, sand and silt at 0–5 cm (3) |

2. **The private store** (bootstrap step 5 without a set, also the bootstrap of the admin
   panel, which runs with the `config.yaml` of the backend): the raster of Poland of the rule
   (EPSG:2180 `167000 29000 860000 814000`), a version of `<cache_dir>/kartograf`, computed
   once and reused after.
3. **A set** (amends decision 3 of ADR-067): the HSG pin is a version of the segment of the
   rule; the pins of an HSG raster of the other rule are verified and not used. Without a
   raster of the rule whose requested box covers the mosaic, the run is refused before step 1
   (`no_data`, exit 14, reason `set_hsg_missing`): the message names the segment and the rule,
   the hint the Kartograf command over the box of the mosaic (EPSG:2180, rounded outwards to
   whole metres) for a call of Archiwista, for example on h07:
   `kartograf soil hsg --depth-rule least-permeable --bbox 350581,506697,422093,588208`. Any
   box that covers the mosaic will do; Poland's box serves every project of a store.
4. **The record.** `bootstrap_set.json` keeps `hsg_depth_rule` (null when step 5 is skipped);
   `instance.json` gives `hsg`, the rule and its segment (null when unknown), and
   `write_instance_info --hsg-depth-rule` names the rule for data without a record.
5. **The CN on demand** of `analyze_watershed` (`get_hsg_from_soilgrids`, ADR-075 decision 6)
   takes the default rule; that path reads no configuration.
6. **The wetlands** of BDOT10k (`OT_OIMK_A`) stay group D after the raster (ADR-078): the rule
   assumes a profile deeper than 100 cm to an impermeable layer and to the water table
   (Kartograf's ADR-061, decision 5), and the water table is what the wetlands add.

## Consequences

- h07 (SoilGrids 2.0, the raster of set h07/2026-2 as ADR-075 measured it): the groups of the
  raster go from B 95.1 %, A 4.8 % (C 7 km²) to B 98.5 %, C 1.5 % of the area: the loamy sand
  of the surface becomes B, the sandy clay loam at 60–100 cm C. Measured on the raster that
  set h07/2026-4 pins (2026-11-10, below), over the 69,719 cells of h07: A 5.33 % → 0,
  B 94.67 % → 98.39 %, C 0 → 1.61 %; every cell of A becomes B and 1.61 % of the cells of B
  become C. The wetlands make their 39.55 km² of h07 group D as before. `soil_hsg` and the CN
  of the catchments change at the next step 5 of Hydroni, where they are to be measured.
  *[Inference, not measured:]* ADR-075 found that the groups of h07 lowered the CN by 0.7 on
  average against all-B, almost all of it by group A, so the CN of h07 should rise by about
  that much, most in the catchments with much A (up to 9.5), and a little more by the 1.6 % of
  C.
- Kaczawa (production, private store; topsoil B 99.50 %, C 0.14 %, D 0.36 %): to be measured
  at its next step 5.
- Every instance needs step 5 again for the new groups, and the CN follows them at query time
  (ADR-075). Hydroni's bootstrap from h07/2026-3, whose only HSG raster is that of 0–5 cm, is
  refused; set h07/2026-4 (closed 2026-11-10, 728 pins) is 2026-3 with the raster of the rule
  of `67000 -71000 960000 914000` instead of the 0–5 cm one, computed by
  `kartograf soil hsg --depth-rule least-permeable --bbox 67000,-71000,960000,914000` into the
  Hydroni store, so the bootstrap of Hydroni takes `--set 2026-4`. The Archiwista that makes
  such a set needs a Kartograf with `depth_rule` (`d0990c8`, Nogat's release set candidate-2).
- The first step 5 of the private store fetches the 12 SoilGrids rasters of Poland that the
  0–5 cm raster did not need (15 instead of 3; Kartograf's ADR-061); later runs reuse them.
  The CN on demand of `analyze_watershed` fetches 15 rasters of its bbox instead of 3 and keeps
  none.
- A set made before this decision still runs with `soil.hsg_depth_rule: topsoil`; the record
  and `instance.json` then say so.
