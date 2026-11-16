# Plan: the CN of the soil-cover complexes (land cover × HSG)

Approved: 2026-11-08 (by delegation of the author)

Requirements: the author's goal of 2026-11-08 (land cover and CN as methodologically
correct as the data allow, for the drought work on the 223 h07 catchments of Hydroni);
decision ADR-075. Scope: how the CN is computed from `land_cover` and `soil_hsg`
(`core/land_cover.py`, `core/cn_tables.py`, `core/cn_calculator.py`, `core/point_info.py`,
`core/watershed_service.py`, the export's CN columns), the HSG check, the panel's (i).
Not in scope: the content of `land_cover` (branch `feat/landcover-industry`, ADR-074),
bootstrap step 5. Branch `feat/cn-by-soil-group`.

## Steps

1. ✅ HSG check (ADR-075, Context): bootstrap step 5, the SoilGrids texture of h07 at
   0–5 cm and deeper, NEH 630 ch. 7. Usable; B on ~95% of h07, agreeing with NEH 630's
   least transmissive layer.
2. ✅ Design (ADR-075): complexes in PostGIS, Hydrolog's TR-55 table with the mapping of
   `core/cn_tables.py` (overrides by `bdot_class` agreed with LandCover's strings), the
   rule for land cover outside `soil_hsg`, composite CN only, AMC I/III in the export.
3. ✅ Code: `get_land_cover_for_boundary` (`_COMPLEXES_SQL`, `summarize_complexes`),
   `determine_cn` on it (`calculate_weighted_cn` removed), `cn_tables` rewritten (stale
   BDOT10k/CORINE/English keys, `lookup_cn`, `calculate_weighted_cn_from_stats` gone),
   `cn_calculator` on the categories of `land_cover` and the HSG shares, identify with the
   point's soil group, tiles without `cn_value`, `LandCoverStats.hsg_assumed_pct` and a
   float `cn_value` per category, export columns `cn_amc_i`, `cn_amc_iii`, `hsg_*_pct`,
   `lc_without_hsg_pct`; the (i) of CN, the land cover legend, the identify card, the guide.
4. ✅ Tests: the hand-computed CN of known complexes and of a part without soil
   (`test_land_cover.py`, `test_land_cover_db.py` on PostGIS), the TR-55 covers
   (`test_cn_tables.py`), the export's CN, AMC I/III (Hydrolog's conversion) and HSG
   columns (`test_export_catchment_parameters.py`), identify (`test_point_info.py`,
   `test_identify_point_db.py`), the Kartograf path (`test_cn_calculator.py`).
5. ✅ Measurement on h07 (ADR-075, Consequences): pg_dump of Hydroni's `land_cover` and
   `soil_hsg` (and the 100000 m² stream tables the export checks) into a throwaway
   PostGIS; the export of the 223 catchments with the code of `origin/develop` and of this
   branch; GeoPackages in `/tmp/cn-work/` only.
6. ✅ Docs: COMPUTATION_PIPELINE phase 5, DATA_MODEL, CHANGELOG, INFO_TEXTS_SOURCES,
   ADR-075.

## Integration with `feat/landcover-industry`

- ✅ The branch that merges second drops `land_cover.cn_value`: an Alembic migration, the
  importer's `CATEGORY_CN` and the INSERT column, the `cn_value` of the INSERTs of
  `tests/integration/test_identify_point_db.py` and `test_land_cover_db.py`, DATA_MODEL.
  Done on `integrate/landcover-cn` (2026-11-08): migration 006; `test_cn_tables.py` fails
  for a `bdot_class` of the import without a cover of its own or a decision that it
  takes its category's.
- ✅ `frontend/js/info-texts.js`: CurveNumber edited `cn` only, LandCover the Nash
  entries; the second merger re-runs `scripts/bump_asset_versions.py`.

## Open questions for the author

1. Arable land as small grain (B 75) or row crops (B 78), both good condition (TR-55
   table 2-2b)? Decided by the author 2026-11-08: small grain, straight row, good (B 75).
2. Should the drought work get the weighted runoff for given rainfalls besides the
   composite CN (ADR-075: +21% at 50 mm)? Decided by the author 2026-11-08: no; the
   area-weighted composite CN, which the export names for AMC I, II and III (`cn_amc_i`,
   `cn_amc_ii` = `cn`, `cn_amc_iii`).
3. Requests to the producers: Kartograf, an HSG from the least transmissive SoilGrids
   layer 0–100 cm; Hydrolog, the missing TR-55 rows (paved roads with open ditches incl.
   right-of-way, residential 1/4 acre, woods–grass) and water at 98 per NEH 630 ch. 9.
4. A water-table criterion for the HSG (wet valley soils as D) needs another soil source.
