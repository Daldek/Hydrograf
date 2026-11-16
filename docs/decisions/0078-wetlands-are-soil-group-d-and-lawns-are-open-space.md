# ADR-078: Wetlands are hydrologic soil group D; the grass of sports and recreation complexes and airports is open space

**Date:** 2026-11-10
**Status:** accepted (the author's decisions of 2026-11-09, below; the details by
delegation)
**Amends:** ADR-074 (the wetland overlay and the complexes that it left unused), ADR-075
(the soil groups of `soil_hsg`, the TR-55 cover of the lawns)

## Context

ADR-074 left two kinds of BDOT10k overlay unused. The wetlands of `OT_OIMK_A`
("mokradło"): "a wet soil is the soil group's matter, and TR-55 has no wetland cover". The
complexes other than the industrial ones (`OT_KU*_A`): "the partition already shows their
cover, and TR-55 has no district of their kind". ADR-075 found that the hydrologic soil
groups of SoilGrids "know nothing of the water table": wet valley soils, D or A/D to C/D by
NEH 630, are B or A in `soil_hsg`; it named a water-table criterion among the improvements.

NEH 630 chapter 7 (USDA-NRCS 2009, p. 7-2 to 7-3) puts a soil with a water table within
60 cm of the surface into group D; a wet soil that can be drained gets a dual group (A/D,
B/D, C/D) whose first letter is the drained and whose second letter the undrained
condition. TR-55 (USDA-SCS 1986) describes the meadow of table 2-2c as "continuous grass,
protected from grazing and generally mowed for hay", and the open space of table 2-2a as
"lawns, parks, golf courses, cemeteries, etc.", by its grass cover: poor below 50%, fair
50 to 75%, good above 75%.

The author decided on 2026-11-09:

- **Wetlands:** a wet soil is the soil group's matter: inside the `OT_OIMK_A` polygons the
  hydrologic soil group becomes D; the land cover of the PT partition stays.
- **Complexes:** measure them on h07 first, then map only the kinds that change the TR-55
  cover: the sports and recreation complexes to open space (TR-55 table 2-2a, the condition
  argued as in ADR-075), the transport complexes such as airports to open space with their
  paved parts kept paved through PT; the others unchanged.

### Measured on h07

The 13 BDOT10k packages of the set h07/2026-3 (the same versions as in h07/2026-2), the
land cover of today's import (ADR-074) of the same packages, and the 223 catchments h07
(`Obszar_h07.gpkg`, 2,940.69 km²). Areas in km²: "13 packages" is the area in the whole
counties (13,790 km²), "h07" the part inside the catchments, split by the land cover
category under it (`zab. mieszk.` `zabudowa_mieszkaniowa`, `zab. przem.`
`zabudowa_przemysłowa`). Each layer is counted by itself: complexes of different layers
overlap, a wetland can lie in a park.

| Layer | Kind (`RODZAJ`) | 13 packages | h07 | objects in h07 | łąka | las | grunt_orny | zab. mieszk. | zab. przem. | droga | woda | inny |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OIMK | bagno | 12.74 | 0.98 | 42 | 0.80 | 0.17 | <0.01 | 0 | 0 | 0 | 0 | 0 |
| OIMK | teren podmokły | 183.30 | 38.57 | 2880 | 28.76 | 9.51 | 0.29 | <0.01 | <0.01 | <0.01 | 0.01 | <0.01 |
| **OIMK** | **all** | **196.04** | **39.55** | **2922** | **29.56** | **9.68** | **0.29** | **<0.01** | **<0.01** | **<0.01** | **0.01** | **<0.01** |
| KUSK | kompleks sportowo-rekreacyjny | 8.51 | 0.84 | 30 | 0.62 | 0.07 | 0 | 0.07 | <0.01 | 0.04 | <0.01 | 0.03 |
| KUSK | ogród botaniczny | 0.30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| KUSK | ogród zoologiczny | 1.15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| KUSK | park lub skwer | 20.54 | 4.74 | 115 | 0.65 | 3.67 | 0.05 | 0.15 | <0.01 | 0.01 | 0.18 | 0.02 |
| KUSK | zespół domów letniskowych | 7.71 | 2.49 | 66 | 0.39 | 0.21 | 0.02 | 1.87 | 0 | 0 | <0.01 | 0 |
| **KUSK** | **all** | **38.21** | **8.07** | **211** | **1.66** | **3.95** | **0.06** | **2.10** | **<0.01** | **0.06** | **0.19** | **0.05** |
| KUKO | dworzec autobusowy | 0.12 | 0.01 | 2 | <0.01 | 0 | 0 | <0.01 | 0 | 0.01 | 0 | 0 |
| KUKO | lotnisko lub lądowisko | 37.22 | 2.23 | 2 | 1.54 | 0.38 | 0.19 | 0.01 | <0.01 | 0.10 | 0.01 | 0 |
| KUKO | miejsce obsługi podróżnych | 0.85 | 0.31 | 6 | 0.07 | 0 | 0 | 0.01 | 0 | 0.24 | 0 | 0.01 |
| KUKO | parking | 2.36 | 0.11 | 15 | <0.01 | 0 | 0 | 0.01 | 0.02 | 0.08 | 0 | 0.01 |
| KUKO | port wodny lub przystań | 0.04 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| KUKO | stacja kolejowa | 2.44 | 0.11 | 14 | <0.01 | 0 | 0 | 0.02 | <0.01 | 0.08 | 0 | 0 |
| KUKO | stacja paliw | 1.80 | 0.28 | 66 | 0.07 | 0 | <0.01 | 0.03 | 0.11 | 0.06 | <0.01 | 0.02 |
| KUKO | zajezdnia lub baza transportowa | 0.97 | 0.08 | 7 | 0.02 | <0.01 | 0 | 0.01 | 0.03 | 0.02 | 0 | 0 |
| **KUKO** | **all** | **45.80** | **3.14** | **112** | **1.70** | **0.38** | **0.19** | **0.08** | **0.17** | **0.58** | **0.01** | **0.03** |
| KUPG | baza paliw | 1.29 | 0.54 | 1 | 0 | 0 | 0 | 0 | 0.54 | 0 | 0 | 0 |
| KUPG | elektrociepłownia | 0.65 | 0.02 | 1 | 0 | 0 | 0 | 0 | 0.02 | 0 | 0 | 0 |
| KUPG | elektrownia | 11.23 | 3.32 | 63 | 0.02 | 0 | <0.01 | <0.01 | <0.01 | 0 | <0.01 | 3.29 |
| KUPG | gazownia | 0.32 | 0.03 | 2 | 0 | 0 | 0 | 0 | 0.03 | 0 | 0 | 0 |
| KUPG | gospodarstwo hodowlane | 24.41 | 6.48 | 178 | 1.34 | 0.11 | 0.02 | 3.39 | 0.92 | 0.07 | 0.05 | 0.60 |
| KUPG | kopalnia | 13.11 | 2.29 | 15 | 0.32 | <0.01 | <0.01 | 0.02 | 0.01 | <0.01 | 0.80 | 1.14 |
| KUPG | oczyszczalnia ścieków | 2.66 | 0.40 | 33 | 0.19 | <0.01 | <0.01 | 0.07 | 0.01 | <0.01 | 0.01 | 0.10 |
| KUPG | podstacja elektroenergetyczna | 1.12 | 0.06 | 8 | 0.02 | 0 | 0 | 0.02 | 0 | 0 | 0 | 0.02 |
| KUPG | przepompownia | 0.23 | 0.02 | 3 | 0.01 | 0 | 0 | <0.01 | 0.01 | 0 | 0 | <0.01 |
| KUPG | składowisko odpadów | 2.05 | 0.31 | 6 | 0.14 | 0.02 | <0.01 | 0.04 | <0.01 | 0 | <0.01 | 0.10 |
| KUPG | teren ujęcia wody | 0.30 | 0.06 | 18 | 0.02 | 0 | 0 | 0.03 | 0 | 0 | 0 | 0.01 |
| KUPG | zakład produkcyjny, usługowy lub remontowy | 58.32 | 5.70 | 319 | <0.01 | <0.01 | <0.01 | <0.01 | 5.68 | <0.01 | 0.02 | 0 |
| KUPG | zakład utylizacji | 0.16 | 0.01 | 1 | 0 | 0 | 0 | 0 | 0.01 | 0 | 0 | 0 |
| KUPG | zakład wodociągowy | 3.44 | 0.08 | 8 | 0.03 | <0.01 | 0 | 0.02 | 0.02 | <0.01 | 0 | 0.01 |
| **KUPG** | **all** | **119.29** | **19.32** | **656** | **2.08** | **0.14** | **0.02** | **3.60** | **7.25** | **0.08** | **0.87** | **5.27** |
| KUSC | cmentarz dla zwierząt | 0.01 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| KUSC | cmentarz komunalny | 3.00 | 0.06 | 2 | 0.02 | <0.01 | 0 | <0.01 | 0 | <0.01 | 0 | 0.03 |
| KUSC | cmentarz wojenny | 0.25 | <0.01 | 2 | 0 | <0.01 | <0.01 | 0 | 0 | 0 | 0 | 0 |
| KUSC | cmentarz wyznaniowy | 4.73 | 1.08 | 176 | 0.13 | 0.33 | 0.01 | 0.02 | <0.01 | <0.01 | <0.01 | 0.59 |
| KUSC | zespół sakralny lub klasztorny | 2.34 | 0.35 | 44 | 0.05 | 0.03 | <0.01 | 0.24 | <0.01 | 0.01 | <0.01 | 0.01 |
| **KUSC** | **all** | **10.33** | **1.49** | **224** | **0.21** | **0.36** | **0.01** | **0.26** | **<0.01** | **0.01** | **<0.01** | **0.63** |
| KUOS | ośrodek naukowo-badawczy | 1.60 | 0.01 | 1 | <0.01 | 0 | 0 | <0.01 | 0 | 0 | 0 | 0 |
| KUOS | przedszkole | 1.10 | 0.11 | 22 | 0.04 | <0.01 | <0.01 | 0.07 | 0 | <0.01 | 0 | <0.01 |
| KUOS | szkoła lub zespół szkół | 8.79 | 1.11 | 103 | 0.39 | 0.03 | 0.01 | 0.55 | <0.01 | 0.11 | <0.01 | 0.01 |
| KUOS | szkoła wyższa | 1.82 | 0.09 | 3 | 0.04 | 0.01 | 0 | 0.03 | 0 | <0.01 | <0.01 | 0 |
| **KUOS** | **all** | **13.31** | **1.32** | **129** | **0.47** | **0.04** | **0.01** | **0.66** | **<0.01** | **0.12** | **0.01** | **0.01** |
| KUOZ | zakład opieki socjalnej lub dom dziecka | 0.79 | 0.12 | 11 | 0.03 | 0.02 | <0.01 | 0.06 | 0 | <0.01 | <0.01 | <0.01 |
| KUOZ | zespół szpitalny lub sanatoryjny | 1.98 | 0.39 | 8 | 0.05 | 0.15 | 0 | 0.18 | <0.01 | 0.01 | <0.01 | <0.01 |
| KUOZ | żłobek | 0.07 | 0.03 | 3 | 0.01 | 0 | 0 | 0.01 | 0 | <0.01 | 0 | 0 |
| **KUOZ** | **all** | **2.84** | **0.54** | **22** | **0.10** | **0.17** | **<0.01** | **0.25** | **<0.01** | **0.01** | **<0.01** | **<0.01** |
| KUZA | miejsce pamięci narodowej | 0.04 | 0.01 | 1 | <0.01 | <0.01 | 0 | 0 | 0 | 0 | 0 | 0 |
| KUZA | skansen | 0.47 | 0.36 | 4 | 0.16 | 0.06 | 0.05 | 0.08 | 0 | <0.01 | <0.01 | 0 |
| KUZA | twierdza lub forteca | 0.74 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| KUZA | zespół muzealny | 0.50 | 0.31 | 5 | 0.14 | 0.09 | 0 | 0.05 | <0.01 | 0.01 | 0.01 | 0.01 |
| KUZA | zespół zabudowy historycznej | 2.49 | 0.58 | 20 | 0.09 | 0.35 | <0.01 | 0.10 | <0.01 | <0.01 | 0.04 | 0.01 |
| **KUZA** | **all** | **4.25** | **1.25** | **30** | **0.39** | **0.51** | **0.05** | **0.22** | **<0.01** | **0.01** | **0.04** | **0.01** |
| KUMN | (no attribute) | 21.12 | 1.41 | 25 | 0.47 | 0.03 | <0.01 | 0.88 | 0.01 | <0.01 | <0.01 | 0.02 |
| KUHO | hotel lub motel | 1.36 | 0.31 | 14 | 0.11 | 0.09 | 0 | 0.08 | 0.01 | 0.01 | 0.01 | 0.01 |
| KUHO | kemping | 0.39 | 0.06 | 3 | 0.01 | 0.02 | 0 | 0.03 | 0 | 0 | 0 | 0 |
| KUHO | ośrodek wypoczynkowy | 1.91 | 0.23 | 11 | 0.05 | 0.07 | 0 | 0.10 | 0 | <0.01 | 0 | <0.01 |
| **KUHO** | **all** | **3.67** | **0.60** | **28** | **0.17** | **0.18** | **0** | **0.21** | **0.01** | **0.01** | **0.01** | **0.01** |
| KUHU | (no attribute) | 0.41 | 0.05 | 6 | 0.01 | 0 | 0 | 0 | <0.01 | 0.02 | 0 | 0.03 |
| KUPW | (no attribute) | 84.63 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Under the wetlands of h07 the soil groups of the set's HSG raster (as step 5 warps it,
250 m) were B on 38.74 km² and A on 0.81 km²; none is C or D. Read by layer:

- **OIMK:** 1.3% of h07, nearly all "teren podmokły"; 75% of it is grass (PTTR roślinność
  trawiasta 25.61 km², PTRK 3.95), 24% forest, 0.7% arable land.
- **KUSK:** the parks of h07 are 77% forest (3.67 of 4.74 km²) and 14% grass; the sports
  and recreation complexes are 74% grass (0.62 of 0.84); the summer house estates are 75%
  built-up (1.87 of 2.49). The botanical and zoological gardens lie outside h07 (Poznań):
  in the packages 45% and 40% forest, 45% and 32% grass.
- **KUKO:** the two airports and landing fields of h07 (`TYPLOTNISKA` "inne lotnisko lub
  lądowisko") are 69% grass, 17% forest, 9% arable land and 4% paved; the stations, car
  parks, petrol stations, depots and service areas are paved or built-up, with 0.16 km² of
  grass between them.
- **The other layers** are left by the author's decision: KUPG (whose industrial kinds
  ADR-074 decided), KUSC, KUOS, KUOZ, KUZA, KUMN, KUHO, KUHU and KUPW (military training
  grounds, none in h07).

## Options considered

The wetlands:

- **D under the wetland, the land cover kept (chosen, the author's decision).** A wetland
  that BDOT10k maps is wet land in its natural, undrained state, the second letter of a
  dual group. The cover of the partition stays: a wet meadow is a meadow, a wet forest a
  forest, and TR-55 has no wetland cover.
- **A dual group taken as drained (A/D as A, B/D as B):** rejected; the land is mapped as
  wet, so it is not drained.
- **A wetland category of `land_cover`:** rejected by the author's decision; it would also
  need a TR-55 row that does not exist.
- **Where the soil becomes D.** In bootstrap step 5, which builds `soil_hsg`: chosen. The
  soil polygons are cut at the wetland outlines, so `soil_hsg` stays a partition and the
  CN of ADR-075 reads it unchanged. A wetland table that the CN query reads as a third
  overlay: rejected (a migration, and the query of the panel would change). Wetlands
  written into `soil_hsg` by the land cover import: rejected; step 5 runs after step 4
  and replaces `soil_hsg` in its box.

The complexes:

- **What a complex replaces.** Everything but water and paved surfaces, as an industrial
  complex replaces all but water and industrial land: rejected after the measurement. The
  parks of h07 are 77% forest, and their woods (55 on group B) would become open space
  (61), although TR-55 has a cover for woods; a park of trees and lawns is in TR-55 the
  composite of woods and open space (table 2-2a, footnote 3: the CN of open space is that
  of pasture, composites are computed for other combinations). Fields, buildings and the
  `inny` land with a row of its own (dirt, graded land) are described better by their own
  covers too. **Only the grass (`łąka`): chosen.** The complex tells what its grass is: a
  lawn, mown and walked on, the open space of TR-55, not a meadow mowed for hay. The paved
  surfaces stay paved through PT, as the author decided for the airports, and so do the
  buildings, the water, the forest and the fields.
- **The condition of the open space.** Fair (grass cover 50 to 75%), the cover of `inny`
  in ADR-075: rejected; `inny` is technical land, wasteland and solar farms. **Good (grass
  cover above 75%): chosen.** The lawns of sports grounds, parks and airfields are mown
  turf, and TR-55 counts the pervious land of its urban districts as open space in good
  condition (table 2-2a, footnote 2). On group B: meadow 58, open space good 61, fair 69.
- **The kinds.** KUSK kompleks sportowo-rekreacyjny and park lub skwer: mapped. KUSK ogród
  botaniczny and ogród zoologiczny: mapped as parks with collections (none in h07). KUSK
  zespół domów letniskowych: not mapped: it is built-up land, not a sports or recreation
  ground, and its lawns are those that the residential districts of TR-55 already hold.
  KUKO lotnisko lub lądowisko: mapped. The other KUKO kinds (bus and railway stations, car
  parks, petrol stations, depots, service areas, ports): not mapped: their paved part is
  the PT's already, and their grass is the verge of their paved land.
- **The category of a lawn.** `inny`, whose TR-55 cover is open space (ADR-075), with the
  complex in `bdot_class` and a cover of its own: chosen. A new category: rejected (a
  migration, the constraint, the legends and the panel for 0.1% of h07). Lutz's W and U
  do not count `inny`, as they did not count `łąka`.

## Decision

1. **Wetlands, step 5** (`scripts/bootstrap.py`, `step_soil_hsg`; `read_wetlands` and
   `soils_with_wetlands` in `scripts/import_landcover.py`): the polygons of the HSG raster
   are cut at the wetlands of `OT_OIMK_A`, every kind, of the BDOT10k packages of step 4 (a
   set's packages, else those of the area, which steps 3 and 4 stored): the part inside a
   wetland becomes D, the rest keeps its group; the pieces of a polygon cover it exactly,
   and a polygon of group D stays whole. Step 5 replaces `soil_hsg` in its box as before,
   so a second run writes the same rows. Without a package the groups of the raster stay
   and the step says so (`bez mokradeł`). The map layer `frontend/data/soil_hsg.geojson` is
   simplified by 5 m and written with 6 decimal digits; the table keeps the exact polygons.
2. **Lawns, step 4** (`scripts/import_landcover.py`): after the industrial complexes of
   ADR-074, the complexes of `OPEN_SPACE_COMPLEX_CLASSES` are made disjoint (KUKO first, a
   complex keeps its part outside the earlier ones) and cut out of the `łąka` polygons and
   pieces of the partition; the pieces inside become `inny`, imperviousness 0.0, with
   `bdot_class`:

   | Layer | Kind (`RODZAJ`) | `bdot_class` |
   |---|---|---|
   | OT_KUKO_A | lotnisko lub lądowisko | `KUKO:lotnisko` |
   | OT_KUSK_A | kompleks sportowo-rekreacyjny | `KUSK:kompl. sport.` |
   | OT_KUSK_A | park lub skwer | `KUSK:park` |
   | OT_KUSK_A | ogród botaniczny | `KUSK:ogród botan.` |
   | OT_KUSK_A | ogród zoologiczny | `KUSK:ogród zoolog.` |

   Every other polygon and kind keeps its class. The pieces of the package still cover the
   PT layers exactly, and the import replaces the rows of the package by the rule of
   ADR-074, those of the earlier mapping too.
3. **CN** (`core/cn_tables.py`): the five sources above take TR-55 open space in good
   condition, 39/61/74/80; the land cover under a wetland takes its cover on group D.
4. Every other complex, and the land cover under a wetland, stays as ADR-074 has it.

## Consequences

Measured with the code of this decision on h07/2026-3: the land cover of the packages
with ADR-074's mapping and with this decision, the soil groups of the set's raster as step
5 makes them before and after the wetlands, the CN of `core/cn_tables.py` (Hydrolog's
TR-55 values), per catchment of h07:

| Change | km² in h07 | CN on group B (A) before → after | Area-weighted CN of h07 |
|---|---:|---|---:|
| wet meadow (PTTR roślinność trawiasta, PTRK) to D | 29.53 | 58 → 78 (30 → 78) | +0.206 |
| wet forest to D | 9.68 | 55 → 77 (30 → 77) | +0.074 |
| wet arable land to D | 0.29 | 75 → 87 (63 → 87) | +0.001 |
| wet lawns of the complexes | 0.03 | 58 → 80 | <0.001 |
| lawns of the complexes, not wet | 2.78 | 58 → 61 (30 → 39) | +0.003 |
| **all** | | | **+0.285** |

- The area-weighted CN of h07 rises by 0.3 (it was 69.1 after ADR-074 and ADR-075). By
  catchment: median +0.18; among the 203 catchments of at least 1 km² the 90th
  percentile is +0.66 and the largest +2.96 (1866927, Zlewnia jez. Maciejak, 1.81 km²),
  12 rise by more than 1; the 0.002 km² catchment 1865259, all wet meadow, by 20; 26 of
  the 223 do not change. Almost all of it is the wetlands (+0.28); the lawns change the
  grass of 2.8 km² by 3 on group B.
- Cross-checked through the database (a throwaway PostGIS; county 3028 imported with
  ADR-074's mapping, step 5 without the wetlands, then both with this decision): the CN of
  the panel for 1865251 (Zlewnia jez. Łękno, 10.21 km²) goes from 73.2 to 74.7, the
  estimate above +1.46; the wetlands alone change the CN of 92 catchments of the county
  by 0 to +2.9. The import with this decision replaced the 16,718 rows of the county by
  16,740 (31 lawns: 8 sports complexes, 23 parks), the area unchanged (1,038.5491 km²);
  a second import replaced 16,740 by 16,740, and a second step 5 wrote the same rows.
- Step 5 over the h07 box (5,534 km², the 13 packages, 14,748 wetlands): 89.50 km² of the
  box becomes D (39.55 km² of it in h07), in 8 to 9 s; `soil_hsg` has 556 polygons instead
  of 461 (95 of group D), 488,764 vertices instead of 8,052; they are valid and cover the
  box exactly, as before. The map layer is 4.6 MB instead of 0.25 MB (14.7 MB without the
  simplification).
- The land cover query of the panel follows the wetland outlines: on the 92 catchments of
  county 3028 it takes a median 0.39 s instead of 0.09 s, at most 1.2 s instead of 0.36
  s. Splitting `soil_hsg` into pieces of at most 256 vertices (`ST_Subdivide`, 10,739
  rows) does not make it faster (0.46 s): the cost is the pieces of soil that every land
  cover row of the watershed now meets.
- The Kartograf path of `analyze_watershed` (ADR-075, decision 6) keeps the soil groups of
  SoilGrids and the shares of the PT layers.
- An instance changes at its next import of the packages (step 4) and step 5: Hydroni at
  its re-bootstrap from h07/2026-3; production (Kaczawa) at its reprocessing, where the
  change has not been measured.
- `bdot_class` of the lawns is at most 18 characters of `VARCHAR(20)`.
