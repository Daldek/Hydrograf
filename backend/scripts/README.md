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
| `frontend/data/` | overlays (PNG, JSON), the DEM tile pyramid, GeoJSON exports, `instance.json` (the area of the instance for the welcome screen) |
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
| 5 | HSG: the raster of Poland (a version of the store), clipped to the mosaic, polygonized into `soil_hsg`, the soil under the wetlands (`OT_OIMK_A`) of the BDOT10k packages of step 4 group D (ADR-078); from a set: the pinned raster and packages. The map layer `frontend/data/soil_hsg.geojson` is simplified by 5 m | `--skip-hsg` |
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
| `--area-name` | the name of the data area on the welcome screen and in the guide (`instance.json`) | the Archiwista project's name, else the boundary file's stem |
| `--output` | output directory | `../data/` |
| `--cache-dir` | directory of the cached downloads: the Kartograf store is `<cache-dir>/kartograf` | `paths.cache_dir` of the configuration (`cache/` in the repository root) |
| `--config` | YAML configuration file | `config.yaml` |
| `--port` | HTTP port of the server | 8080 |
| `--dry-run` | only show what would be done; with `--project`, after every check of the set | off |
| `--allow-uncovered` | warn instead of refusing when the NMT sheets leave part of the area, or a hole inside their mosaic, without data (ADR-076) | off |

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

**Enclosed nodata** (`dem.fill_enclosed_nodata` of the configuration, default `false`): pyflwdir's
depression fill takes every cell next to nodata for an outlet, so a nodata area that the DEM data
encloses (a sheet missing from the mosaic; the repair of small holes, `fill_internal_nodata_holes`,
fills at most three cells in from their edge) drains the land around it: an endorheic area, whose
streams and sub-catchments have no downstream link. With `true` step 3 interpolates every nodata area
that does not reach the frame of the raster (8-connected) from the data around it (GDAL's inverse
distance weighting, `core.hydrology.interpolate_enclosed_nodata`) before anything else, so the fill
fills it like any ground and every cell drains to the outer edge of the data. The filled cells are DEM
cells of the run from then on: owned by a unit, routed and published in every raster, `01_dem`
included, and the depressions of step 7 count them. A value that is not `true` or `false` is refused
(`validation_error`, exit 2). The run logs the setting, step 3 reports the filled cells, a run by
units records it in its settings and the record of a set keeps it.

**Coverage of the area** (ADR-076): the sheets of the mosaic must cover the area and enclose no
hole. The frames of the sheets (their meridians and parallels projected to EPSG:2180) are unioned;
what lies outside them, of the area (the outline of `--project`, `--boundary-file` or `--bbox`, the
frames of `--sheets`) or of a hole that the frames enclose, is uncovered, parts narrower than three
cells of `--resolution` left out. An uncovered part is refused (`no_data`, exit 14) with its km² and
the sheets of the grid (`--scale`) that overlap it, for example:

```text
BŁĄD: Arkusze NMT zostawiają bez danych 9.751 km² obszaru lub wnętrza ich mozaiki; brakujące arkusze (2): N-33-118-B-a-4-2, N-33-120-D-a-3-3.
```

A set is checked before step 1, with its other checks; a download run at the start of step 3, on
the sheets that step 2 got (a sheet without data at GUGiK is not among them). `--allow-uncovered`
logs the same text as a warning and goes on: with `dem.fill_enclosed_nodata: true` the holes that
do not reach the frame of the raster are interpolated, the rest stays nodata.

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
`stream_burning`, `fill_enclosed_nodata`, start, end, status); a run without a set removes the file.

**The description of the instance:** after a run whose steps 1 to 3 passed the bootstrap writes
`frontend/data/instance.json` (see [`write_instance_info.py`](#write_instance_infopy-the-description-of-the-instance)),
which the welcome screen and the guide read to name the data area. A failure to write it is a
warning; the run does not fail.

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
| 14 | `no_data` | sheets, counties or the HSG raster missing from the set; the NMT sheets leave part of the area, or a hole inside their mosaic, without data |
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
| `overlays` | PNG and JSON overlays (also `instance.json`) and the DEM tile pyramid (`frontend/data/`) |
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

### `write_instance_info.py`: the description of the instance

Writes `frontend/data/instance.json`, which the welcome screen (`js/welcome.js`) and the guide
`/instrukcja/` (`js/instance.js`) read to name the data area of the instance. The bootstrap writes
it at the end of a run; this script (re)writes it for data that already exist, without a run.
Without the file the front end shows a neutral text („Obszar danych: ten, który mapa pokazuje po
otwarciu”).

```bash
# Inside the API container of the instance (/data and /frontend/data are its mounts)
docker exec hydro_api python -m scripts.write_instance_info \
    --area-name "zlewnia Kaczawy do Legnicy" \
    --boundary-file /data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg

# An instance bootstrapped from a set: the area is the project's, checked by its SHA-256
docker exec hydroni_api python -m scripts.write_instance_info --area-name "obszar h_07"
```

| Parameter | Description | Default |
|---|---|---|
| `--area-name` | the name of the area shown to users (Polish) | the project's name of `bootstrap_set.json`, else the boundary file's stem |
| `--boundary-file` | the boundary whose area (km², EPSG:2180) is given | the area file of the set's project |
| `--boundary-layer` | its layer, for a multi-layer file | the first layer |
| `--resolution` | NMT resolution, `1m` or `5m` | the set's NMT segment, else the cell of `nmt/dem_mosaic.tif` (or `.vrt`) |
| `--data-dir` | the bootstrap's output directory (`bootstrap_set.json`, `nmt/`) | `../data/` (`/data` in the container) |
| `--frontend-data` | the directory nginx serves as `/data/` | `../frontend/data/` (`/frontend/data` in the container) |

The file (`hydrograf-instance/1`) is public, so it carries no server path:

```json
{"schema": "hydrograf-instance/1",
 "area": {"name": "zlewnia Kaczawy do Legnicy", "area_km2": 790.6,
          "boundary": "zlewnia_kaczawy_790km2_przyciecie.gpkg"},
 "counties": null,
 "nmt": {"resolution_m": 5.0, "segment": null},
 "set": null,
 "generated_at": "2026-11-09T22:18:39Z"}
```

`counties` are the TERYT codes of the BDOT10k packages of the set, `nmt.segment` its NMT segment
of the Kartograf store and `set` its project, name and `closed_at`; all three are null for data
not made from a set. `area.name` and `area.area_km2` are null when nothing gives them (a run by
`--bbox` or `--sheets` without `--area-name`).

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
3. Burn the streams into the DEM (`--burn-streams`, optional), then smooth them monotonically: each
   line descends strictly in the direction of its flow, the lines in the order of the flow, which
   corrects bridges and embankments and keeps a river that crosses the edge of the data flowing out
   downstream (ADR-041, ADR-072; `--no-smooth-streams` switches it off). The direction of a line is
   the first of: towards the mouth of its MPHP watercourse, where it meets a line of its receiver;
   down the DEM of its whole watercourse, for a block of lines digitized against the rest of it
   (unless the DEM of the block falls more than 2 m the way it is digitized); the other way where
   the DEM along the line rises by more than 2 m; the way BDOT10k digitizes it (ADR-077). An
   artificial connector through a lake never takes its direction from the DEM along it.
4. Classify the endorheic lakes and their drain points (`--waterbody-mode`): a lake that a
   watercourse line leaves is exorheic, a burned line flowing the way the smoothing takes it and
   any other line the way it is digitized, unless the DEM along it rises by more than 2 m; burn the
   storm-sewer inlets and route the flow accumulation through the sewer graph (optional, ADR-051).
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

### `process_dem.py --units`: process the NMT by PGW units

```bash
cd backend
# Dry run: the owners, the routing, the mosaics; no database
uv run python -m scripts.process_dem --input /data/nmt/dem_mosaic.vrt --output-dir /data/nmt \
    --units pgw.gpkg --units-area area.gpkg --dry-run
# A run of the MPHP catchments grouped by PGW unit: replaces the DEM-derived stream_network and
# stream_catchments in one transaction; the same command resumes it after an interruption
uv run python -m scripts.process_dem --input /data/nmt/dem_mosaic.vrt --output-dir /data/nmt \
    --units pgw.gpkg --units-catchments Obszar_h07.gpkg --units-catchments-layer zlew_h_07 \
    --units-scratch-dir /mnt/scratch --clear-existing
```

`--units` takes Kartograf's PGW GeoPackage (`pl.pgw.pgw`: the layers `zlewnie_jcwp_rzecznych` and
`pozostale_obszary_jcwp`, one owner per `MS_KOD`, EPSG:2180). With `--units-catchments` (and
`--units-catchments-layer`, `--units-catchments-key`, default `ID_HYD_10`) the owners are groups of those
catchments instead: each catchment goes to the PGW unit it overlaps most and an owner is the union of its
catchments; the keys of each owner's catchments are recorded in `processing_units.catchment_keys`
(ESRI:102173 counts as EPSG:2180). `--units-area` (and `--units-area-layer`) is the analysis area: the
polygons are clipped to it, and every valid cell of it must be inside one; `bootstrap --units` uses the
area of `--boundary-file` or `--project`. Cells outside every polygon go to their nearest owner; the DEM
keeps its grid and its nodata. The input VRT must read its sources cell for cell (a VRT that resamples is
refused); the bootstrap averages finer sheets (GUGiK delivers some 5 m sheets as 1 m grids) onto the grid
of the others first, into `<data>/nmt/aligned/`. With `dem.fill_enclosed_nodata` the enclosed nodata is
interpolated before the owners are drawn, so its cells have an owner too. Burning and smoothing streams
(`dem.stream_burning`), raising buildings and the lake classification run on the whole DEM first; then
the depressions of the whole prepared grid are filled once, with pyflwdir's fill and D8 as in the
whole-raster run (the fill and its D8 are written as tiled GeoTIFFs and freed), every owner takes its
cells from them, and the accumulation, flow distance, Strahler order, streams and labels of the whole
grid are computed over disk-backed rasters. The results are those of the whole-raster run: the same
rows, and the same rasters on the cells that hold DEM data. The scratch of a run (the prepared DEM, the
fill and the routing rasters, and the DEM with its enclosed nodata filled) is removed after a successful
run; `--units-scratch-dir DIR` puts it on another disk than `--output-dir`.

A run writes, under `<output-dir>/unit_runs/<token>/`: `units/<stem>_<raster>_<MS_KOD>.tif` (the cells of
one owner), `<stem>_<raster>.vrt` (the mosaic of each raster over the whole grid, named like the
`--save-intermediates` GeoTIFFs), `stage/<MS_KOD>.npz` (the fill and D8 of each owner's cells, removed
once the run is published) and `report.json` (owners, wall time and peak RSS of each stage, counts). It is
recorded in `processing_runs` and `processing_units` (migration 005): each unit is `routed` once its stage
file is saved and `complete` once its tiles are written; the publication replaces the DEM-derived network
and activates the run in one transaction, and `<output-dir>/active_run.json` then names the run
directory, from which the API reads its rasters (a single-raster publication supersedes the run and
removes the file). A failed run is marked `failed` and
the database stays as it was. A later run with the same inputs (the text of the VRTs, the size and mtime
of the other files) and settings resumes the latest stopped or failed run and restores its routed units
whose stage files are intact (the grid is filled again only for a unit that is not); `--no-resume` begins
a new run, and a run held by another process is refused. Tiles come from the published rows
(`generate_tiles.py`, bootstrap step 8) as for any run.

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
podstawowe”, „Wskaźniki kształtu”, „Pokrycie terenu” and „Grupy glebowe (HSG)”, the CN of the
watershed for the antecedent runoff conditions AMC I, II and III and, as a control, the runoff of
that CN against the weighted runoff of the soil-cover complexes, with the polygon as the
boundary of the watershed (no delineation from the NMT), and writes the polygons with their key,
the fields asked for and these values to a new GeoPackage. It reads the rasters that the
pipeline saved in `DEM_DIR` (`dem_mosaic_02_filled`, `_03_flowdir`, `_04_flowacc`,
`_04b_stream_distance`, `_05_slope` and `_10_subcatchments_<threshold>`) and the database
(`land_cover`, `soil_hsg`, the BDOT10k flags and lengths of `stream_network` and
`stream_catchments`), only reading both. The values come from the code behind the panel: the
zonal statistics of the sub-catchments over the cells whose centre lies in the polygon, the flow
paths of `core.divide_flow_path`, the overland segment of `process_dem`, the BDOT10k part of the
main channel of `core.catchment_graph`, the shape indices of `core.morphometry` and the land
cover, the CN of its soil-cover complexes (ADR-075) and the soil groups of
`core.watershed_service`. The outlet is the cell of the largest flow accumulation in the
polygon; the flow paths start in the part of the polygon that drains to it; the main channel
goes up the stream network of the threshold from it, at each confluence into the branch of the
larger accumulation, to its source or to where it flows in from outside the polygon. The length
and the mean width of the watershed and the shape indices computed from them (elongation, form
factor, lemniscate) are left out.

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
| Hydrogram | `cn_amc_i`, `cn_amc_ii`, `cn_amc_iii`: the CN of the watershed for AMC I (dry), II (average, equal to `cn`) and III (wet); I and III are Hydrolog's conversion of II (Hawkins et al. 1985, which approximates NEH 630 ch. 10, table 10-1; integers), as the hydrograph converts it. The CN is the area-weighted composite CN, not a weighting of the runoff |
| Wskaźniki kształtu | `compactness_coefficient`, `circularity_ratio` |
| Pokrycie terenu | `lc_<class>_pct` and `lc_<class>_cn` (AMC II, over the soil-cover complexes of the class) of `grunt_orny`, `las`, `laka`, `zabudowa_mieszkaniowa`, `zabudowa_przemyslowa`, `droga`, `woda`, `inny` |
| Grupy glebowe (HSG) | `hsg_a_pct`, `hsg_b_pct`, `hsg_c_pct`, `hsg_d_pct` (of the area of the polygon with soil groups) |
| Kontrola | `lc_without_hsg_pct` (the land cover outside the soil groups, which takes the groups of the rest of the polygon, ADR-075), `q_cn_mm_p25`, `q_weighted_mm_p25`, `q_cn_mm_p50`, `q_weighted_mm_p50` (below), `polygon_area_km2` (of the geometry), `outlet_upstream_area_km2` (the NMT watershed of the outlet), `polygon_to_upstream_area_ratio` (about 1 for a polygon that is that watershed, less with inflow from outside), `cell_count`, `quality_flag` (`under_100_cells`, `partly_outside_nmt`, `outside_nmt`) |

The runoff columns check the composite CN (ADR-075, amendment of 2026-11-09). For a storm of
P = 25 mm and 50 mm, AMC II, `q_cn_mm_p<P>` is the SCS-CN runoff depth of `cn` and
`q_weighted_mm_p<P>` the area-weighted mean of the runoff depths of the soil-cover complexes, each
from its own CN (the method of weighted Q, NEH 630 ch. 10, p. 10-10); both by Hydrolog's SCS-CN
equation (Ia = 0.2 S), in mm to 0.01. Their difference is the error of the composite CN for that
storm: large in relative terms for small storms and a wide spread of the CN in the polygon (on h07
0.40 against 1.35 mm at 25 mm). The hydrograph and the panel keep the composite CN.

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

### `diagnose_catchment_exits.py`: where the NMT flow leaves given polygons

A diagnosis of `polygon_to_upstream_area_ratio` of the export above: a polygon that is the NMT
watershed of its outlet drains through that one cell, a ratio above 1 means that part of it drains
elsewhere. For every polygon the script takes the cells whose D8 flow leaves it, groups the
connected ones with the same destination (a polygon of the layer, a cell of no polygon, a cell
without NMT data, a pit) into exits and accumulates the flow within the polygon only, so each exit
gets the area of the polygon that leaves through it (the areas of the exits add up to the polygon;
inflow from outside is not counted). The exit that holds the outlet of the export (the cell of the
largest flow accumulation) is marked. It reads the flow directions, the accumulation, the filled
DEM and the slope as the export does (`open_rasters`: the VRT mosaics of an active unit run,
otherwise the GeoTIFFs of `DEM_DIR`), only in the window of each polygon, and needs no database.

```bash
cd backend
.venv/bin/python -m scripts.diagnose_catchment_exits --input zlewnie.gpkg --layer zlew_h_07 \
    --key ID_HYD_10 --ids 1863141,1883617 --output wyjscia_zlewni.gpkg
```

| Parameter | Description | Default |
|---|---|---|
| `--input`, `--layer`, `--key` | the polygons, as for the export; every polygon of the layer can receive the flow | required, the only layer, required |
| `--ids` | the keys to diagnose, comma separated | every polygon |
| `--output` | the new GeoPackage; an existing file is refused. It is written locally and copied, so it may be on a network share | required |
| `--csv` | the new CSV of the summary | `--output` with `.csv` |
| `--min-exit-km2` | the smallest exit that gets its area and counts in `exit_count_over_min` and `receivers` | `0.01` |
| `--dem-dir` | the directory of the rasters | `DEM_DIR` |

The GeoPackage has three layers. `catchment_exits`, a point per exit at its cell of the largest
accumulation within the polygon: `exit_id` (1 the largest), `kind` (`outflow`, `nodata`, `pit`),
`destination` (the key of the receiving polygon, `outside_layer`, `nodata` or `pit`),
`is_export_outlet`, `reenters_polygon` (the flow comes back into the polygon within its window),
`area_km2` and `share_of_polygon` (the part of the polygon that leaves there), `boundary_cells`,
`mean_slope_percent` of that part, `nmt_upstream_area_km2` (the accumulation of the point's cell,
with any inflow; an exit of several cells may drain more than its point) and `elevation_m`.
`catchment_exit_areas`, the part of the polygon that drains to
each exit of at least `--min-exit-km2`. `catchment_exit_summary` (also the CSV), a row per polygon:
`polygon_area_km2`, `cell_area_km2`, `outlet_upstream_area_km2` and
`polygon_to_upstream_area_ratio` (as the export), `exit_count`, `exit_count_over_min`,
`outlet_exit_km2` and `outlet_destination`, `other_exits_km2` (of which `reentering_km2`, `pit_km2`,
`nodata_km2`), `largest_other_exit_km2` and `largest_other_exit_to`, and `receivers` (the area that
leaves to each destination, `key: km²; ...`, the largest first). The 12 polygons of Hydroni
(5 to 30 km², 5 m cells) take about 20 s.

---

### `check_stream_directions.py`: the flow directions of the BDOT10k lines (a diagnostic)

Finds the BDOT10k watercourse lines of an area that are digitized upstream, for a review on a
map; outside the pipeline, which it changes in nothing (ADR-077). It reads the lines of
`OT_SWRS_L`, `OT_SWKN_L` and `OT_SWRM_L` within 1 km of the area, splits a line where an end of
another line lies on its middle and joins the ends within 0.5 m into nodes. For each line it
gathers the evidence that it is digitized upstream: the DEM every 5 m along it (the lowest value
of its last quarter against the lowest of its first, as the smoothing reads it), the order of
the MPHP catchment codes of its river at its ends (with `--catchments`), a run of lines from a
node where only lines begin to one where only lines end, and its direction against the rest of
its watercourse (the lines of one MPHP identifier, else of one name, joined where exactly two of
them meet), whose downstream end the DEM along the whole watercourse decides (more than 0.5 m),
else the digitized majority. The verdict weighs the evidence; the mouth test, independent of
it, orients the lines of an MPHP watercourse towards the node where it meets its receiver (a
line whose identifier is a proper prefix of its own). Beside them it runs the rules of the
smoothing of the pipeline (`core.hydrology._line_directions`, ADR-077) on the burned lines
alone (their ends joined within 0.5 m, the DEM every 5 m), and says which rule decides each
burned line and whether it reverses it.

```bash
cd backend
.venv/bin/python -m scripts.check_stream_directions --hydro ../data/hydro/hydro_merged.gpkg \
    --dem ../data/nmt/dem_mosaic.vrt --area obszar.gpkg:Zlewnie \
    --catchments zlewnie.gpkg:zlew_h_07 --burning main --out /tmp/kierunki.gpkg
```

| Parameter | Description | Default |
|---|---|---|
| `--hydro` | the BDOT10k GeoPackage with `OT_SWRS_L`, `OT_SWKN_L`, `OT_SWRM_L` and `OT_PTWP_A` (`hydro_merged.gpkg`), in EPSG:2180 | required |
| `--dem` | the DEM in EPSG:2180 (a VRT mosaic or a GeoTIFF) | required |
| `--area` | the area, `GPKG[:layer]` (without a layer, the only one of the file) | required |
| `--catchments` | the MPHP catchments with `ID_HYD_10`, `GPKG[:layer]` | none (no catchment evidence) |
| `--burning` | the lines the pipeline burns, as `dem.stream_burning`: `main` or `all` | `all` |
| `--out` | the new GeoPackage; an existing file is refused. SQLite: a local disk, not a share | required |

The output has three layers with Polish names and columns, as the review map reads them:

| Layer | Content |
|---|---|
| `odcinki` | the lines (pieces) with the BDOT10k attributes, `glowny` (a main watercourse, the selection of `main`), `wypalany` (burned with `--burning`), the nodes and kinds at both ends, the DEM along the line (`przyrost_m`, `spadek_m_km`, `nmt`), the catchment order (`mphp`), the run (`ciag_konfliktu`), the watercourse (`ciek`, `odcinek_cieku`, `wzgledem_cieku`, `styk_od`, `styk_do`), the evidence (`dowody_odwr`, `dowody_zgod`), the verdict `werdykt` (`odwrocony`, `podejrzany`, `sprzeczny`, `zgodny`, `nieustalony`), the rules of the smoothing on the burned lines (`regula`: `ujscie` the mouth, `nmt_cieku` the DEM of the watercourse, `nmt_odcinka` the DEM of the line, `digitalizacja` the digitized direction, empty for a line not burned or closed; `odwraca`: the rule reverses it; `blok_zachowany`: a block digitized against its watercourse that the guard of rule 2 keeps, its own DEM falling more than 2 m the way it is digitized), `test_ujscia` (`zgodny`, `odwrocony` or empty when the mouth cannot tell) and `kategoria`: the verdict, with the reversed lines split into `odwrocony`, `odwrocony_lacznik` (an artificial connector through a lake, where the DEM is a water surface) and `odwrocony_siec_oderwana` (a network without a main watercourse), the two doubtful cases |
| `wezly` | the nodes: lines ending and beginning there and the kind (`zrodlo`, `zbieg`, `rozwidlenie`, `same_poczatki`, `same_konce`, `krawedz` and others), as digitized and after the lines of the verdict `odwrocony` are reversed |
| `cieki` | the watercourses drawn downstream: their lines, length, rise, what decided the direction (`nmt`, `wiekszosc`), the lines against it and the watercourse they flow into |

The log ends with the counts over the burned lines: the reversed lines by category, the lines
each rule of the smoothing decides and reverses, the reversed lines of the verdict the rules
reverse and the other lines they reverse, the lines whose `odwraca` the mouth test contradicts
and those the guard keeps, the lines the mouth test checks, confirms and contradicts, and the
lines the mouth says are digitized upstream while the verdict does not. On the Hydroni area h07
(20,279 lines, `main`) a run takes about 55 s and peaks at 2.2 GB (the DEM of the area and
1 km around it).

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

Imports the land cover of a BDOT10k county package into the table `land_cover` (ADR-074,
ADR-078): the `PT*` layers, which partition the county, split by their attributes, with the
industrial complexes of `OT_KUPG_A` cut out of them, then the lawns of the sports and
recreation complexes (`OT_KUSK_A`) and of the airports (`OT_KUKO_A`) cut out of their grass.
Each row gets a category, the imperviousness and its source in `bdot_class`; its CN is that of
its soil-cover complex (ADR-075). The import of a package replaces, in one transaction, the
rows of its area (those whose interior point and more than half of whose area lie in the
package), so importing a package again changes nothing and the neighbouring counties keep
their rows.

```bash
cd backend

# Import the package of a county
.venv/bin/python -m scripts.import_landcover \
    --input ../cache/kartograf/landcover/pl_bdot10k_gpkg/teryt/1465.gpkg

# Dry run: show what would be imported
.venv/bin/python -m scripts.import_landcover --input <package>.gpkg --dry-run

# Delete the land cover of every county first
.venv/bin/python -m scripts.import_landcover --input <package>.gpkg --clear-existing
```

**Parameters:**

| Parameter | Description | Default |
|---|---|---|
| `--input`, `-i` | path to the `.gpkg` file (required) | - |
| `--batch-size` | records per database batch | 1000 |
| `--clear-existing` | delete the land cover of every county first | off |
| `--dry-run` | only show what would be imported (rows and km² per category) | off |

**The BDOT10k sources and their categories:**

| Source (`bdot_class`) | Category | Imperviousness |
|---|---|---|
| `PTLZ` | `las` | 0.0 |
| `PTTR:trawiasta` (`RODZAJ` roślinność trawiasta), `PTUT`, `PTRK` | `łąka` | 0.0 |
| `PTTR:grunty orne` (uprawa na gruntach ornych) | `grunt_orny` | 0.1 |
| `PTZB:jednorodzinna`, `PTZB:pozostała` | `zabudowa_mieszkaniowa` | 0.30 |
| `PTZB:wielorodzinna` | `zabudowa_mieszkaniowa` | 0.65 |
| `PTZB:przem.-skład.`, `PTNZ:przem.-skład.` (teren przemysłowo-składowy) | `zabudowa_przemysłowa` | 0.72 |
| `PTZB:handl.-usług.` | `zabudowa_przemysłowa` | 0.85 |
| `KUPG:<kind>` | `zabudowa_przemysłowa` | 0.72 |
| `PTKM`, `PTPL:utwardzony` (`MATERIALNAWIERZCHNI` beton, bruk, kostka, masa bitumiczna, płyty betonowe) | `droga` | 0.95 |
| `PTWP` | `woda` | 1.0 |
| `PTNZ:urządzenia` (teren pod urządzeniami technicznymi lub budowlami), `PTPL:nieutwardzony` (grunt naturalny, żwir, tłuczeń), `PTWZ`, `PTGN`, `PTSO`, any other `PT*` layer | `inny` | 0.2 |
| `KUSK:<kind>`, `KUKO:lotnisko` (the lawns of the open-space complexes) | `inny` | 0.0 |

A polygon of PTZB, PTTR, PTNZ or PTPL without its attribute or with another value takes the
layer's first category under the plain layer code (`PTZB` `zabudowa_mieszkaniowa`, `PTTR`
`grunt_orny`, `PTNZ` `inny`, `PTPL` `droga`); an unknown value is logged.

The industrial complexes are the `OT_KUPG_A` of the kinds (`RODZAJ`) zakład produkcyjny,
usługowy lub remontowy (`KUPG:zakład prod.`), baza paliw (`KUPG:baza paliw`), gazownia
(`KUPG:gazownia`), elektrociepłownia (`KUPG:elektrociepł.`), zakład utylizacji
(`KUPG:zakład utyliz.`), huta (`KUPG:huta`), rafineria (`KUPG:rafineria`), zakład
metalurgiczny (`KUPG:zakład metal.`) and the thermal and nuclear power plants (`KUPG:el.
cieplna`, `KUPG:el. atomowa`). Their area is cut out of every PT polygon but water and the
industrial land above; overlapping complexes count once. Farms, solar, wind and water power
plants, mines, sewage treatment plants, landfills, waterworks and substations keep the land
cover of the PT layers.

The open-space complexes are the `OT_KUSK_A` of the kinds kompleks sportowo-rekreacyjny
(`KUSK:kompl. sport.`), park lub skwer (`KUSK:park`), ogród botaniczny (`KUSK:ogród botan.`)
and ogród zoologiczny (`KUSK:ogród zoolog.`), and the `OT_KUKO_A` lotnisko lub lądowisko
(`KUKO:lotnisko`). Their area is cut out of the grass (`łąka`) that the industrial complexes
leave and becomes `inny`, which the CN takes as TR-55 open space in good condition (lawns);
the forest, fields, water, paved surfaces and buildings in them keep their category, and
overlapping complexes count once, the airports first. Summer house estates (zespół domów
letniskowych), stations, car parks, petrol stations and the other KU layers keep the land
cover of the PT layers.

The wetlands of `OT_OIMK_A` are not land cover: step 5 of the bootstrap makes the soil under
them group D (ADR-078).

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
