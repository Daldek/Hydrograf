# ADR-075: The CN is that of the soil-cover complexes, from Hydrolog's TR-55 table

**Date:** 2026-11-08
**Status:** accepted (by delegation of the author, 2026-11-08; plan
`docs/plans/2026-11-08-cn-by-soil-group.md`)

## Context

The panel, the hydrograph and the export took `land_cover.cn_value`: one CN per land
cover category whatever the soil (grunt orny 78, las 60, łąka 70, zabudowa 85, droga 98,
woda 100, inny 75). The hydrologic soil group (HSG) entered only the Kartograf path of
`analyze_watershed`, as one dominant group. In SCS-CN the CN belongs to a hydrologic
soil-cover complex, a cover on a soil group (USDA-NRCS 2004, NEH 630 ch. 9, p. 9-1;
USDA-SCS 1986, TR-55, tables 2-2a to 2-2c). The h07 catchments of Hydroni (223, 2,941 km²)
feed the author's work on hydrological and soil drought.

**The HSG data (`soil_hsg`, bootstrap step 5).** The raster is Kartograf's
`calculate_hsg(depth="0-5cm")`: SoilGrids 2.0 clay, sand and silt 0–5 cm (EPSG:4326,
~150 × 265 m cells), USDA texture by Hydrolog's classifier, Kartograf ADR-025 table
(sand, loamy sand → A; sandy loam, loam, silt loam → B; …). Step 5 warps it by nearest
neighbour to 250 m cells of EPSG:2180, fills gaps by the nearest cell and polygonizes it
(no simplification; fragments < 50 m² dropped). Hydroni's 479 polygons (A 430, B 46, C 3)
are a count of islands: by area A 280 km² (4.8%), B 5,542 km² (95.1%), C 7 km². Inside h07
the 0–5 cm texture is sandy loam on 94.7% of the area and loamy sand on 5.3% (clay p5–p95
6–10%, sand 70–77%, silt 16–21%): SoilGrids smooths the soil mosaic of the Wielkopolska
lowland into one band. Deeper layers (fetched for this check, not kept): 5–15 cm loamy
sand 18%, 15–100 cm sandy loam on 98–100%, a little sandy clay loam at 60–100 cm (1.5%).

NEH 630 ch. 7 (2009, p. 7-1 to 7-3, table 7-1) assigns the group by the least transmissive
layer within 100 cm and the depth to a water table; it describes group B as typically
10–20% clay, 50–90% sand, loamy sand or sandy loam, and A as sand or gravel. The least
transmissive layer of the h07 profile gives B on 98.5% and C on 1.5% with the class Ksat
of Rawls et al. (1982), and B 96.4%, A 2.1%, C 1.5% with the continuous Ksat of Saxton and
Rawls (2006). TR-55 (1986, appendix A) puts sandy loam into A; with that rule h07 would be
all A. **Conclusion:** the HSG is usable and agrees with NEH 630 for ~95% of h07 (B); it
overstates A by the loamy-sand topsoil patches (~5%) that the profile rule makes B, and
it knows nothing of the water table (wet valley soils, D or A/D–C/D by NEH 630, are B or A
here). It is nearly uniform, so the land cover drives the spatial pattern of the CN.

## Options considered

1. **Keep one CN per category** (status quo): ignores the soil; not the method of TR-55.
2. **Category CN on the dominant HSG of the watershed**: loses the soil pattern inside a
   watershed and jumps when the dominant group changes.
3. **Area-weighted CN of the complexes land cover ∩ soil, computed in PostGIS** (chosen).
4. **Weighted runoff instead of weighted CN** (NEH 630 ch. 10, p. 10-10: "the method of
   weighted Q always gives the correct result"): depends on the rainfall, so it is no
   single parameter of a watershed; the hydrograph engine takes one CN; WinTR-55 and
   WinTR-20 use the weighted CN.

## Decision

1. **Complexes.** `get_land_cover_for_boundary` returns the land cover of the watershed
   whole and in its pieces on each soil group (soil clipped to the watershed and
   subdivided, then joined to `land_cover` by its index). CN of the watershed =
   Σ A_i CN_i / Σ A_i over the complexes (Hydrolog's `calculate_weighted_cn`), to 0.1; the
   CN of a category is the same mean over its complexes.
2. **Single source of the numbers: Hydrolog's TR-55 table** (`hydrolog.runoff.get_cn`).
   `core/cn_tables.py` maps (category, `bdot_class`) to a TR-55 cover:
   - `las` → woods, good: Polish forests are not grazed and keep litter and brush (TR-55
     table 2-2c, note 6);
   - `łąka` → meadow, continuous grass mowed for hay (2-2c); brush (PTRK) and orchards
     (PTUT, woods–grass good) differ by ≤ 2 at B;
   - `grunt_orny` → small grain, straight row, good (2-2b): cereals are most of the
     sown area; the condition moves the CN by 1 at B (row crops good would be 78);
   - `zabudowa_mieszkaniowa` → residential 1/3 acre, 30% impervious (2-2a);
     `PTZB:wielorodzinna` → 1/8 acre, 65%. Measured on h07 BDOT10k: roofs (BUBD) cover
     15.7% of PTZB jednorodzinna, 19.4% of pozostała and 20.6% of wielorodzinna; roofs are
     ~30–37% of the impervious cover of residential sites (Schueler 1994), and the minor
     streets lie inside PTZB;
   - `zabudowa_przemysłowa` → industrial, 72% (2-2a); `PTZB:handl.-usług.` → commercial
     and business, 85% (roofs 31.5% and 25.3% of those kinds);
   - `droga` → paved (2-2a); `woda` → CN 98, "impervious and water surfaces … are always
     assigned a CN of 98" (NEH 630 ch. 9, p. 9-1; Hydrolog's own WATER row is 100, so the
     paved row of Hydrolog, 98, is used);
   - `inny` → open space, fair (2-2a); `PTPL:nieutwardzony` → dirt road incl. right-of-way;
     `PTWZ` (pits, heaps) → newly graded area, no vegetation.
   A `bdot_class` override applies only within its category; plain layer codes (today's
   data) take the category's cover.
3. **Land cover outside `soil_hsg`** takes the soil groups of the watershed's land cover
   that lies on `soil_hsg`, in their shares (the best estimate of unknown soil is the soil
   around it, and the mean is kept); with no soil data at all, group B (the fallback of
   the Kartograf HSG). The share is reported (`hsg_assumed_pct`, `lc_without_hsg_pct`).
4. **Composite CN only** in the panel and the export; the weighted runoff is not reported
   (option 4). Its size on h07 is below.
5. **AMC.** The panel and the CN columns stay AMC II. The export adds `cn_amc_i` and
   `cn_amc_iii`: Hydrolog's conversion (`SCSCN.adjust_cn_for_amc`, Hawkins et al. 1985,
   approximating NEH 630 ch. 10 table 10-1) of the watershed CN, exactly as the hydrograph
   converts it, so the export equals the "CN użyty" of a hydrograph with that AMC. NEH 630
   ch. 10 (p. 10-6) treats ARC I and III as the dry and wet envelopes of the CN of a
   watershed; the dry one is the value a drought study needs.
6. **Kartograf path** (`analyze_watershed`): without an overlay the land cover shares and
   the HSG shares of the bbox are taken as independent; the CN is the weighted mean of
   the complexes with the products of the shares as weights.
7. **`land_cover.cn_value`** is no longer read (panel, hydrograph, identify, tiles,
   export). The import still writes it; the column is dropped by whichever of this branch
   and `feat/landcover-industry` merges second (a migration and the importer's
   `CATEGORY_CN`), so each branch stays consistent alone.

## Consequences

Measured on h07 (throwaway PostGIS with Hydroni's `land_cover` and `soil_hsg`, the export
of the 223 catchments before and after, today's land cover):

| | before | after |
|---|---|---|
| CN mean (sd) | 75.8 (4.1) | 71.4 (4.7) |
| min / p25 / median / p75 / max | 63.8 / 73.8 / 77.1 / 78.3 / 85.6 | 53.5 / 69.4 / 72.4 / 74.8 / 82.4 |
| area-weighted CN | 75.2 | 70.7 |

- Every catchment's CN falls, by 3.0 to 14.2 (median 3.9): arable land 78 → 75 on B,
  forest 60 → 55, built-up 85 → 72, water 100 → 98; the largest drops are forested
  catchments with A soils (188581: 67.7 → 53.5, forest 64%, A 49.6%).
- Effect of the HSG: against all-B the actual groups lower the CN by 0.7 on average
  (0 for most catchments, up to 9.5 where A covers much; 18 catchments have A > 20%);
  the TR-55 1986 texture rule (all A) would give 13.5 less.
- AMC I 34–67 (median 53), AMC III 73–92 (median 86).
- Spread of the CN of the complexes inside a catchment: sd 8.5 on average (up to 19.5).
  The weighted runoff exceeds the runoff of the weighted CN by 0.95 mm at P = 25 mm
  (0.40 vs 1.35 mm), 1.7 mm at 50 mm (+21% median) and 1.6 mm at 100 mm (+4%): small for
  design storms, large in relative terms for small events.
- The land cover query of the panel takes 0.55 s instead of 0.08 s per h07 catchment
  (max 1.6 s for 63 km²); Hydroni's `land_cover` holds every row twice (a re-import of
  step 4), which doubles the work.

What would improve the HSG: the least transmissive layer of SoilGrids 0–100 cm (a
Kartograf request: HSG from several depths); a water-table criterion (D or dual groups for
wet valley soils, e.g. from the soil-agricultural map or hydrogenic soils); a finer soil
source than SoilGrids 250 m. Missing TR-55 rows in Hydrolog (a Hydrolog request): paved
roads with open ditches including right-of-way (83/89/92/93, the row PTKM describes: it is
the right-of-way with ditches and rail beds, 17 km² in h07, ≤ 0.1 CN on average),
residential 1/4 acre (38%), woods–grass combination, and water at 98.
