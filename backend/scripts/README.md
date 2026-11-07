# Preprocessing scripts

Scripts that prepare the input data once, before the system runs. The API serves only what they
leave in PostGIS, in `frontend/data/` and in `frontend/tiles/` (ADR-021, ADR-022).

## Requirements

- Python 3.12+ in `backend/.venv` (`uv sync --locked`). Run the scripts from `backend/` as
  `.venv/bin/python -m scripts.<name>` (or `uv run python -m scripts.<name>`).
- A running PostgreSQL/PostGIS database with the Alembic migrations applied (`bootstrap.py` does
  both).
- [Kartograf](https://github.com/Daldek/Kartograf), pinned by commit in `backend/pyproject.toml`
  (0.8.0.dev0, installed by `uv sync --locked`; details in
  [docs/integrations/KARTOGRAF.md](../../docs/integrations/KARTOGRAF.md)):
  - NMT (DEM): elevation data from GUGiK
  - BDOT10k: one GeoPackage package per county (*powiat*) from GUGiK, every layer; the land cover
    (`PT*` layers) and the hydrography (SWRS rivers, SWKN canals, SWRM ditches, PTWP waters) are
    taken from it
  - HSG: hydrologic soil groups, computed by Kartograf from SoilGrids
  - CORINE: the European land cover classification from Copernicus (downloaded by
    `download_landcover.py`, not used by the pipeline)
- GDAL (`gdalbuildvrt`, `gdalwarp`) for the VRT mosaic; `tippecanoe` for the MVT tiles (optional:
  bootstrap skips the step without it).

### Where the files go

| Directory | Content |
|---|---|
| `cache/kartograf/` | the Kartograf store of the downloads: NMT sheets, BDOT10k packages, the HSG raster of Poland and its SoilGrids inputs, with versions and a sidecar per file. With `HYDROGRAF_KARTOGRAF_ROOT` set, the store it names (shared with Archiwista, ADR-066) is only read, through a set (`bootstrap --project --set`), and every download is refused (ADR-067) |
| `cache/kartograf_meta.db` | the Kartograf metadata cache (SQLite; a local disk, not a network share) |
| `data/nmt/` | the VRT mosaic `dem_mosaic.vrt` (and `reprojected/`), the intermediate rasters `dem_mosaic_*` |
| `data/hydro/` | `hydro_merged.gpkg`: the BDOT10k hydro layers of the area, for stream burning |
| `frontend/data/` | overlays (PNG, JSON), the DEM tile pyramid, GeoJSON exports |
| `frontend/tiles/` | MVT tiles |

`data/` and `cache/` are ignored by Git. The store needs a file system with hard links (not FAT,
exFAT or SMB); `prepare_area.py` keeps its own store in `<output>/kartograf`.

## Available scripts

### `bootstrap.py`: one-command setup

The orchestrator: ten steps from an empty machine to a running system. Steps 1 to 3 are critical
(a failure stops the pipeline and the exit code is 1); steps 4 to 10 are optional and the pipeline
continues when one fails.

| Step | What it does | Skip flag |
|---|---|---|
| 1 | infrastructure: `.venv` (`uv sync --locked`), the database container, `alembic upgrade head`, the SRI hashes of the CDN resources | `--skip-infra` |
| 2 | downloads the NMT sheets of the area into the Kartograf store (`download_dem.download_sheets`); from a set: the pinned sheets, nothing downloaded | - |
| 3 | processes the DEM: the VRT mosaic of the sheets of step 2, the BDOT10k hydro layers for stream burning, `process_dem` (`stream_network`, `stream_catchments`) | - |
| 4 | downloads the BDOT10k packages of the counties of the mosaic and imports them into `land_cover`; from a set: the pinned packages | `--skip-landcover` |
| 5 | HSG: the raster of Poland (a version of the store), clipped to the mosaic, polygonized into `soil_hsg`; from a set: the pinned raster | `--skip-hsg` |
| 6 | IMGW precipitation (PMAXTP) on a 2 km grid into `precipitation_data` | `--skip-precipitation` |
| 7 | depressions (blue spots) from the filled DEM | `--skip-depressions` |
| 8 | MVT tiles (`tippecanoe`) | `--skip-tiles` |
| 9 | DEM and stream overlays (PNG) and the DEM tile pyramid | `--skip-overlays` |
| 10 | starts the Docker Compose stack | `--skip-serve` |

**Usage:**

```bash
cd backend

# By a bounding box (WGS84)
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"

# By sheet codes
.venv/bin/python -m scripts.bootstrap --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2

# By a boundary file (SHP/ZIP, GPKG, GeoJSON)
.venv/bin/python -m scripts.bootstrap --boundary-file ../data/boundary/area.gpkg

# From a closed set of an Archiwista project (the shared store, ADR-067):
# check everything and show the plan, then run
.venv/bin/python -m scripts.bootstrap --project /path/to/project --set "Hydrograf 2020" --dry-run
.venv/bin/python -m scripts.bootstrap --project /path/to/project --set "Hydrograf 2020"

# Dry run: show the plan without executing it
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" --dry-run

# Skip optional steps
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" \
    --skip-precipitation --skip-tiles
```

**Parameters:**

| Parameter | Description | Default |
|---|---|---|
| `--bbox` | bounding box in WGS84: `"min_lon,min_lat,max_lon,max_lat"` | (one of the four is required) |
| `--sheets` | sheet codes to download | (one of the four is required) |
| `--boundary-file` | vector boundary file (SHP/ZIP, GPKG, GeoJSON) | (one of the four is required) |
| `--project` | an Archiwista project: its directory or its `archiwista-project.json`; the Kartograf data come only from the closed set `--set` (ADR-067) | (one of the four is required) |
| `--set` | the set of `--project` (compared case-folded); required with `--project` | - |
| `--boundary-layer` | layer name of a GPKG boundary file | the first layer |
| `--scale` | sheet scale in Kartograf's labels (`1:10000`, `1:25000`, `1:50000`, `1:100000`) | `1:10000` |
| `--resolution` | NMT resolution: `1m` (high, slow) or `5m` | `5m` |
| `--output` | output directory | `../data/` |
| `--cache-dir` | directory of the cached downloads: the Kartograf store is `<cache-dir>/kartograf` | `paths.cache_dir` of the configuration (`cache/` in the repository root) |
| `--config` | YAML configuration file | `config.yaml` |
| `--port` | HTTP port of the server | 8080 |
| `--dry-run` | only show what would be done; with `--project`, after every check of the set | off |

`--bbox`, `--sheets`, `--boundary-file` and `--project` exclude each other.

**Stream burning** (`dem.stream_burning` of the configuration): step 3 burns the BDOT10k streams
into the DEM and smooths the DEM along them. `all` (the default) takes every line of `OT_SWRS_L`,
`OT_SWKN_L` and `OT_SWRM_L`; `main` only the main watercourses: `OT_SWRS_L` with
`PRZEBIEG = 'ciek główny'` (no side arms) that is a river (`RODZAJ = 'rzeka'`) or carries an MPHP
identifier (`IDENTYFIKATORMPHP`), `OT_SWKN_L` with an MPHP identifier, no ditches (`OT_SWRM_L`,
whose networks form loops that falsify the flow directions). The water bodies (`OT_PTWP_A`) are
burned in both modes; the stream table `bdot_streams`, the map layer of the streams and the
classification of the lakes always use every layer. Another value is refused
(`validation_error`, exit 2). The run logs the mode, step 3 reports it after the burned file, and
the record of a set keeps it.

**From a set** (ADR-067): `--project` and `--set` read a closed set of an Archiwista project
(`archiwista-project/1`) and download nothing. Before step 1 the bootstrap checks the project file,
the area file and its SHA-256, that the set is closed (an open set, „w budowie”, is refused), its
recorded `pins_sha256`, the project's Kartograf store (the same directory as
`HYDROGRAF_KARTOGRAF_ROOT` when that is set) and every Kartograf pin by size and SHA-256; then that
the set holds the NMT sheets of the project's area, the BDOT10k packages of the counties of the
mosaic (unless `--skip-landcover`) and one HSG raster that covers the mosaic (unless
`--skip-hsg`), one version per sheet, county and raster. Steps 2 to 5 read the pinned files (step 2
reports `N/N arkuszy z zestawu`); steps 6 to 10 do not change. The run logs the set and writes
`<output>/bootstrap_set.json` (`hydrograf-bootstrap-set/1`: project, set, `pins_sha256`, inputs,
`stream_burning`, start, end, status); a run without a set removes the file.

**The shared store is read-only:** while `HYDROGRAF_KARTOGRAF_ROOT` is set, `--bbox`, `--sheets` and
`--boundary-file` are refused (`forbidden`, exit 12), as are `download_dem.py`,
`download_landcover.py`, `prepare_area.py` and `analyze_watershed.py --download`; unset it to
download into `<cache-dir>/kartograf`. A refusal prints `BŁĄD:` and `Wskazówka:` and, as the last
line of standard error, the error document `hydrograf-error/1`; the exit code is the registry's:

| Exit | Code | When |
|---|---|---|
| 2 | `validation_error` | an argument error (also `--project` without `--set`); the project's store is not `HYDROGRAF_KARTOGRAF_ROOT` |
| 3 | `not_found` | no project file, no area file, no set of the name, a pinned file absent |
| 4 | `conflict` | the set is open; two versions of one sheet, county or raster, or two HSG rasters that cover the mosaic |
| 5 | `source_unavailable` | PRG does not answer (the counties of the mosaic) |
| 7 | `data_error` | the project file breaks its format; the area or a pinned file changed; the recorded `pins_sha256` differs |
| 8 | `store_unavailable` | no store, or not a marked Kartograf store |
| 9 | `io_error` | the project file or a pinned file cannot be read (the ACL) |
| 12 | `forbidden` | `--bbox`, `--sheets` or `--boundary-file` while `HYDROGRAF_KARTOGRAF_ROOT` is set |
| 14 | `no_data` | sheets, counties or the HSG raster missing from the set |
| 15 | `unsupported` | a project schema other than `archiwista-project/1` |

The hint names the Archiwista action that fixes the set: „Zamknij zestaw”, „Weryfikuj”,
„Przywróć brakujące”, or „Otwórz do edycji”, a call that covers the project's area and
„Zamknij zestaw”.

**Water bodies:**

| Parameter | Description | Default |
|---|---|---|
| `--waterbody-mode` | `auto` (BDOT10k classification), `none` (skip) or a path to a `.gpkg`/`.shp` file (all treated as endorheic) | `none` |
| `--waterbody-min-area` | the smallest water body in m²; smaller ones are ignored | - |

**Storm sewer** (ADR-051, ADR-052): `--sewer-enabled`, `--sewer-source` (a GPKG/SHP/GeoJSON file)
and `--sewer-layer` (the line layer of a multi-layer file); they override the `sewer` section of the
configuration.

A failed step 2 can be run again: the sheets that are already in the store are used without a
request and only the rest is downloaded. The accumulation thresholds of step 3 are fixed at 10000,
100000, 1000000 and 10000000 m² (`core.constants.PIPELINE_THRESHOLDS_M2`; `docs/BACKLOG.md`: a
`--thresholds` flag for `bootstrap.py`).

---

### `clean.py`: remove generated data

Removes the processed rasters, the frontend assets, the tiles and, on request, the database tables
and the download cache, to prepare a clean run of `bootstrap.py`.

```bash
cd backend

# Standard clean: processed data only (rasters, hydro, boundary, overlays, geojson, tiles)
.venv/bin/python -m scripts.clean

# Also the download cache
.venv/bin/python -m scripts.clean --include-cache

# Also the database tables
.venv/bin/python -m scripts.clean --include-db

# Everything: data, cache and tables
.venv/bin/python -m scripts.clean --all

# Selected components only
.venv/bin/python -m scripts.clean --only rasters tiles

# Dry run, and without the confirmation prompt
.venv/bin/python -m scripts.clean --dry-run
.venv/bin/python -m scripts.clean --yes
```

`--output` and `--cache-dir` name the data and cache directories (defaults `../data` and
`../cache`).

**Components:**

| Component | What it removes |
|---|---|
| `rasters` | the NMT rasters (`*.tif`, `*.vrt` in `data/nmt/`) |
| `hydro` | the merged BDOT10k hydro data (`data/hydro/`) |
| `boundary` | the boundary files of the area (`data/boundary/`) |
| `overlays` | PNG and JSON overlays and the DEM tile pyramid (`frontend/data/`) |
| `geojson` | the GeoJSON exports (`frontend/data/*.geojson`) |
| `tiles` | MVT tiles and mbtiles (`frontend/tiles/`) |
| `db` | truncates the tables `stream_network`, `stream_catchments`, `bdot_streams`, `depressions`, `land_cover`, `precipitation_data`, `soil_hsg`, `sewer_nodes` and `sewer_network` |
| `cache` | the large products of the Kartograf store that Kartograf fetches again (`cache/kartograf/nmt` and `cache/kartograf/landcover`), `cache/kartograf_meta.db*`, and the directories of the 0.7.0 layout, whole: `cache/nmt`, `cache/bdot10k`, `cache/soil_hsg` (nothing reads them any more, ADR-061). The HSG raster of Poland, its SoilGrids inputs and the marker of the store stay: they are small, Poland-wide and reusable. A shared store (`HYDROGRAF_KARTOGRAF_ROOT`, ADR-066) stays whole |

The standard clean takes the first six components; `--include-cache` adds `cache` and
`--include-db` adds `db`.

**A typical regeneration:**

```bash
cd backend
.venv/bin/python -m scripts.clean --include-db -y
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
```

---

### `prepare_area.py`: one area from a point

Downloads the NMT for the area around a point, builds the VRT mosaic and processes it with
`process_dem`; optionally with the BDOT10k hydro layers for stream burning and with land cover.

```bash
cd backend

# The area of 5 km around a point (NMT only)
.venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5

# With land cover (BDOT10k), which the hydrographs need
.venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5 --with-landcover

# With the hydro layers burned into the DEM
.venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5 --with-hydro

# Dry run: show the plan
.venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --dry-run
```

**Parameters:**

| Parameter | Description | Default |
|---|---|---|
| `--lat`, `--lon` | the centre of the area (WGS84) | (required) |
| `--buffer` | the buffer radius in km | 5 |
| `--scale` | sheet scale in Kartograf's labels (`1:10000`, `1:25000`, `1:50000`, `1:100000`) | `1:10000` |
| `--batch-size` | batch size of the land cover insert | 10000 |
| `--with-landcover` | also download and import the land cover (BDOT10k) | off |
| `--with-hydro` | also download the BDOT10k hydro layers and burn the streams into the DEM | off |
| `--burn-depth` | the burn depth in m | 2.0 |
| `--waterbody-mode`, `--waterbody-min-area` | as in `bootstrap.py` | `none` |
| `--output`, `-o` | output directory | `../data/nmt/` |
| `--keep-downloads` / `--no-keep-downloads` | keep the downloaded `.asc` files, or work in a temporary directory and remove it | keep |
| `--save-intermediates`, `-s` | write the intermediate GeoTIFF files | off |
| `--dry-run` | only show what would be done | off |

`--output` is the working directory of the run: the NMT sheets and the BDOT10k packages go to the
Kartograf store `<output>/kartograf`, the metadata cache to `<output>/kartograf_meta.db` (a local
disk), and the mosaic and the intermediates to `<output>` itself. There is no choice of the land
cover provider: the county-level CORINE download never worked (ADR-061).

---

### `download_dem.py`: download the NMT from GUGiK

Downloads the NMT through [Kartograf](https://github.com/Daldek/Kartograf) into its store and
processes nothing. Kartograf downloads the sheets by OpenData (ASC), expands coarse sheet codes into
the 1:10000 sheets they consist of, takes the newest flight of each sheet (partial or not, so the
border and coast sheets are kept) and uses a version that is already local without a request. A sheet
without coverage is a warning (an error when no sheet has coverage); a failed transfer is exit code 1.
The format is not configurable.

```bash
cd backend

# The area around a point
.venv/bin/python -m scripts.download_dem --lat 52.23 --lon 21.01 --buffer 5 \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db

# Given sheets
.venv/bin/python -m scripts.download_dem --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2 \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db

# The sheets that cover a geometry file
.venv/bin/python -m scripts.download_dem --geometry ../data/boundary.gpkg \
    --root ../cache/kartograf --metadata-cache ../cache/kartograf_meta.db

# Dry run: show the sheets, download nothing
.venv/bin/python -m scripts.download_dem --lat 52.23 --lon 21.01 --dry-run
```

**Parameters:**

| Parameter | Description | Default |
|---|---|---|
| `--lat`, `--lon` | the centre (WGS84) | - |
| `--buffer` | the buffer radius in km | 5 |
| `--sheets` | sheet codes to download | - |
| `--geometry`, `--layer` | an SHP/GPKG file that selects the sheets, and its layer | the first layer |
| `--root` | the Kartograf store; a new or empty directory becomes one, a directory with other files is refused | `../cache/kartograf` |
| `--metadata-cache` | the SQLite metadata cache, on a local disk, outside `--root` | required to download |
| `--scale` | sheet scale in Kartograf's labels (`1:10000`, `1:25000`, `1:50000`, `1:100000`) | `1:10000` |
| `--no-skip-existing` | fetch the sheets again although a version is local | off |
| `--dry-run` | only show what would be downloaded | off |

A sheet lands at `<root>/nmt/pl_1992_5m_evrf2007/<hierarchy>/<sheet>.asc`, for example
`N-34/131/C/c/2/1/N-34-131-C-c-2-1.asc`; the versions are below `versions/`.

---

### `process_dem.py`: process the NMT

Processes an NMT file (ASCII GRID, a VRT mosaic or a GeoTIFF) with `pyflwdir` (Deltares) and writes
the stream network and the sub-catchments into `stream_network` and `stream_catchments`.

**Stages:**

1. Read the raster (`.asc`, `.vrt`, `.tif`); with `--hydro-resolution` downsample it first.
2. Raise the buildings (+5 m under the BUBD footprints, ADR-033): `process_dem()` takes the file as
   `building_gpkg`, but no script passes it, so the stage does not run in the pipeline (what the
   wiring needs: `docs/BACKLOG.md`, Bugs and diagnoses).
3. Burn the streams into the DEM (`--burn-streams`, optional), then smooth them monotonically with a
   running minimum downstream from the outlet, which corrects bridges and embankments (ADR-041;
   `--no-smooth-streams` switches it off).
4. Classify the endorheic lakes and their drain points (`--waterbody-mode`); burn the storm-sewer
   inlets and route the flow accumulation through the sewer graph (optional, ADR-051).
5. Fill the depressions, compute the D8 flow direction and the flow accumulation.
6. Compute the distance along the flow to the outlet, the slope and the aspect (Sobel), the Strahler
   order and the TWI.
7. Make the stream mask of the lowest threshold and vectorize the streams per accumulation
   threshold; delineate the sub-catchments (thresholds from 1000 m², ADR-026) with their statistics
   and flow paths. Each sub-catchment gets the elevation of the head (farthest cell) of its longest
   flow path, the length and drop of the overland segment of that path down to the first stream
   cell of its threshold, and the elevation of the upstream end of its stream segment, all on the
   filled DEM (ADR-070); what cannot be measured stays empty.
8. Insert the result into PostGIS (COPY) with the matching of the streams against BDOT10k when
   `--burn-streams` is given (ADR-044); `--clear-existing` first deletes the DEM-derived streams and
   the sub-catchments.

`--from-intermediates` skips stages 1–6: it reads the rasters that an earlier run saved with
`--save-intermediates` (`*_02_filled`, `*_03_flowdir`, `*_04_flowacc`, `*_04b_stream_distance`,
`*_05_slope`, where `*` is the stem of `--input`) and adds the streams and sub-catchments of
`--thresholds` to the database without touching the thresholds already there (it refuses a threshold
the database holds). The new streams are matched against the BDOT10k streams of the database. This is
how the thresholds of 1 km² and 10 km² are added to data processed before them
(`docs/runbooks/2026-11-v050-reprocessing.md`).

```bash
cd backend

# A VRT mosaic (or a single .asc sheet)
.venv/bin/python -m scripts.process_dem --input ../data/nmt/dem_mosaic.vrt

# With the intermediate GeoTIFF files for a check in QGIS
.venv/bin/python -m scripts.process_dem --input ../data/nmt/dem_mosaic.vrt \
    --save-intermediates --output-dir ../data/nmt/output

# Dry run: only the computation and the statistics
.venv/bin/python -m scripts.process_dem --input ../data/nmt/dem_mosaic.vrt --dry-run

# Add the thresholds of 1 km² and 10 km² from the rasters of an earlier run
.venv/bin/python -m scripts.process_dem --input ../data/nmt/dem_mosaic.tif \
    --from-intermediates --thresholds 1000000,10000000 --save-intermediates
```

**Parameters:**

| Parameter | Short | Description | Default |
|---|---|---|---|
| `--input` | `-i` | path to the raster (required) | - |
| `--thresholds` | - | the flow accumulation thresholds in m², comma separated (`1000,10000,100000`); the lowest makes the stream mask | `10000,100000,1000000,10000000` |
| `--from-intermediates` | - | add the thresholds from the saved rasters of an earlier run, without the hydrology; needs `--thresholds`, refuses `--clear-existing`, `--burn-streams` and `--hydro-resolution` | off |
| `--dry-run` | - | only compute and print the statistics, no insert | off |
| `--save-intermediates` | `-s` | write the intermediate rasters as GeoTIFF | off |
| `--output-dir` | `-o` | the directory of the GeoTIFF files | the directory of the input |
| `--clear-existing` | - | delete the DEM-derived streams and the sub-catchments before the insert | off |
| `--burn-streams` | - | a GeoPackage/Shapefile with the stream lines to burn into the DEM | - |
| `--burn-depth` | - | the burn depth in m | 2.0 |
| `--no-smooth-streams` | - | no monotonic smoothing after the burning (for debugging) | off |
| `--skip-streams-vectorize` | - | no vectorization of the streams (useful without a database) | off |
| `--skip-catchments` | - | no sub-catchments | off |
| `--hydro-resolution` | - | downsample the DEM to this resolution in m before the hydrology; saves memory on large rasters | - |
| `--waterbody-mode` | - | `auto`, `none` or a path to a file | `none` |
| `--waterbody-min-area` | - | the smallest water body in m² | - |

**Intermediate files (GeoTIFF):**

`--save-intermediates` writes files to check the computation in a GIS (for example QGIS); `*` is the
name of the input without its extension. The files are LZW-compressed and tiled in 256 × 256 cells,
so a read of a window (the API, a GIS) decodes only the tiles the window touches.

| File | Description | Data type |
|---|---|---|
| `*_01_dem.tif` | the original DEM | float32 |
| `*_02a_burned.tif` | the DEM after the stream burning (with `--burn-streams`) | float32 |
| `*_02b_smoothed.tif` | the DEM after the monotonic smoothing (with `--burn-streams`, without `--no-smooth-streams`) | float32 |
| `*_02_filled.tif` | the DEM after the depressions are filled | float32 |
| `*_03_flowdir.tif` | the flow direction (D8) | int16 |
| `*_04_flowacc.tif` | the flow accumulation (the number of cells upstream) | int32 |
| `*_04b_stream_distance.tif` | the distance along the flow to the outlet [m] | float32 |
| `*_05_slope.tif` | the slope [%] | float32 |
| `*_06_streams.tif` | the stream mask (0/1) | uint8 |
| `*_07_stream_order.tif` | the Strahler order (1 and more, 0 = not a stream) | uint8 |
| `*_07_stream_order_<threshold>.tif` | the same per threshold | uint8 |
| `*_08_twi.tif` | TWI, the Topographic Wetness Index | float32 |
| `*_09_aspect.tif` | the aspect (0-360°, north = 0) | float32 |
| `*_10_subcatchments_<threshold>.tif` | the labels of the sub-catchments per threshold | int32 |

**The D8 encoding (flow direction):**

| Value | Direction |
|---|---|
| 1 | E |
| 2 | SE |
| 4 | S |
| 8 | SW |
| 16 | W |
| 32 | NW |
| 64 | N |
| 128 | NE |

**Example output** (a dry run on a synthetic DEM of 240 x 240 cells of 5 m, a tilted plane with a
valley, `--thresholds 1000,10000`; the timestamps and the log level are left out, the middle of the
log is cut):

```
Multi-threshold FA: [1000, 10000] m²
Dry run: True
Read DEM: 240x240 cells
Origin: (500000.0, 500000.0)
Cell size: 5.0 m
Waterbody mode: none — skipping lake classification
Processing hydrology with pyflwdir (Deltares)...
  Filling depressions and computing D8 flow direction...
  Computing flow accumulation...
Hydrology processing complete
Slope computed (range: 0.0% - 8.1%)
  Threshold 1000 m² = 40 cells
  Threshold 10000 m² = 400 cells
Strahler order computed (max order: 3, stream cells: 32,657)
TWI computed (range: 4.8 - 19.5)
...
Dry run - skipping database insert
Processing complete!
  Grid size: 240 x 240
  Cell size: 5.0 m
  Total cells: 57,600
  Valid cells: 57,600
  Max accumulation: 57,600
  Mean slope: 7.3%
  Stream cells: 32,657
  Stream segments: 923
    Threshold 1000 m²: 920 segments
    Threshold 10000 m²: 3 segments
    Sub-catchments 1000 m²: 920
    Sub-catchments 10000 m²: 3
  Time elapsed: 5.5s
```

---

### `backfill_flow_path_heads.py`: fill the flow path heads of existing data

Fills `flow_path_head_elev_m`, `overland_length_m`, `overland_drop_m` and `stream_head_elev_m`
of `stream_catchments` (migration 004, ADR-070) for data processed before them, from the rasters
their run saved (`*_02_filled`, `*_03_flowdir`, `*_04_flowacc`, `*_04b_stream_distance` and
`*_10_subcatchments_<threshold>`), with the code of the pipeline and without running it again. The
head of a sub-catchment's longest flow path is the first vertex of `longest_flow_path_geom`; when a
head is not in its own label or its flow distance differs from `max_flow_dist_m` by more than
0.05 m, the rasters are not those of the data and the script stops before it writes anything.
Idempotent.

```bash
cd backend
.venv/bin/python -m scripts.backfill_flow_path_heads --input ../data/nmt/dem_mosaic.tif
.venv/bin/python -m scripts.backfill_flow_path_heads --input ../data/nmt/dem_mosaic.tif \
    --thresholds 10000 --dry-run
```

| Parameter | Description | Default |
|---|---|---|
| `--input` | the DEM of the run; its stem prefixes the rasters (the file itself is not read) | required |
| `--output-dir` | the directory of the rasters | the directory of `--input` |
| `--thresholds` | the thresholds to fill, comma separated | every threshold of `stream_catchments` |
| `--dry-run` | compute and check, no `UPDATE` | off |

`scripts/generate_tiles.py --thresholds 1000000,10000000` builds the tiles of those thresholds only
and keeps the others; `tiles_metadata.json` then lists every threshold of the database that has
tiles.

---

### `export_catchment_parameters.py`: the parameters of the panel for given polygons

Computes, for every polygon of a layer, what the panel „Zlewnia” shows in „Parametry
podstawowe”, „Wskaźniki kształtu” and „Pokrycie terenu”, with the polygon as the boundary of
the watershed (no delineation from the NMT), and writes the polygons with their key, the fields
asked for and these values to a new GeoPackage. It reads the rasters that the pipeline saved in
`DEM_DIR` (`dem_mosaic_02_filled`, `_03_flowdir`, `_04_flowacc`, `_04b_stream_distance`,
`_05_slope` and `_10_subcatchments_<threshold>`) and the database (`land_cover`, the BDOT10k flags
and lengths of `stream_network` and `stream_catchments`), only reading both. The values come from
the code behind the panel: the zonal statistics of the sub-catchments over the cells whose centre
lies in the polygon, the flow paths of `core.divide_flow_path`, the overland segment of
`process_dem`, the BDOT10k part of the main channel of `core.catchment_graph`, the shape indices
of `core.morphometry` and the land cover of `core.watershed_service`. The outlet is the cell of
the largest flow accumulation in the polygon; the flow paths start in the part of the polygon
that drains to it; the main channel goes up the stream network of the threshold from it, at each
confluence into the branch of the larger accumulation, to its source or to where it flows in from
outside the polygon. The length and the mean width of the watershed and the shape indices computed
from them (elongation, form factor, lemniscate) are left out.

```bash
cd backend
.venv/bin/python -m scripts.export_catchment_parameters --input zlewnie.gpkg --layer zlew_h_07 \
    --key ID_HYD_10 --keep ID_HYD_50,NAZ_ZLEWNI --output parametry.gpkg
```

| Parameter | Description | Default |
|---|---|---|
| `--input` | the GeoPackage of the polygons, in PL-1992 (EPSG:2180; ESRI:102173 is accepted as the same) | required |
| `--layer` | the layer of the polygons | the only layer of the file |
| `--key` | a field with a unique, non-empty value per polygon | required |
| `--keep` | other fields to keep, comma separated | none |
| `--output` | the new GeoPackage; an existing file is refused | required |
| `--output-layer` | the layer of the output | `catchment_parameters` |
| `--threshold-m2` | the flow accumulation threshold of the main channel, the overland segment and the BDOT10k length | `100000`, the default of the panel |
| `--dem-dir` | the directory of the rasters | `DEM_DIR` |

The script stops with a message, before it computes anything, when the layer is not in PL-1992, a
field is missing, the key is empty or repeated, a geometry is not a valid polygon, a raster is
missing or the database has no stream network of the threshold. The output keeps each geometry as
it was, in EPSG:2180, with the key and the kept fields, then these columns (the table
`<output layer>_units` of the same GeoPackage gives the unit, the section, the row of the panel and
the source of each; the layer's metadata the threshold, the raster directory and the version):

| Section | Columns |
|---|---|
| Parametry podstawowe | `area_km2`, `perimeter_km`, `elevation_min_m`, `elevation_max_m`, `elevation_mean_m`, `mean_slope_m_per_m`, `channel_length_km`, `real_channel_length_km`, `channel_slope_m_per_m`, `flow_path_length_km`, `flow_path_slope_m_per_m`, `overland_length_km`, `overland_slope_m_per_m`, `divide_flow_path_km`, `cn`, `outlet_latitude_deg`, `outlet_longitude_deg`, `outlet_elevation_m` |
| Wskaźniki kształtu | `compactness_coefficient`, `circularity_ratio` |
| Pokrycie terenu | `lc_<class>_pct` and `lc_<class>_cn` of `grunt_orny`, `las`, `laka`, `zabudowa_mieszkaniowa`, `zabudowa_przemyslowa`, `droga`, `woda`, `inny` |
| Kontrola | `polygon_area_km2` (of the geometry), `outlet_upstream_area_km2` (the NMT watershed of the outlet), `polygon_to_upstream_area_ratio` (about 1 for a polygon that is that watershed, less with inflow from outside), `cell_count`, `quality_flag` (`under_100_cells`, `partly_outside_nmt`, `outside_nmt`) |

Slopes are in m/m like the API (the panel shows them times 100 in %). For the boundary of a
watershed of the panel the values are those of the panel, with these differences: the mean
elevation and the mean slope may differ by 0.01 m and 0.005 % (the panel averages
sub-catchment means rounded to 0.01), the outlet is the centre of the outlet cell (the panel takes
the end of the outlet's stream segment snapped to its boundary, up to two cells away), the
perimeter is that of the given polygon (the panel's includes the rings of the micro-holes of its
merged boundary) and the land cover counts every part of a multipart polygon (the panel takes its
largest part). A polygon with cells without NMT data is computed over the cells with data. On the
production rasters a polygon of 33 km² takes about 1 s and the run peaks at about 1.3 GB.

---

### `download_landcover.py`: download land cover

Downloads land cover through Kartograf into its store: BDOT10k (GUGiK; the whole package of a county,
every layer, as a GeoPackage) or CORINE (Copernicus, a raster). A package that is already local is
used again without a request. A bbox or a point gets every county it intersects.

```bash
cd backend

# BDOT10k for the area around a point (every county the square intersects)
.venv/bin/python -m scripts.download_landcover --lat 52.23 --lon 21.01 --buffer 5 \
    --root ../cache/kartograf

# BDOT10k for one county (powiat) by its TERYT code
.venv/bin/python -m scripts.download_landcover --teryt 1465 --root ../cache/kartograf

# CORINE Land Cover
.venv/bin/python -m scripts.download_landcover --lat 52.23 --lon 21.01 \
    --provider corine --year 2018
```

**Parameters:**

| Parameter | Description | Default |
|---|---|---|
| `--lat`, `--lon` | the centre (WGS84) | - |
| `--buffer` | the buffer radius in km | 5 |
| `--teryt` | the TERYT code of a county (4 digits) | - |
| `--godlo` | a sheet code | - |
| `--provider`, `-p` | `bdot10k` or `corine` | `bdot10k` |
| `--year` | the CORINE reference year (1990, 2000, 2006, 2012, 2018) | 2018 |
| `--root` | the Kartograf store | `../cache/kartograf` |
| `--metadata-cache` | the SQLite metadata cache | none |
| `--no-skip-existing` | fetch the files again although a version is local | off |
| `--dry-run` | only show what would be downloaded | off |

One of `--teryt`, `--godlo` or `--lat` with `--lon` is required. The file of a county is
`<root>/landcover/pl_bdot10k_gpkg/teryt/<teryt>.gpkg`; the exit code is 1 when the download failed or
a county failed. The hydro layers are not selected here: `merge_hydro_gpkgs()` keeps `SWRS`, `SWKN`,
`SWRM` and `PTWP` when the packages are merged for stream burning.

---

### `import_landcover.py`: import land cover into the database

Imports the `PT*` layers of a BDOT10k GeoPackage into the table `land_cover` with a category, a CN
value and the imperviousness.

```bash
cd backend

# Import the package of a county
.venv/bin/python -m scripts.import_landcover \
    --input ../cache/kartograf/landcover/pl_bdot10k_gpkg/teryt/1465.gpkg

# Dry run: show what would be imported
.venv/bin/python -m scripts.import_landcover --input <package>.gpkg --dry-run

# Delete the existing land cover first
.venv/bin/python -m scripts.import_landcover --input <package>.gpkg --clear-existing
```

**Parameters:**

| Parameter | Description | Default |
|---|---|---|
| `--input`, `-i` | path to the `.gpkg` file (required) | - |
| `--batch-size` | records per database batch | 1000 |
| `--clear-existing` | delete the existing `land_cover` data first | off |
| `--dry-run` | only show what would be imported | off |

**The BDOT10k mapping to categories and CN:**

| BDOT10k code | Hydrograf category | CN | Imperviousness |
|---|---|---|---|
| PTLZ | `las` | 60 | 0.0 |
| PTTR, PTUT | `grunt_orny` | 78 | 0.1 |
| PTWP | `woda` | 100 | 1.0 |
| PTWZ, PTRK | `łąka` | 70 | 0.0 |
| PTZB | `zabudowa_mieszkaniowa` | 85 | 0.5 |
| PTKM, PTPL | `droga` | 98 | 0.95 |
| PTGN, PTNZ, PTSO | `inny` | 75 | 0.2 |

Any other `PT*` layer gets the category `inny`, CN 75 and imperviousness 0.2.

---

### `preprocess_precipitation.py`: IMGW precipitation

Downloads the PMAXTP maximum precipitation of IMGW (through Obserwator, the package `obserwator`
at the pinned commit `1ee5457`) for a grid of points inside a
bounding box and stores every scenario, 16 durations x 27 probabilities = 432 per point, in the table
`precipitation_data`.

```bash
cd backend

# A small test around Warsaw
.venv/bin/python -m scripts.preprocess_precipitation --bbox "20.8,52.1,21.2,52.4" --spacing 5.0

# Dry run: show the grid points
.venv/bin/python -m scripts.preprocess_precipitation --bbox "20.8,52.1,21.2,52.4" --dry-run
```

| Parameter | Description | Default |
|---|---|---|
| `--bbox` | the bounding box (WGS84): `min_lon,min_lat,max_lon,max_lat` (required) | - |
| `--spacing` | the grid spacing in km | 2.0 |
| `--delay` | the delay between the requests in s | 0.5 |
| `--dry-run` | only show the grid points, download nothing | off |

---

## Checking the data

### In the database

```bash
# Connect to the database
docker exec -it hydro_db psql -U hydro_user -d hydro_db
```

```sql
-- Streams per accumulation threshold
SELECT threshold_m2,
       COUNT(*) AS segments,
       ROUND(SUM(length_m) / 1000.0) AS length_km,
       MAX(strahler_order) AS max_strahler
FROM stream_network
GROUP BY threshold_m2
ORDER BY threshold_m2;

-- Sub-catchments per accumulation threshold
SELECT threshold_m2,
       COUNT(*) AS catchments,
       ROUND(SUM(area_km2)::numeric, 1) AS area_km2
FROM stream_catchments
GROUP BY threshold_m2
ORDER BY threshold_m2;
```

### In QGIS

1. Run `process_dem.py` with `--save-intermediates`.
2. Open the generated GeoTIFF files in QGIS.
3. Check:
   - `*_02_filled.tif`: the depressions are filled
   - `*_03_flowdir.tif`: the flow directions make sense
   - `*_04_flowacc.tif`: the streams lie in the valleys
   - `*_06_streams.tif`: the mask matches the real streams

---

## Known limitations

1. **Memory**: the whole raster is loaded into RAM. A raster of 113 million cells with the 1000 m²
   threshold runs out of the 8 GB of memory while the sub-catchments are polygonized; `bootstrap.py`
   therefore starts at 10000 m² (`--hydro-resolution` of `process_dem.py` reduces the grid). The
   peak is ~103 B per cell of the raster (`docs/TECHNICAL_DEBT.md`); `--from-intermediates` needs
   ~85 B per cell.
2. **Coordinate system**: only EPSG:2180 (PL-1992) is processed; sheets in PUWG 2000 are reprojected
   to it before the mosaic is built.
3. **`analyze_watershed.py` delineates sub-catchments, not cells**: step 3 runs the code of
   `POST /api/delineate-watershed` (precomputed mode) on the catchment graph of the database, so the
   catchments of `--threshold-m2` (default 10000, one of the thresholds of `process_dem`) must be
   loaded (`--process` or the bootstrap) and the boundary is the merge of whole sub-catchments, not a
   polygon around single cells. The cell layer of `--save-qgis` and the cell elevation histogram of
   the figures are gone (the hypsometric curve replaces the histogram). Tests:
   `tests/unit/test_analyze_watershed_delineate.py` (step 3 on a synthetic graph, offline) and
   `tests/unit/test_process_dem_callers.py` (the DEM step before it).
4. **Real downloads are not tested**: the offline test suite runs the real Kartograf against stubbed
   providers (`docs/integrations/KARTOGRAF.md` §10).
