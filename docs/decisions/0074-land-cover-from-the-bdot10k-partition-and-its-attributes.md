# ADR-074: The land cover is the BDOT10k partition split by its attributes, with the industrial complexes cut out of it

> **Amended by ADR-078 (2026-11-10):** the wetland overlay `OT_OIMK_A` is used, in the
> soil: bootstrap step 5 makes the soil under it hydrologic soil group D, and the land
> cover under it keeps its category. The sports and recreation complexes of `OT_KUSK_A`
> (kompleks sportowo-rekreacyjny, park lub skwer, ogród botaniczny, ogród zoologiczny)
> and the airports and landing fields of `OT_KUKO_A` are cut out of the grass (`łąka`)
> of the partition after the industrial complexes; their pieces become `inny`
> (`KUSK:<kind>`, `KUKO:lotnisko`, imperviousness 0.0), the lawns of TR-55's open space.
> Summer house estates and the other complexes keep the PT cover.

**Date:** 2026-11-08
**Status:** accepted (by delegation of the author, 2026-11-08; the open points decided by
the author 2026-11-08, below; plan `docs/plans/2026-11-08-landcover-industry.md`)

## Context

`scripts/import_landcover.py` wrote one category per BDOT10k layer of the category
"pokrycie terenu" (`OT_PT*_A`). Its CN feeds the panel, the export of catchment parameters
and the hydrograph, and the author's work on hydrological and soil drought in the 223
catchments h07 of the Hydroni instance.

The specification (Dz.U. 2021 poz. 1412, the regulation on BDOT10k) and the 13 county
packages of the Archiwista set h07/2026-2 (schema 2021) say:

- The PT layers form a partition: together they cover 100% of the county and do not
  overlap (Zał. 3, rozdz. 5, ust. 1-2). In h07 they sum to 2,940.69 km², the area of the
  223 catchments. The land use complexes (KU) are drawn independently of the land cover,
  with an approximate boundary, and overlap it (Zał. 3, rozdz. 7, ust. 2-4).
- Four PT layers carry the attribute that divides them (Zał. 1; Zał. 3, rozdz. 5, tables
  14, 18, 21, 24), present in every package:
  - PTZB "zabudowa", `RODZAJ`: jednorodzinna 66.82 km² in h07, pozostała zabudowa 12.37,
    przemysłowo-składowa 6.62, wielorodzinna 5.45, handlowo-usługowa 1.60;
  - PTTR "roślinność trawiasta i uprawa rolna", `RODZAJ`: uprawa na gruntach ornych
    1,835.05, roślinność trawiasta 270.32 (meadows, pastures, grass of parks and
    estates: table 18 and ust. 9);
  - PTNZ "inny teren niezabudowany", `RODZAJ`: teren pod urządzeniami technicznymi lub
    budowlami 5.53 (3.29 of it under solar farms), teren przemysłowo-składowy 1.29;
  - PTPL "plac", `MATERIALNAWIERZCHNI`: paved 1.98, grunt naturalny 1.55, żwir 0.20,
    tłuczeń 0.13, inny 0.16.
- PTWZ is "wyrobisko i zwałowisko" (pits and spoil heaps, 1.53 km², all pits), not
  wetland: wetland is the overlay OT_OIMK_A "mokradło". PTUT is "uprawa trwała": allotment
  gardens 5.19, orchards 4.38, plantations 1.78, nurseries 1.50.
- The industrial complexes are OT_KUPG_A "kompleks przemysłowo-gospodarczy" with `RODZAJ`
  (table 45). In h07: gospodarstwo hodowlane 6.48 km², zakład produkcyjny, usługowy lub
  remontowy 5.70, elektrownia słoneczna 3.32, kopalnia 2.29, baza paliw 0.54,
  oczyszczalnia ścieków 0.40, składowisko odpadów 0.31, gazownia 0.026,
  elektrociepłownia 0.021, zakład utylizacji 0.010 and smaller ones. OT_KUHU_A is
  "bazar lub targowisko" (0.05 km²), not commercial land.

The old mapping therefore put PTZB (all kinds) into `zabudowa_mieszkaniowa`, so nothing
wrote `zabudowa_przemysłowa`; counted 270 km² of grassland as arable land; put the pits of
PTWZ into `łąka` as "wetland"; and counted orchards as arable land. The author had ruled
which complexes are industry: KUPG production, service or repair plants, fuel depots,
gasworks, combined heat and power plants and waste treatment plants, not solar or wind
farms or mines; that rule assumed that PTZB had no attribute of its own. Of the 5.69 km²
of production plants in h07, 3.32 km² is PTZB przemysłowo-składowa, 0.88 grass, 0.45 PTNZ
teren przemysłowo-składowy, 0.63 squares and 0.19 PTZB pozostała zabudowa.

The import was not idempotent either: the bootstrap imports each county with
`clear_existing=False`, and hydroni's `land_cover` holds every geometry twice (479,462
rows, 239,731 distinct geometries).

## Options considered

Industrial land:

- **The KUPG rule alone** (the author's kinds cut out of PT; PTZB stays housing): rejected
  as the whole rule. It leaves 2.4 km² of PTZB przemysłowo-składowa outside any complex
  (warehouses, depots, workshops) as housing, and the specification classifies the built-up
  land by its physiognomy (table 14: "rodzaj zabudowy ze względu na jej cechy
  fizjonomiczne").
- **The PT attribute alone** (PTZB przemysłowo-składowa and PTNZ teren
  przemysłowo-składowy): rejected as the whole rule. It drops the author's decision that the
  complex as a whole is industrial land, with its yards, lawns and squares, which is how
  TR-55 composes an urban district: the CN of "Industrial" (72% impervious) assumes the
  pervious rest is open space (USDA-SCS 1986, table 2-2a and its footnote 2).
- **Both: chosen.** The author's KUPG rule is kept and widened by the PT evidence: the PT
  kinds that are industrial land, and inside the complexes of the author's kinds all PT
  land but water.
- **Buildings (OT_BUBD_A, `FUNKCJAOGOLNABUDYNKU`)**: rejected. They are roofs, not land;
  PTZB is the land under the buildings with its surroundings (ust. 5).

The commercial kind of PTZB (handlowo-usługowa): `zabudowa_przemysłowa`, as CORINE Land
Cover's class 1.2.1 "Industrial or commercial units" groups them; of the TR-55 covers,
"Commercial and business" (85% impervious) is the nearest to "Industrial" (72%) and far
from the residential districts. `bdot_class` keeps it apart, so the CN can use the
commercial cover. `zabudowa_mieszkaniowa` was the alternative: rejected, a shopping centre
is not housing in any of the two sources. Decided by the author 2026-11-08: commercial
land stays in `zabudowa_przemysłowa`; `bdot_class` (`PTZB:handl.-usług.`) tells it apart.

Other complexes (KUKO airports, car parks and stations; KUSK parks and summer house
estates; KUOS, KUOZ, KUZA, KUHO, KUSC, KUMN, KUHU): not used. The partition already shows
their cover (an airport is mostly grass with paved runways), and TR-55 has no district of
their kind. The other KUPG kinds (farms, solar, wind and water power plants, mines,
treatment plants, landfills, waterworks, substations) keep the PT cover too; steelworks,
refineries, metallurgical plants and thermal and nuclear power plants, absent in h07,
are industry like a combined heat and power plant. Decided by the author 2026-11-08: the
solar farms keep their PT cover, `inny` (3.29 of their 3.32 km² in h07 lie on PTNZ teren
pod urządzeniami technicznymi lub budowlami).

Water under a complex: kept as water. A water surface is neither of the two covers that
the TR-55 districts combine; the KUPG boundary is approximate (it takes 0.02 km² of ponds
in h07).

The other PT layers:

- PTUT to `łąka`, not `grunt_orny`: TR-55 puts orchards and tree farms among the other
  agricultural lands ("Woods-grass combination", table 2-2c, CN 43/65/76/82 in fair
  condition), close to meadow (30/58/71/78) and pasture, not among the cultivated lands
  of table 2-2b. Allotment gardens are closer to that than to a field. Decided by the
  author 2026-11-08: PTUT stays `łąka`.
- PTRK stays `łąka`: brush (table 2-2c, 35/56/70/77 fair) is close to meadow.
- PTWZ to `inny`, with the other bare or disturbed land (PTGN, PTSO).
- PTPL by its surface: natural ground, gravel and crushed stone to `inny`, the paved
  surfaces to `droga`. TR-55 gives gravel and dirt 85 and 82 for soil group B, paved 98.
- The wetland overlay OT_OIMK_A: not used; a wet soil is the soil group's matter, and TR-55
  has no wetland cover.

Identifying the rows that a new import of a package replaces:

- **A `teryt` column**: rejected for now; it needs a migration, and the rows imported
  before it would carry none.
- **The rows whose interior point lies in the package**: rejected. Two neighbouring
  packages overlap by slivers along their border: the interior point of a 3.9 ha PTTR
  polygon of 3003 lies in a 1 m² overlap with 3021, and the import of 3021 deleted it.
- **The rows whose interior point and more than half of whose area lie in the package**:
  chosen. The area is computed only for rows that no record repeats exactly (13.9 s
  for the point test of the largest county, 3021, 39,257 rows; the area for every row
  would take 6 min).

## Decision

`scripts/import_landcover.py`:

- Category of a PT polygon by layer and attribute:

  | Source | Category | `bdot_class` | Imperviousness |
  |---|---|---|---|
  | PTZB jednorodzinna, pozostała zabudowa | `zabudowa_mieszkaniowa` | `PTZB:jednorodzinna`, `PTZB:pozostała` | 0.30 |
  | PTZB wielorodzinna | `zabudowa_mieszkaniowa` | `PTZB:wielorodzinna` | 0.65 |
  | PTZB przemysłowo-składowa | `zabudowa_przemysłowa` | `PTZB:przem.-skład.` | 0.72 |
  | PTZB handlowo-usługowa | `zabudowa_przemysłowa` | `PTZB:handl.-usług.` | 0.85 |
  | PTNZ teren przemysłowo-składowy | `zabudowa_przemysłowa` | `PTNZ:przem.-skład.` | 0.72 |
  | PTNZ teren pod urządzeniami technicznymi lub budowlami | `inny` | `PTNZ:urządzenia` | 0.2 |
  | PTTR uprawa na gruntach ornych | `grunt_orny` | `PTTR:grunty orne` | 0.1 |
  | PTTR roślinność trawiasta | `łąka` | `PTTR:trawiasta` | 0.0 |
  | PTPL beton, bruk, kostka, masa bitumiczna, płyty betonowe | `droga` | `PTPL:utwardzony` | 0.95 |
  | PTPL grunt naturalny, żwir, tłuczeń | `inny` | `PTPL:nieutwardzony` | 0.2 |
  | PTLZ | `las` | `PTLZ` | 0.0 |
  | PTUT, PTRK | `łąka` | `PTUT`, `PTRK` | 0.0 |
  | PTKM | `droga` | `PTKM` | 0.95 |
  | PTWP | `woda` | `PTWP` | 1.0 |
  | PTGN, PTSO, PTWZ, another PT layer | `inny` | its code | 0.2 |

  A polygon without the attribute or with another value takes its layer's first category
  and the plain layer code (PTZB `zabudowa_mieszkaniowa`, PTTR `grunt_orny`, PTNZ `inny`,
  PTPL `droga`); an unknown value is logged.
- The complexes of OT_KUPG_A of the kinds zakład produkcyjny, usługowy lub remontowy, baza
  paliw, gazownia, elektrociepłownia, zakład utylizacji, huta, rafineria, zakład
  metalurgiczny, and elektrownia with `RODZAJELEKTROWNI` cieplna or atomowa are made
  disjoint (a complex keeps only its part outside the earlier ones) and cut out of every
  PT polygon but water and industrial land. The pieces inside become
  `zabudowa_przemysłowa`, `bdot_class` `KUPG:<kind>` (`KUPG:zakład prod.`,
  `KUPG:baza paliw`, `KUPG:gazownia`, `KUPG:elektrociepł.`, `KUPG:zakład utyliz.`,
  `KUPG:huta`, `KUPG:rafineria`, `KUPG:zakład metal.`, `KUPG:el. cieplna`,
  `KUPG:el. atomowa`), imperviousness 0.72; the pieces outside keep their class. The
  pieces of a polygon cover it exactly, so the areas of the categories sum to the area of
  the PT layers.
- Imperviousness of the urban classes from TR-55, table 2-2a: industrial 72%, commercial
  and business 85%, residential 1/3 acre 30%, 1/8 acre 65% (the residential lot sizes are
  those that the CN of ADR-075 takes for the PTZB kinds); the others are unchanged.
- Invalid geometries are repaired with `make_valid`, which keeps all their area, not with
  `buffer(0)`, which keeps one lobe of a self-intersecting ring (2,500 of 5,000 m² for a
  100 m bow-tie).
- The import of a package runs in one transaction: its records go to a temporary table,
  the rows they replace (above) are deleted, the records are inserted.
  `--clear-existing` still empties the whole table first.
- `cn_value` is still written, one value per category (DATA_MODEL §3.3,
  `zabudowa_przemysłowa` 92); the CN of ADR-075 no longer reads it, and the branch merged
  second drops the column with `CATEGORY_CN`. Done when the two branches were merged
  (2026-11-08): migration 006 drops the column and the import no longer writes it.

## Consequences

Measured on the 13 packages of h07/2026-2, imported with the code of `develop` and with
this decision into a throwaway PostGIS, and intersected with the 223 catchments
(`Obszar_h07.gpkg`, 2,940.69 km²):

| Category | Before, km² | After, km² | Before, % | After, % |
|---|---:|---:|---:|---:|
| `grunt_orny` | 2,118.22 | 1,835.04 | 72.03 | 62.40 |
| `łąka` | 14.36 | 294.81 | 0.49 | 10.03 |
| `las` | 610.45 | 610.38 | 20.76 | 20.76 |
| `zabudowa_mieszkaniowa` | 92.85 | 84.40 | 3.16 | 2.87 |
| `zabudowa_przemysłowa` | 0 | 11.90 | 0 | 0.40 |
| `droga` | 21.30 | 18.94 | 0.72 | 0.64 |
| `woda` | 76.38 | 76.38 | 2.60 | 2.60 |
| `inny` | 7.13 | 8.84 | 0.24 | 0.30 |

- Industrial land in h07 is 11.90 km²: PTZB przemysłowo-składowa 6.62, PTZB
  handlowo-usługowa 1.60, PTNZ teren przemysłowo-składowy 1.29 and the parts of the
  complexes that were other land 2.40 (production plants 1.86, the fuel depot 0.52,
  gasworks, CHP plant and waste treatment 0.02). The author's KUPG rule alone gives
  6.28 km² (the complexes but their water); the PT evidence adds the 5.62 km² of PT
  industrial and commercial land outside them. 166 of the 203 catchments of at least
  1 km² have some; the largest share is 16.4% (Nielba od przecięcia z Wełną do ujścia,
  1.26 km²).
- Per catchment the share of `łąka` rises and that of `grunt_orny` falls by nearly the
  same amount: median 7.5 percentage points, 90th percentile 21.2, at most 58.8 in a
  catchment of at least 1 km² (Noteć od dopł. z Kaźmierzewa do Kcynki, 29.9 km²) and
  100 in the smallest one (0.002 km², all grass). The other shares change by a median of
  0.13 (`zabudowa_przemysłowa`), 0.09 (`zabudowa_mieszkaniowa`), 0.03 (`inny`) and 0.02
  (`droga`) points, at most 16.4, 13.1, 1.1 and 3.1 points; `las` by at most 0.2 (the
  forest inside the fuel depot) and `woda` not at all.
- With one CN per category (`cn_value`) the CN of every catchment falls, by a median of
  0.6 (0.05 to 4.7 in catchments of at least 1 km², 8.0 in a 0.002 km² one): the
  grassland weighs 70 instead of 78. The CN that ADR-075 computes from the category,
  `bdot_class` and the soil group is measured there.
- The rows are an exact partition of each package: the areas of the records equal the
  areas of the PT layers (13,790.02 km² for the 13 counties, the largest difference
  1.2·10⁻⁶ m² per county); 241,914 rows, all valid, 353 of them below 1 m² (53 m² in
  all: the edges of the complexes against the PT boundaries). Inside h07 the rows cover
  each catchment as before (from 593 m² short to 49 m² over: the packages of neighbouring
  counties leave slivers along their borders, unchanged by this decision).
- A second import of a package replaces its rows (3021: 39,257 replaced by 39,257;
  3016: 11,332 by 11,332); the import of 3021 replaces one 2.6 m² row of 3003 that lies
  wholly inside it. The 13 packages take 5 min instead of 1.5 min.
- The Hydroni land cover is imported again from the 13 packages, which also removes its
  duplicated rows. Until then the instance keeps the old categories.
- `bdot_class` is longer than a layer code (up to 19 characters of `VARCHAR(20)`); the
  map tiles and the point identification show it as it is.
- The other KU complexes and the wetland overlay stay unused (options above); a farm,
  a solar farm or a mine keeps the cover of its PT polygons.
