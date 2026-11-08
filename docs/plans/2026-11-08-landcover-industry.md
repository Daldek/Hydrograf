# Plan: the land cover follows the BDOT10k partition and its attributes; industry from PT and KUPG

Approved: 2026-11-08 (by delegation of the author)

Requirements: the author's goal of 2026-11-08 (land cover and CN of Hydrograf as
methodologically correct as the data allow, for the 223 catchments h07 of the Hydroni
instance) and the author's rule for industrial land (KUPG production, service or repair
plants, fuel depots, gasworks, combined heat and power plants and waste treatment plants;
not solar or wind farms, not mines). Decision ADR-074; the CN from the land cover and the
soil groups is ADR-075 (branch `feat/cn-by-soil-group`). Scope: the import of the land
cover (`backend/scripts/import_landcover.py`) and the content of the `land_cover` rows
(category, geometry, `bdot_class`, imperviousness); no schema change. Branch
`feat/landcover-industry`.

## Findings

Data: the 13 county packages of the Archiwista set h07/2026-2 (BDOT10k, schema 2021,
`versions/teryt/2026-11-06_*`); specification: Dz.U. 2021 poz. 1412 (the regulation on
BDOT10k), Zał. 1 (classes and classifying attributes), Zał. 3 rozdz. 5 (land cover) and
rozdz. 7 (land use complexes).

- **The PT layers are the partition.** They cover 100% of a county without overlapping
  (Zał. 3, rozdz. 5, ust. 1-2); in h07 they sum to 2,940.69 km², the area of the 223
  catchments. The KU complexes are drawn independently of the land cover, with an
  approximate boundary, and overlap it (rozdz. 7, ust. 2-4).
- **The import mapped whole layers.** PTZB went to `zabudowa_mieszkaniowa`; nothing wrote
  `zabudowa_przemysłowa`. The 2021 data have the attributes that the specification
  defines, in every package:

  | Layer, attribute | Values in h07 (km²) |
  |---|---|
  | PTZB `RODZAJ` (tab. 14) | jednorodzinna 66.82, pozostała zabudowa 12.37, przemysłowo-składowa 6.62, wielorodzinna 5.45, handlowo-usługowa 1.60 |
  | PTTR `RODZAJ` (tab. 18) | uprawa na gruntach ornych 1,835.05, roślinność trawiasta 270.32 |
  | PTNZ `RODZAJ` (tab. 24) | teren pod urządzeniami technicznymi lub budowlami 5.53, teren przemysłowo-składowy 1.29 |
  | PTPL `MATERIALNAWIERZCHNI` (tab. 21) | paved 1.98, grunt naturalny 1.55, żwir 0.20, tłuczeń 0.13, inny 0.16 |
  | PTUT `RODZAJ` (tab. 17) | ogródki działkowe 5.19, sad 4.38, plantacja 1.78, szkółka roślin 1.50 |
  | PTWZ `RODZAJ` (tab. 23) | wyrobisko 1.53 |

- **Errors of the old mapping.** PTTR grassland (270 km², 9.2% of h07) counted as arable
  land; PTWZ, which is "wyrobisko i zwałowisko" (pits and spoil heaps), was described as
  wetland and mapped to `łąka` (wetland is the overlay OT_OIMK_A, not a PT layer); the
  OT_KUHU_A of the earlier analysis is "bazar lub targowisko" (0.05 km²), not commercial
  land.
- **KUPG in h07.** gospodarstwo hodowlane 6.48 km², zakład produkcyjny, usługowy lub
  remontowy 5.70, elektrownia słoneczna 3.32, kopalnia 2.29, baza paliw 0.54, oczyszczalnia
  ścieków 0.40, składowisko odpadów 0.31, others below 0.1 (gazownia 0.026,
  elektrociepłownia 0.021, zakład utylizacji 0.010). Of the 5.69 km² of production
  plants, 3.32 is PTZB przemysłowo-składowa, 0.88 grass, 0.45 PTNZ teren
  przemysłowo-składowy, 0.63 squares, 0.19 PTZB pozostała zabudowa.
- **Not idempotent.** The bootstrap imports every county with `clear_existing=False`, so a
  second run doubled the rows: hydroni's `land_cover` holds every geometry twice (479,462
  rows, 239,731 distinct geometries; read-only check of the CN agent). Shares were
  unaffected, areas doubled.

## Method

1. Each PT polygon gets its category from its layer and, for PTZB, PTTR, PTNZ and PTPL,
   from the attribute (table in ADR-074). PTUT and PTRK go to `łąka` (TR-55, table 2-2c:
   orchards are "woods-grass combination", brush is close to meadow; neither is
   cultivated land); PTWZ to `inny`.
2. Industrial land is PTZB przemysłowo-składowa, PTZB handlowo-usługowa (commercial, kept
   apart in `bdot_class`), PTNZ teren przemysłowo-składowy, and the KUPG complexes of the
   author's kinds (plus steelworks, refineries, metallurgical plants, thermal and nuclear
   power plants, absent in h07): their area is cut out of the PT polygons, except water and
   land that is industrial already, so the rows stay a partition.
3. `bdot_class` records the source of every row (`PTZB:przem.-skład.`,
   `KUPG:baza paliw`, ...), so the CN can tell industrial from commercial land.
4. Imperviousness of the urban classes from TR-55, table 2-2a (industrial 0.72,
   commercial 0.85, residential 0.30, multi-family 0.65).
5. An import replaces the rows of its area in one transaction (rows whose interior point
   and more than half of whose area lie in the package: neighbouring packages overlap by
   slivers along their borders); `--clear-existing` still empties the table.

## Steps

1. ✅ `scripts/import_landcover.py`: the attribute split, the KUPG overlay, `bdot_class`,
   the imperviousness, the replacing import.
2. ✅ Tests: `tests/unit/test_import_landcover.py` (a synthetic GeoPackage: a plant over
   PTZB takes exactly its overlap; solar and wind farms, mines and farms change nothing;
   overlapping complexes count once; industrial land and water stay whole; the areas sum
   to the PT layers; the PTTR, PTZB and PTPL splits; layers without the attribute),
   `tests/integration/test_import_landcover_db.py` (marker `db`: a second import replaces
   its rows and keeps the neighbour's, also one whose interior point lies in the package).
3. ✅ ADR-074, DATA_MODEL §3.3, CHANGELOG, `backend/scripts/README.md`, the info texts of
   Lutz's W and U and of the urbanisation index.
4. ✅ Measurement on the 13 packages (below).
5. The Hydroni land cover imported again from the 13 packages: by the coordinator after the
   merge, not in this branch (it also removes the duplicated rows).

## Results (2026-11-08)

The 13 packages imported with the code of `develop` and of this branch into a throwaway
PostGIS (`docker compose -p lcind-measure`, removed afterwards), intersected with the 223
catchments of `Obszar_h07.gpkg` (2,940.69 km²); the table per category is in ADR-074,
Consequences. In short:

- `łąka` 14.36 → 294.81 km² and `grunt_orny` 2,118.22 → 1,835.04 km² (the grassland of
  PTTR, 269.14 km² after the complexes, and PTUT); `zabudowa_przemysłowa` 0 → 11.90 km²;
  `zabudowa_mieszkaniowa` 92.85 → 84.40; `droga` 21.30 → 18.94; `inny` 7.13 → 8.84;
  `las` and `woda` unchanged (−0.07 km² of forest inside the fuel depot).
- Per catchment: the shares of `łąka` and `grunt_orny` move by a median of 7.5
  percentage points (90th percentile 21.2; at most 58.8 in a catchment of at least
  1 km²); `zabudowa_przemysłowa` by a median of 0.13 (at most 16.4), the others by a
  median below 0.1.
- CN with one value per category: h07 75.15 → 74.41, every catchment lower (median −0.6).
- An exact partition: the records of the 13 packages sum to the 13,790.02 km² of their PT
  layers (largest difference 1.2·10⁻⁶ m² per county); a second import of 3021 and 3016
  replaced exactly its own rows.

## Open

- The other KU complexes, the buildings (OT_BUBD_A) and the wetland overlay (OT_OIMK_A)
  are not used (ADR-074, options); a farm, solar farm or mine keeps its PT cover.
- ✅ `cn_value` goes with ADR-075: the branch merged second drops the column and
  `CATEGORY_CN`. Done on `integrate/landcover-cn` (2026-11-08): migration 006.
