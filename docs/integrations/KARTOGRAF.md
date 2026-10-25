# Kartograf integration

**Version:** 7.0
**Date:** 2026-10-25
**Status:** Active (Kartograf 0.8.0.dev0, head `45dedf4`; ADR-061)

---

## 1. Overview

Hydrograf uses [Kartograf](https://github.com/Daldek/Kartograf) to download spatial data from
Polish and European sources and to do the arithmetic of the map sheet codes (*godła*). Kartograf
is a library dependency used through its public API. It is pinned by the commit of the head of its
`feature/data-output` branch (0.8.0.dev0, `45dedf4`), with the range `>=0.8.0.dev0,<0.9`, until the
0.8.0 tag exists; the release pull request replaces the commit with the tag (REL-5.3, REL-5.6,
ADR-060, ADR-061).

What Hydrograf takes from it:

| Data | Source | Used by |
|---|---|---|
| NMT (DEM), 5 m (or 1 m), EVRF2007, ESRI ASCII Grid | GUGiK OpenData | bootstrap step 2, `download_dem`, `prepare_area`, `analyze_watershed --download` |
| BDOT10k: one GeoPackage package per county (*powiat*), every layer | GUGiK | bootstrap steps 3 and 4, `download_landcover`, `prepare_area`, the CN calculation |
| HSG raster (hydrologic soil groups): Kartograf classifies the USDA texture of the SoilGrids clay, sand and silt rasters at 0-5 cm | ISRIC SoilGrids | bootstrap step 5, the CN calculation |
| CORINE Land Cover (raster, 44 classes) | Copernicus | only `download_landcover --provider corine`; nothing in the pipeline reads it |
| Sheet codes and their frames | the PL-1992 sheet system | `utils/sheet_lookup.py`, bootstrap, `download_dem` |

### 1.1 What Kartograf does

- Parses map sheet codes of the 1992 and 2000 systems and finds the sheets that cover a bbox or a
  geometry file (`SheetParser`, `find_sheets_for_bbox`, `find_sheets_for_geometry`).
- Downloads the NMT and NMPT from GUGiK OpenData by sheet code, with the choice of the flight
  (campaign), and orthophotos; expands a coarse sheet code into the 1:10000 sheets (in Kartograf's
  labels) it consists of.
- Downloads land cover: BDOT10k per county and CORINE.
- Downloads SoilGrids and computes the HSG raster (`download_landcover`, `calculate_hsg`,
  `hsg_statistics`).
- Writes everything either into a **store** (versions, a marker, a sidecar per file, hard-linked
  standard paths) or as **plain files** into a directory, the two targets of the data output
  convention (ECO-051, DEV §19).
- Retries transport failures, caches the answers of the GUGiK sheet index in a SQLite metadata cache
  and reports every failure as a `KartografError` with a code of the Nogat error registry and a hint.

Hydrograf does not call the NMPT, the orthophoto or the WCS download by bbox (`download_bbox`,
see §7.4).

### 1.2 Why the integration

| Problem | Solution |
|---|---|
| Manual download of the NMT from Geoportal | Automatic download by Kartograf |
| The user has to know the sheet codes | Coordinates (point + buffer, bbox, boundary file) to sheet codes |
| Many sheets for a large watershed | The neighbouring sheets are downloaded together |
| Inconsistent formats | One format: AAIGrid (`.asc`) for the DEM, GeoPackage for BDOT10k |
| No CN data for hydrographs | BDOT10k land cover and SoilGrids HSG |
| A re-run downloads everything again | A store: a local version is used without a request |
| Buildings disturb the flow directions | Building raising (ADR-033, §13) |

---

## 2. Architecture

```
operator / admin panel
    │  bbox (WGS84), sheet codes or a boundary file
    ▼
scripts/bootstrap.py   (10 steps; steps 2-5 use Kartograf)
    │
    ├─ step 2  scripts/download_dem.py ........ GugikProvider + DownloadManager(provider, root=)
    ├─ step 3  utils/kartograf_store.py ....... download_landcover(product="bdot10k", root=)
    │          (the hydro layers of the counties of the mosaic, for stream burning)
    ├─ step 4  utils/kartograf_store.py ....... the same packages, imported into land_cover
    └─ step 5  calculate_hsg(root=, bbox=Poland, depth="0-5cm")
                          │
                          ▼
        Kartograf store  <cache_dir>/kartograf/            metadata cache  <cache_dir>/kartograf_meta.db
          nmt/  landcover/  hsg/  soil/
                          │
    step 3: VRT mosaic of the sheet paths of step 2 ──► process_dem.py ──► PostGIS
            (stream_network, stream_catchments)
    step 4: import_landcover.py (county packages) ──► land_cover
    step 5: clip + warp + polygonize the HSG raster ──► soil_hsg

core/cn_calculator.py (CN on demand, `analyze_watershed`):
    calculate_hsg(output_dir=<temporary directory>)  ──► a plain file, nothing stays
    download_landcover(...)                          ──► the store, the same packages as bootstrap
```

---

## 3. The store of the pipeline

### 3.1 Two targets (ADR-061)

Kartograf writes either into a store (`root`) or as plain files (`output_dir`); a call that names
neither would write the default store in the data directory of the user, so **every script of
Hydrograf passes `root=` or `output_dir=` and `cache=` explicitly** and none relies on
`KARTOGRAF_ROOT` or on the default store. The decision per call site:

| Call site | Target | Reason |
|---|---|---|
| NMT sheets (`download_dem.download_sheets`: bootstrap step 2, `analyze_watershed --download`, `prepare_area`, the `download_dem` script) | store, `DownloadManager(provider, root=)` | a re-run skips the local sheets; the newest flight is used also when it is partial (border and coast sheets); the standard path is stable |
| BDOT10k packages (bootstrap steps 3 and 4, `prepare_area`, the land cover of the CN calculation, the `download_landcover` script) | store, `download_landcover(product="bdot10k", root=)` | a county is 100 MB or more and is reused by the pipeline and by the CN calculation |
| HSG raster of Poland (bootstrap step 5) | store, `calculate_hsg(root=, bbox=, depth="0-5cm")` | fetched once, `reused` after |
| HSG raster of one analysis (`get_hsg_from_soilgrids`) | plain files, `calculate_hsg(output_dir=<temporary directory>, cache=False)` | used once; the inputs go to Kartograf's staging directory and nothing stays |
| `prepare_area` | its own store `<output>/kartograf` | a stand-alone script with a working directory |

The store of the pipeline is `<cache_dir>/kartograf` (`paths.cache_dir`, default `cache/`;
`bootstrap --cache-dir`). It is a directory of its own: Kartograf refuses a root that holds other
files (`conflict`, reason `not_empty`) and a root that has the layout of a store and no marker
(`store_unavailable`, hint `kartograf store init --root DIR`). A new or empty directory becomes a
store: Kartograf writes the marker on the first write.

A plain directory would leave out a sheet that has no full flight, would take an older full flight
for a sheet whose newest flight is partial, and would refuse a second run (`conflict`,
`output_exists`); that is why the NMT and the BDOT10k go to the store (ADR-061).

### 3.2 Layout

Measured on the pinned Kartograf with the offline stubs of the tests:

```
<cache_dir>/kartograf/
├── kartograf-store.json                       marker: schema kartograf-store/1, tool, created_at, producer_version
├── nmt/pl_1992_5m_evrf2007/
│   ├── N-34/131/C/c/2/1/N-34-131-C-c-2-1.asc            standard path: a hard link to the newest flight
│   ├── N-34/131/C/c/2/1/N-34-131-C-c-2-1.asc.meta.json  its sidecar
│   ├── full_sheet/N-34/131/C/c/2/1/…                    link to the newest FULL flight (absent without one)
│   └── versions/N-34/131/C/c/2/1/2022-05-10_83233_0a7ed810/N-34-131-C-c-2-1.asc  (+ .meta.json)
├── landcover/pl_bdot10k_gpkg/
│   ├── teryt/1465.gpkg                                  the package of a county (+ .meta.json)
│   └── versions/teryt/2026-10-25_c7dda0dc/1465.gpkg     (+ .meta.json)
├── hsg/global_soilgrids_0-5cm_mean/
│   ├── bbox/<minx>_<miny>_<maxx>_<maxy>.tif             the HSG raster of a bbox (+ .meta.json)
│   └── versions/bbox/2.0_c12e8726/…
└── soil/global_soilgrids_{clay,sand,silt}_0-5cm_mean/   the SoilGrids inputs of the HSG raster
    └── bbox/…  and  versions/bbox/…
<cache_dir>/kartograf_meta.db  (+ -wal, -shm)  the metadata cache, beside the store
```

`nmt/pl_<system>_<resolution>_evrf2007/<hierarchy>/<sheet>.asc`: the hierarchy is the sheet code
split at the dashes without the last component (`N-34-131-C-c-2-1` is
`N-34/131/C/c/2/1/N-34-131-C-c-2-1.asc`). The 1 m DEM is `pl_1992_1m_evrf2007`. The last directory
of the hierarchy is the sheet of Kartograf's label `1:10000`, which is officially 1:5000 (§6).

### 3.3 Versions and sidecars

Every file is a **version** under `versions/` with a sidecar `<file>.meta.json` (schema
`kartograf-meta/1`); the standard path and the `full_sheet/` link are hard links to it, so the names
of one flight share one inode. The sidecar holds, among others: `dataset`
(`pl.gugik.nmt_5m`, `pl.gugik.bdot10k`, `global.isric.soilgrids`), `provider`, `horizontal_crs`,
`request`, `license`, `downloaded_at`, `kartograf_version`, `sha256`, `size_bytes` and `extra`:

- NMT: `extra.source` (the OpenData URL, the index layer, `acquisition_date`, `full_sheet`, ...),
  `extra.campaign` (`id`, `date`), `extra.version.label` (`<date>_<campaign>`), `extra.link`
  (`hardlink`) and `extra.link_target`.
- BDOT10k: `extra.source` (URL, `teryt`, `format`), `extra.http` and `extra.version.label`, which is
  the download date (BDOT10k publishes no version of its data).
- HSG: `extra.derived == "hsg"`, `depth`, `stat`, `classes` (`1=A, 2=B, 3=C, 4=D`), the
  `source_files` with their `sha256` and `extra.version.label` (the SoilGrids edition).

A version is written once; a second run answers `local` and transfers nothing, `update="force"`
(`--no-skip-existing`) fetches again and answers `unchanged` when the content is the same or writes a
new version. Hydrograf uses no other update mode: it does not fetch newer flights
(`update="upgrade"`).

**A store needs hard links.** The cache directory cannot be on FAT, exFAT or SMB. Copy the tree only
with the hard links preserved (`rsync -aH`, `cp -a`): a copy without them splits a standard path and
its version into independent files, which doubles the space.

### 3.4 Metadata cache

`<cache_dir>/kartograf_meta.db` (SQLite WAL) keeps the answers of the GUGiK sheet index and of the
county register, with a TTL of 7 days (the default of `MetadataCache`). It must be on a local disk,
never on a network share, and it stays **beside** the store, not in it: the store would refuse a
foreign file. The directory must exist: `download_dem` does not create it and raises
`NmtDownloadError` before any download (`open_metadata_cache` in `utils/kartograf_store.py` creates
it). A cache that SQLite disables (`on_disabled`) is an error of the NMT download, not a silent
degradation.

### 3.5 Cleaning

`python -m scripts.clean --include-cache` (and the `cache` target of the admin panel) removes the
large products of the store that Kartograf fetches again, `nmt/` and `landcover/`, with
`kartograf_meta.db*`, and keeps `hsg/`, `soil/` and the marker (small, Poland-wide, reusable), so
what is left is still a valid store. It also removes the directories of the 0.7.0 layout (§3.6).

### 3.6 No migration from the 0.7.0 layout

Kartograf 0.7.0 wrote `cache/nmt/pl_<system>_<res>_evrf2007/` (+ `kampanie/`),
`cache/bdot10k/bdot10k_teryt_<code>.gpkg` and `cache/soil_hsg/hsg_poland.tif`. The heads are
unreleased and there is no data migration: Hydrograf does not read these directories, the first run
downloads into `cache/kartograf/`, and the cache clean removes the old directories whole (ADR-061,
erratum of 2026-10-25). Data of the 0.6.1 layout (`nmt_1m/`, `nmt_5m/`) was not reusable even in
0.7.0.

---

## 4. Components

### 4.1 `utils/kartograf_store.py`

Where Kartograf writes and how its answers are read. It builds paths without importing Kartograf, so
a script that needs only a path does not load it.

| Name | Meaning |
|---|---|
| `store_dir(cache_dir)` | `<cache_dir>/kartograf` |
| `metadata_cache_path(cache_dir)` | `<cache_dir>/kartograf_meta.db` |
| `open_metadata_cache(cache_dir)` | opens the `MetadataCache` (creates the directory; logs when SQLite disables it) |
| `SHEET_SYSTEM = "1992"` | the sheet grid of Hydrograf, PL-1992 (EPSG:2180); the find functions of Kartograf require it |
| `HSG_DEPTH = "0-5cm"` | the depth of the SoilGrids layers of the HSG |
| `describe_error(error)` | the text of a failure for a log line: `<message> [<code>] <hint>` for a `KartografError` |
| `download_bdot10k(cache_dir, teryt=, bbox=)` | the packages of one county or of every county that a bbox intersects, as `{teryt: path}`; a failed county is logged and left out; an area without counties gives `{}` |

### 4.2 `utils/sheet_lookup.py`

Converts a point and a buffer into sheet codes. Since ADR-057 Hydrograf does not reimplement the
sheet arithmetic: the module is a thin wrapper over `kartograf.find_sheets_for_bbox()` (WGS84 to
EPSG:2180 with `transform_wgs84_to_pl1992()`, a `kartograf.BBox`, the call). It replaced the removed
`utils/sheet_finder.py`, which split a 1:25000 sheet into 1:10000 sheets with a 2 x 4 grid instead of
the nested 2 x 2 of GUGiK and returned wrong codes.

| Function | Meaning |
|---|---|
| `point_buffer_bbox(lat, lon, buffer_km)` | the square of `buffer_km` around the point, as a `BBox` in EPSG:2180; the land cover downloads use it too |
| `sheets_for_point_buffer(lat, lon, buffer_km, scale="1:10000")` | the sorted sheet codes that cover the square |

```python
from utils.sheet_lookup import sheets_for_point_buffer

sheets = sheets_for_point_buffer(52.23, 21.01, buffer_km=5)
# -> ["N-34-131-C-c-1-4", "N-34-131-C-c-2-1", "N-34-131-C-c-2-2", ...]
```

### 4.3 `scripts/download_dem.py`

Downloads the NMT into the store. `download_sheets(sheets, root, metadata_cache_path,
skip_existing=True, resolution="5m")` builds `GugikProvider(vertical_crs="EVRF2007",
resolution=..., cache=...)` and `DownloadManager(provider, root=root)`, calls
`download_sheets(sheets, update=None | "force")` and returns an `NmtDownloadReport`: `paths` (the
standard path of each sheet, new or already local), `no_coverage` and `unverified`.
`download_for_point` and `download_for_geometry` find the sheets first.

```bash
cd backend
python -m scripts.download_dem --lat 52.23 --lon 21.01 --buffer 5 \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db
python -m scripts.download_dem --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2 \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db
python -m scripts.download_dem --geometry ../data/boundary.gpkg \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db
```

| Option | Meaning | Default |
|---|---|---|
| `--lat`, `--lon`, `--buffer` | the centre (WGS84) and the buffer radius in km | buffer 5 |
| `--sheets` | sheet codes to download | - |
| `--geometry`, `--layer` | an SHP/GPKG file to select the sheets, and a GPKG layer | first layer |
| `--root` | the Kartograf store | `../cache/kartograf` |
| `--metadata-cache` | the SQLite metadata cache (local disk, outside `--root`) | required to download |
| `--scale` | the sheet scale in Kartograf's labels (`1:10000`, `1:25000`, `1:50000`, `1:100000`, §6) | `1:10000` |
| `--no-skip-existing` | fetch again although a version is local | off |
| `--dry-run` | show the plan, download nothing | off |

The format is always ASC (ESRI ASCII Grid, OpenData); there is no `--format`.

### 4.4 `scripts/download_landcover.py`

`fetch_landcover(root, provider="bdot10k", teryt=, godlo=, lat=, lon=, buffer_km=, year=2018,
skip_existing=True, metadata_cache_path=)` calls `kartograf.download_landcover(product=..., root=...)`
with a `teryt`, a `sheet` or the `bbox` of the square around a point, and returns a
`LandCoverReport` (`files`, `failed`, `ok`). A bbox gets every county it intersects; the file of a
county is `landcover/pl_bdot10k_gpkg/teryt/<teryt>.gpkg`. `merge_hydro_gpkgs()` merges the hydro
layers of several packages (§12).

```bash
python -m scripts.download_landcover --lat 52.23 --lon 21.01 --buffer 5 --root ../cache/kartograf
python -m scripts.download_landcover --teryt 1465 --root ../cache/kartograf
python -m scripts.download_landcover --lat 52.23 --lon 21.01 --provider corine --year 2018
```

| Option | Meaning | Default |
|---|---|---|
| `--teryt` / `--godlo` / `--lat` + `--lon` | the area: a 4-digit county code, a sheet code or a point | one is required |
| `--buffer` | the buffer radius in km | 5 |
| `--provider`, `-p` | `bdot10k` or `corine` | `bdot10k` |
| `--year` | the CORINE reference year (1990, 2000, 2006, 2012, 2018) | 2018 |
| `--root` | the Kartograf store | `../cache/kartograf` |
| `--metadata-cache` | the SQLite metadata cache | none |
| `--no-skip-existing` | fetch again although a version is local | off |
| `--dry-run` | show the plan, download nothing | off |

The exit code is 1 when the download failed or a county failed.

### 4.5 `scripts/bootstrap.py`

The orchestrator of the whole preprocessing (10 steps: infrastructure, NMT, DEM processing, land
cover, HSG, precipitation, depressions, MVT tiles, overlays, server). Steps 1-3 are critical, steps
4-10 are optional and the pipeline continues when one fails.

| Step | Kartograf | On failure |
|---|---|---|
| area | `SheetParser(code).get_bbox()` for `--sheets`; `find_sheets_for_bbox(bbox, scale, sheet_system="1992")` for `--bbox`; `find_sheets_for_geometry` for an SHP/GPKG `--boundary-file`, the bbox of the geometry for other formats | an invalid bbox or sheet code is a CLI error (exit 2) |
| 2 NMT | `download_sheets(sheets, <cache>/kartograf, <cache>/kartograf_meta.db, resolution=--resolution)` | the step fails, the exit code is 1 |
| 3 DEM | the VRT mosaic is built **from the paths that step 2 returned** (never from a directory scan: the store keeps every version under `versions/`); then `download_bdot10k` for the extent of the mosaic and `merge_hydro_gpkgs` for stream burning | a failed hydro download only logs a warning: no burning |
| 4 land cover | `download_bdot10k(cache_dir, bbox=mosaic)`: the packages that step 3 stored are local and are not requested again; each is imported by `import_landcover` | the step fails, `describe_error` gives the code and the hint; the pipeline continues |
| 5 HSG | `calculate_hsg(root=, bbox=<Poland>, depth="0-5cm", cache=)`: the raster of Poland is a version of the store; then clip to the mosaic, warp to EPSG:2180 at 250 m, nearest-neighbour fill, polygonize and import into `soil_hsg` (a DELETE limited to the bbox first) | a `KartografError` ends the step as "skipped" with its code; any other error fails it; the pipeline continues |

The exit code is 1 only when one of steps 1-3 failed. Whether a failed step 5 should stop the
bootstrap and whether the HSG fallback "B" is right are open (PROGRESS, Open questions 3).

### 4.6 `scripts/prepare_area.py`

A pipeline for one area (point + buffer): NMT download, VRT mosaic, optional BDOT10k hydro for burning
(`--with-hydro`), `process_dem`, optional land cover (`--with-landcover`). Its store is
`<output>/kartograf` with `--output` defaulting to `../data/nmt` (a temporary directory with
`--no-keep-downloads`), and its metadata cache is `<output>/kartograf_meta.db`. It uses `SheetParser`
and `BBox` to get the bbox of the sheets. There is no `--landcover-provider` (CORINE by county never
worked in 0.7.0).

### 4.7 `core/cn_calculator.py`

The CN calculation with Kartograf data. `determine_cn()` (`core/land_cover.py`) calls it as the third
source, after an explicit CN and the `land_cover` table, when `use_kartograf` is true and
`boundary_wgs84` and `cache_dir` are given; only `scripts/analyze_watershed.py` calls it.

| Function | Meaning |
|---|---|
| `check_kartograf_available()` | whether `BBox`, `calculate_hsg`, `download_landcover` and `hsg_statistics` import |
| `convert_boundary_to_bbox(boundary_wgs84, buffer_m=100)` | the boundary of the watershed (WGS84) as a `BBox` in EPSG:2180 |
| `get_hsg_from_soilgrids(bbox)` | `calculate_hsg(output_dir=<temporary directory>, bbox=, depth="0-5cm", cache=False)` and `hsg_statistics` of the file; the dominant group and the shares of A-D. A Kartograf failure or an area without data gives group B |
| `get_land_cover_stats(bbox, cache_dir, teryt=None)` | the BDOT10k packages of the store (`download_bdot10k`), the area of every PT layer clipped to the bbox, in percent per category; every county the bbox intersects counts, each by its part in the bbox. A `KartografError` of the download gives `{}` with a warning; any other error of the download reaches `calculate_cn_from_kartograf`, which logs it as an error and returns `None`; a package that cannot be read counts as no data (warning) |
| `calculate_cn_from_kartograf(boundary_wgs84, cache_dir, use_default_land_cover=True, teryt=None)` | the weighted CN |

`hsg_statistics` of a raster without a sidecar counts the whole raster, so the cells at the edge of
the bbox count in full, as in 0.7.0; in the store the sidecar would give area weights (ADR-061,
erratum of 2026-10-25).

### 4.8 `scripts/analyze_watershed.py`

`--download` downloads the NMT through `download_nmt_data` into `<cache_dir>/kartograf`
(`AnalysisConfig.cache_dir`, default `../cache`, next to `data_dir`, default `../data`).
`find_existing_nmt_files(cache_dir, resolution)` reads the store through its read API: the standard
paths (`kind == "link"`) of the segments `nmt/pl_*_<resolution>_evrf2007` from `iter_store` and
`list_segments`, so it lists neither `versions/` nor `full_sheet/`, other resolutions or the `.prj`
files that `normalize_crs()` writes (§4.9).

### 4.9 `utils/raster_utils.py`

`normalize_crs()` reprojects PUWG 2000 sheets to EPSG:2180 and writes a `<sheet>.prj` beside the file
of an EPSG:2180 sheet so that GDAL knows its CRS; for a sheet of the store that file lands next to
the standard path. `iter_store` reports it as a `problem` entry (`missing_sidecar`), which Hydrograf
ignores because it reads only `link` entries. `create_vrt_mosaic()` builds the VRT from the list it
is given; the old directory scan `discover_asc_files()` is gone.

---

## 5. Modules that use Kartograf

| Module | From Kartograf | Use |
|---|---|---|
| `utils/sheet_lookup.py` | `BBox`, `find_sheets_for_bbox` | point + buffer to sheet codes (ADR-057) |
| `utils/kartograf_store.py` | `MetadataCache`, `KartografError`, `NoCoverageError`, `download_landcover`, `BBox` | the store and the BDOT10k download |
| `scripts/download_dem.py` | `DownloadManager`, `GugikProvider`, `MetadataCache`, `find_sheets_for_geometry` | NMT download |
| `scripts/download_landcover.py` | `MetadataCache`, `download_landcover` | land cover download |
| `scripts/bootstrap.py` | `SheetParser`, `BBox`, `find_sheets_for_bbox`, `find_sheets_for_geometry`, `calculate_hsg`, `KartografError`, `ParseError`, `ValidationError` | the orchestrator |
| `scripts/prepare_area.py` | `BBox`, `SheetParser` | the area pipeline |
| `scripts/analyze_watershed.py` | `iter_store`, `list_segments` | the NMT sheets of the store |
| `core/cn_calculator.py` | `BBox`, `calculate_hsg`, `download_landcover`, `hsg_statistics`, `KartografError` | the CN calculation |
| `utils/raster_utils.py` | none (works on the `.asc` files) | CRS normalisation and the VRT mosaic |
| `tests/` | `kartograf.testing` (`build_fixture_store`, `PL_SEGMENT`), the provider classes (stubbed) | §10 |

---

## 6. The sheet system

### 6.1 Hierarchy

The official PUWG-1992 nomenclature (sheet code, sheet size):

```
1:1 000 000  │  N-34                    │  4° × 6°
1:500 000    │  N-34-A                  │  2° × 3°
1:100 000    │  N-34-131                │  20' × 30'
1:50 000     │  N-34-131-C              │  10' × 15'
1:25 000     │  N-34-131-C-c            │  5' × 7'30"
1:10 000     │  N-34-131-C-c-1          │  2'30" × 3'45"
1:5 000      │  N-34-131-C-c-1-1        │  1'15" × 1'52.5"
```

**Kartograf's scale labels are shifted by one level** against this nomenclature.
`SheetParser(...).scale` and the parameter `target_scale` of `find_sheets_for_bbox()` and
`find_sheets_for_geometry()` use Kartograf's own labels:

| Sheet code pattern (components) | `scale` in Kartograf | Official scale |
|---|---|---|
| `N-34-A` (3, a letter A-D) | `"1:500000"` | 1:500 000 (not shifted) |
| `N-34-131` (3, a number) | `"1:200000"` | **1:100 000** |
| `N-34-131-C` (4) | `"1:100000"` | **1:50 000** |
| `N-34-131-C-c` (5) | `"1:50000"` | **1:25 000** |
| `N-34-131-C-c-1` (6) | `"1:25000"` | **1:10 000** |
| `N-34-131-C-c-1-1` (7) | `"1:10000"` | **1:5 000** |

Checked on the pinned head: `SheetParser("N-34-131").scale == "1:200000"` and
`SheetParser("N-34-131-C-c-1-1").scale == "1:10000"`. So `target_scale="1:10000"`, which Hydrograf
uses by default (`sheet_lookup.py`, `download_dem --scale 1:10000`), returns 7-component codes,
officially 1:5000 sheets: the grid of the NMT files of GUGiK OpenData.

The find functions require `sheet_system` (Hydrograf passes `"1992"`). `DownloadManager.download_sheets()`
expands a code coarser than the label `"1:10000"` into all its descendants of that label: a sheet
labelled `"1:25000"` (6 components) gives 4 sheets, one labelled `"1:50000"` (5 components) gives 16.

### 6.2 Subdivision

- 1:100 000 sheets are numbered 001-144 in a 12 × 12 grid on a 1:1 000 000 sheet (row by row).
- 1:50 000: four sheets of a 1:100 000 sheet, `A B / C D`.
- 1:25 000: four sheets of a 1:50 000 sheet, `a b / c d`.
- 1:10 000 and 1:5 000: four sheets each, `1 2 / 3 4` (1 = NW, 2 = NE, 3 = SW, 4 = SE), the same
  code at both levels. A full 1:5 000 code nests both: `N-34-131-C-c-1-1` is `N-34-131-C-c` + `1`
  (the 1:10 000 quadrant) + `1` (the 1:5 000 quadrant).

---

## 7. NMT download from GUGiK (OpenData)

### 7.1 Call chain

Hydrograf downloads the NMT by sheet code only (OpenData), never by bbox:

```
scripts/bootstrap.py / scripts/download_dem.py
    -> kartograf.MetadataCache(<cache_dir>/kartograf_meta.db, on_disabled=...)
    -> kartograf.GugikProvider(vertical_crs="EVRF2007", resolution="5m", cache=...)
    -> kartograf.DownloadManager(provider, root=<cache_dir>/kartograf)
        -> .download_sheets(sheets, update=None | "force")
            (a code coarser than the label "1:10000" is expanded, §6.1)
            -> the GUGiK sheet index: the newest flight of each sheet
            -> the file as a version of the store; the standard path is a hard link to it
        -> DownloadResult: files, failed, no_coverage, hard_failures, unverified, ...
```

### 7.2 Parameters

| Parameter | Value in Hydrograf | Where |
|---|---|---|
| `root` | `<cache_dir>/kartograf` | `download_sheets(sheets, root, ...)` |
| `resolution` | `"5m"` (the 5 m NMT exists in EVRF2007 only); `"1m"` by `bootstrap --resolution` | `download_dem.download_sheets`, bootstrap `--resolution` |
| `vertical_crs` | `"EVRF2007"` (`VERTICAL_CRS`) | `scripts/download_dem.py` |
| `update` | `None` (a local version is used without a request) or `"force"` (`--no-skip-existing`) | `download_sheets(..., skip_existing=)` |
| `cache` | `MetadataCache(<cache_dir>/kartograf_meta.db)` | `--metadata-cache`, bootstrap |
| the flight | the newest, partial or not | Kartograf's default |
| format | ASC (ESRI ASCII Grid), fixed for OpenData | `GugikProvider` |
| horizontal CRS | EPSG:2180 (PL-1992); PUWG 2000 sheets are reprojected by `normalize_crs()` | `utils/raster_utils.py` |

### 7.3 Error policy of Hydrograf (`download_sheets()` → `NmtDownloadReport` / `NmtDownloadError`)

- `hard_failures` (network, 429/5xx after 3 attempts, an error of the sheet index layer) raise
  `NmtDownloadError` with the full list of sheets after all sheets were tried; bootstrap: step 2
  fails, exit code 1.
- `no_coverage` for some sheets (outside Poland, the sea) is a warning with the list, and a count in
  the detail of step 2; for every sheet it is an `NmtDownloadError`.
- `unverified` (the index was unavailable, the local version was used without checking for a newer
  one) is a warning per sheet and a count.
- A metadata cache that SQLite disabled (`on_disabled`) is an `NmtDownloadError` after the download.
- A metadata cache whose directory does not exist and an empty sheet list are an `NmtDownloadError`
  before any download.
- An invalid sheet code is a `kartograf.ParseError` before the download; in bootstrap it is a CLI
  error (exit 2).
- A store that refuses the write (`conflict`, `store_unavailable`) is a `KartografError` that the
  scripts print through `describe_error`.

### 7.4 The WCS path (not used)

Kartograf also offers `GugikProvider.download_bbox()` / `DownloadManager.download_bbox()`: any bbox
(not aligned to the sheet grid) through WCS `GetCoverage`. **Hydrograf does not call it** (no
occurrence in `api/`, `core/`, `scripts/`, `utils/`). The path exists for the 1 m resolution only and
returns GeoTIFF, PNG or JPEG: there is no ASC through WCS.

---

## 8. Errors

### 8.1 Classes and codes

Every failure of Kartograf is a `KartografError` with a `code` of the Nogat error registry, a
`reason` and often a `hint`. Hydrograf catches `KartografError` where it used to catch `Exception`
to mean "the download failed", so an API change is no longer reported as "no land cover".

| Class | Code | Cause | Reaction of Hydrograf |
|---|---|---|---|
| `ValidationError`, `ParseError` | `validation_error` | an inverted or degenerate bbox, a bad sheet code, an invalid argument | fix the input; CLI error (exit 2) in bootstrap |
| `DownloadError` | `source_unavailable` | network, 429/5xx after 3 attempts, an error of the sheet index | `NmtDownloadError`; run again |
| `NoCoverageError` (a `DownloadError`) | `no_data` | GUGiK has no data for the sheet (or no county for the area) | a report, an error only for all sheets |
| `ConflictError` | `conflict` | a store root with foreign files (`not_empty`), a store inside a store, an existing plain target | the script prints it; give the store a directory of its own |
| `StoreUnavailableError` | `store_unavailable` | a root with the layout of a store and no marker | the hint: `kartograf store init --root DIR` |
| `InvalidLayoutError` | `data_error` | a damaged layout of the store | the script prints it with its hint |

`describe_error()` prints `<message> [<code>] <hint>`; the scripts show it in the log and in the
detail of a bootstrap step.

### 8.2 Retries

`kartograf.transport.http` makes up to 3 attempts with an exponential backoff (2 s, 4 s) and only for
network errors, 429 and 5xx; one HTTP transport is shared.

---

## 9. Usage examples

### 9.1 Preparing the data for a new area

```bash
cd backend

# 1. Which sheets are needed
.venv/bin/python -c "
from utils.sheet_lookup import sheets_for_point_buffer
sheets = sheets_for_point_buffer(52.23, 21.01, buffer_km=5)
print(f'Sheets: {len(sheets)}')
for s in sheets:
    print(f'  {s}')
"

# 2. Download and process
.venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5
```

### 9.2 Full bootstrap

```bash
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" --dry-run
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" --skip-precipitation --skip-tiles
```

### 9.3 A given region

```bash
# All 1:10 000 sheets of one quarter of a 1:100 000 sheet
.venv/bin/python -m scripts.download_dem \
    --sheets N-34-131-A-a-1-1 N-34-131-A-a-1-2 N-34-131-A-a-1-3 N-34-131-A-a-1-4 \
             N-34-131-A-a-2-1 N-34-131-A-a-2-2 N-34-131-A-a-2-3 N-34-131-A-a-2-4 \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db
```

### 9.4 In Python

```python
from pathlib import Path

from scripts.download_dem import download_sheets
from utils.kartograf_store import metadata_cache_path, store_dir
from utils.sheet_lookup import sheets_for_point_buffer

cache_dir = Path("../cache")
sheets = sheets_for_point_buffer(52.23, 21.01, buffer_km=5)

# The standard paths of the sheets, e.g.
# ../cache/kartograf/nmt/pl_1992_5m_evrf2007/N-34/131/C/c/1/1/N-34-131-C-c-1-1.asc
report = download_sheets(sheets, store_dir(cache_dir), metadata_cache_path(cache_dir))
print(f"Ready: {len(report.paths)}, no coverage: {report.no_coverage}")
```

The BDOT10k packages of an area:

```python
from kartograf import BBox
from utils.kartograf_store import download_bdot10k

bbox = BBox(450000, 550000, 460000, 560000, crs="EPSG:2180")
packages = download_bdot10k(cache_dir, bbox=bbox)   # {"1465": Path(".../teryt/1465.gpkg"), ...}
```

---

## 10. Tests

The tests run the **real Kartograf**, offline: `tests/kartograf_offline.py` replaces only what would
leave the machine, the provider classes (the GUGiK sheet index, BDOT10k and SoilGrids), so the
reports and the files are those of the pinned version: a real store with a marker, versions,
sidecars and links. The fixture `offline` fails any call that reaches a socket. The stores that a test
only reads are built by `kartograf.testing.build_fixture_store`.

```bash
cd backend
uv run pytest tests/unit/test_sheet_lookup.py -v          # sheet lookup vs kartograf.find_sheets_for_bbox
uv run pytest tests/unit/test_kartograf_store.py -v       # describe_error, download_bdot10k
uv run pytest tests/unit/test_download_dem_report.py tests/unit/test_download_dem.py -v   # NMT download, report, errors, --geometry
uv run pytest tests/unit/test_download_landcover.py -v    # fetch_landcover, merge_hydro_gpkgs
uv run pytest tests/unit/test_bootstrap_nmt.py tests/unit/test_bootstrap_bbox.py -v      # steps 2-3, bbox validation
uv run pytest tests/unit/test_analyze_watershed_nmt_files.py -v   # find_existing_nmt_files on a fixture store
uv run pytest tests/unit/test_clean_cache.py -v           # the cache clean
uv run pytest tests/unit/test_cn_calculator.py tests/unit/test_land_cover_stats.py tests/unit/test_land_cover.py tests/unit/test_cn_tables.py -v
uv run pytest tests/unit/test_building_raising.py tests/unit/test_tiles_landcover.py -v
```

`tests/unit/test_download_dem.py` also guards a regression of `find_sheets_for_geometry()`, which
needs a `pathlib.Path` (it calls `filepath.suffix`). No test has the `live` marker: **a real download
is not covered**; the offline suite proves the calls against the library, not the servers of GUGiK,
Copernicus or ISRIC.

---

## 11. Land cover

### 11.1 Sources

| Source | Description | Scale / resolution |
|---|---|---|
| **BDOT10k** | the Topographic Objects Database of GUGiK; the whole package of a county, every layer, as a GeoPackage | 1:10 000 |
| **CORINE** | CORINE Land Cover (Copernicus), a raster | 100 m |

### 11.2 BDOT10k layers used

The `PT*` layers (land cover) are imported into `land_cover` with a category and a CN
(`scripts/import_landcover.py`, `BDOT10K_MAPPING`); `cn_calculator.py` maps the same codes to its
CN-table categories (`BDOT10K_CATEGORY_MAP`). The `SW*` layers and `PTWP` serve stream burning
(§12).

| Code | Description | Hydrograf category | CN |
|---|---|---|---|
| PTLZ | forests | `las` | 60 |
| PTTR, PTUT | arable land, permanent crops | `grunt_orny` | 78 |
| PTWP | surface waters | `woda` | 100 |
| PTWZ, PTRK | wetlands, shrubs | `łąka` | 70 |
| PTZB | built-up areas | `zabudowa_mieszkaniowa` | 85 |
| PTKM, PTPL | roads, squares | `droga` | 98 |
| PTGN, PTNZ, PTSO | unused, undeveloped land, dumps | `inny` | 75 |
| BUBD | buildings | (building raising, §13) | - |
| SWRS, SWKN, SWRM | rivers, canals, drainage ditches | (hydro, stream burning) | - |

### 11.3 Land cover MVT tiles

`/api/tiles/landcover/{z}/{x}/{y}.pbf` serves the `land_cover` table as Mapbox Vector Tiles
(`ST_AsMVTGeom`, generated on request). The attributes in a tile are `category`, `cn_value` and
`bdot_class`.

### 11.4 Import into the database

```bash
.venv/bin/python -m scripts.import_landcover \
    --input ../cache/kartograf/landcover/pl_bdot10k_gpkg/teryt/1465.gpkg
```

### 11.5 Complete pipeline with land cover

```bash
.venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5 --with-landcover
```

### 11.6 Python API

```python
import kartograf
from kartograf import BBox

bbox = BBox(450000, 550000, 460000, 560000, crs="EPSG:2180")

# BDOT10k: by a county code, a sheet code or an area (every county the area intersects)
report = kartograf.download_landcover(product="bdot10k", root="../cache/kartograf", teryt="1465")
report = kartograf.download_landcover(product="bdot10k", root="../cache/kartograf", bbox=bbox)
for item in report.files:            # one item per county
    print(item.unit, item.file.path)
for failure in report.failed:
    print(failure.unit, failure.error)

# CORINE
report = kartograf.download_landcover(product="corine", root="../cache/kartograf", bbox=bbox, year=2018)
```

`kartograf.discover_teryts_for_bbox()` (the counties of an area, without the data) is public in
0.8.0; Hydrograf does not call it, because `download_landcover(bbox=)` finds the counties itself.
This closed the private `Bdot10kProvider._get_teryt_for_point` exception of ADR-057.

---

## 12. BDOT10k hydro

### 12.1 Hydrographic layers

A county package holds every BDOT10k layer. The hydrographic ones:

| Code | Description | Geometry |
|---|---|---|
| **SWRS** | rivers and streams | LineString |
| **SWKN** | canals | LineString |
| **SWRM** | drainage ditches | LineString |
| **PTWP** | surface waters (lakes, ponds) | Polygon |

### 12.2 Filtering

Kartograf has no category parameter for the hydro layers; `merge_hydro_gpkgs()` in
`scripts/download_landcover.py` keeps only these layers when it merges the packages of several
counties into one GeoPackage (`hydro_merged.gpkg`), with the constant:

```python
HYDRO_LAYER_PREFIXES = ("SWRS", "SWKN", "SWRM", "PTWP")
```

### 12.3 Use in Hydrograf

- **Stream burning**: the streams are burned into the NMT for better flow directions
  (`core/hydrology.py: burn_streams_into_dem()`), then smoothed monotonically (ADR-041).
- **Validation of the stream network**: the generated network is compared with the BDOT10k streams
  (`is_real_stream`, table `bdot_streams`, ADR-044).
- **Supplementary information**: the names and the classification (river, canal, ditch).
- Bootstrap exports the hydro layers as GeoJSON for the front end (`export_bdot_geojson`).

---

## 13. Building raising (ADR-033)

### 13.1 Problem

Buildings in the NMT are not high enough: in the model the water flows through them, which gives
unrealistic flow directions.

### 13.2 Solution

`raise_buildings_in_dem()` in `core/hydrology.py` reads the footprints from a GeoPackage (the BUBD
layer of BDOT10k), rasterises them onto the DEM grid and raises the DEM under them by 5 m:

```python
from core.hydrology import raise_buildings_in_dem

dem = raise_buildings_in_dem(
    dem=dem_array,
    transform=rasterio_transform,
    crs_epsg=2180,
    building_gpkg="buildings.gpkg",
    building_raise_m=5.0,
)
```

### 13.3 Pipeline

`process_dem()` takes the file as `building_gpkg` and raises the buildings after the DEM is read and
before stream burning and depression filling. **No script passes `building_gpkg` today**: the
bootstrap and `prepare_area` do not raise buildings, so the function is tested
(`tests/unit/test_building_raising.py`) and available, and the pipeline does not use it yet.

---

## 14. HSG, the hydrologic soil groups

### 14.1 Overview

`calculate_hsg()` of Kartograf downloads the SoilGrids rasters (clay, sand and silt, depth 0-5 cm,
mean), computes the USDA texture class of each cell and classifies it into a hydrologic soil group
(`uint8`: 0 no data, 1-4 are A-D). The inputs are versions of the store (`soil/`), the result is a
version of `hsg/`. `hsg_statistics()` counts the cells per group.

### 14.2 Use in Hydrograf

Two integration points:

1. **Bootstrap step 5**: the raster of Poland (EPSG:2180 bbox `167000 29000 860000 814000`) is
   fetched once into the store, `reused` after; the step clips it to the mosaic, warps it to
   EPSG:2180 at 250 m, fills the missing pixels with the nearest neighbour, polygonizes it (the
   fragments under 50 m² are dropped) and imports it into `soil_hsg`, replacing the polygons of the
   bbox. It also writes `soil_hsg.geojson` for the front end.
2. **`cn_calculator.py`**: the CN on demand for one watershed, with a plain raster in a temporary
   directory (§4.7).

### 14.3 The `soil_hsg` table

| Column | Type | Description |
|---|---|---|
| id | SERIAL | PK |
| hsg_group | VARCHAR(1) | HSG group (A, B, C, D), `CHECK (hsg_group IN ('A','B','C','D'))` |
| area_m2 | DOUBLE PRECISION NOT NULL | polygon area [m²] |
| geom | GEOMETRY(MultiPolygon, 2180) | geometry |

As in `backend/migrations/versions/001_initial_schema.py` and `docs/DATA_MODEL.md` §3.7. The table is
read by `core/soil_hsg.py: get_hsg_for_boundary()`, a spatial intersection with the watershed
boundary that gives the dominant group.

---

## 15. Filtering by geometry

Kartograf limits a download to a spatial extent:

```python
from pathlib import Path
from kartograf import find_sheets_for_geometry

# The sheets that cover a geometry file (SHP or GPKG). The path must be a
# pathlib.Path: the readers call filepath.suffix, a str raises AttributeError
# (a regression fixed in 382c5f3, guarded by tests/unit/test_download_dem.py).
sheets = find_sheets_for_geometry(
    Path("boundary.gpkg"), target_scale="1:10000", sheet_system="1992"
)
```

```bash
python -m scripts.download_dem --geometry ../data/watershed_boundary.gpkg \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db
```

Other formats (GeoJSON) of `bootstrap --boundary-file` fall back to the bbox of the geometry.

---

## 16. Open items

- **NMPT**: Kartograf downloads it, no analysis of Hydrograf uses it.
- **Parallel download**: `DownloadManager(workers=)` exists; Hydrograf downloads sequentially (the
  default).
- **Area weights of the HSG of one analysis**: `hsg_statistics` of the plain raster counts the whole
  raster (ADR-061, erratum); weights would be a change of the CN calculation, decided on its own.
- **Building raising** in the scripts (§13.3).
- **A real download** is not tested (§10).
- **Versions of the DEM flights**: the store keeps every flight as a version with its campaign and
  its sidecar; the ADR on how Hydrograf records and updates them is still to be decided
  (BACKLOG).
- **The `.prj` files** that `normalize_crs()` writes next to the standard paths of the store (§4.9).

---

**Document version:** 7.0
**Last update:** 2026-10-25: Kartograf 0.8.0 (ADR-061): the store `cache/kartograf/` (marker, versions, sidecars, hard links), `download_landcover`, `calculate_hsg` and `hsg_statistics` instead of `LandCoverManager` and `HSGCalculator`, `KartografError` codes, the pin of the head `45dedf4`; the document is in English.
**History:** 6.0 (2026-10-08): Kartograf 0.7.0 (campaigns, `MetadataCache`, loud download errors, the `cache/nmt/...` layout).
