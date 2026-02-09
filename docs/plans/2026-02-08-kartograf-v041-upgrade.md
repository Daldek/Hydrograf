# Kartograf v0.4.0 → v0.4.1 Upgrade + E2E Test

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade Kartograf to v0.4.1, integrate 3 new features (BDOT10k hydro category, geometry file selection, rtree fix), and validate with a full E2E test on sheet N-33-131-C-b-2.

**Architecture:** Kartograf v0.4.1 adds `category="hydro"` to `LandCoverManager` for downloading hydrographic layers (SWRS, SWKN, SWRM, PTWP), `find_sheets_for_geometry()` for precise NMT tile selection from SHP/GPKG files, and fixes rtree spatial index preservation during GPKG merge. We integrate all three into Hydrograf's download/processing pipeline, then run a comprehensive E2E test: download NMT + hydro streams for a single sheet, burn streams into DEM, process at 1m resolution with threshold 5000, vectorize streams, delineate watershed, compute morphometry.

**Tech Stack:** Python 3.12, Kartograf 0.4.1, FastAPI, PostGIS, pyflwdir, rasterio, geopandas

---

## Task 1: Upgrade Kartograf dependency

**Files:**
- Modify: `backend/requirements.txt:37-41`

**Step 1: Upgrade pip package**

Run:
```bash
cd backend && .venv/bin/pip install "kartograf @ git+https://github.com/Daldek/Kartograf.git@v0.4.1" --upgrade
```
Expected: Successfully installed kartograf-0.4.1

**Step 2: Verify installation**

Run:
```bash
cd backend && .venv/bin/python -c "import kartograf; print(kartograf.__version__)"
```
Expected: `0.4.1`

**Step 3: Verify new APIs are available**

Run:
```bash
cd backend && .venv/bin/python -c "
from kartograf import find_sheets_for_geometry
from kartograf.landcover import LandCoverManager
import inspect
sig = inspect.signature(LandCoverManager.download_by_godlo)
print('find_sheets_for_geometry:', find_sheets_for_geometry)
print('download_by_godlo params:', list(sig.parameters.keys()))
"
```
Expected: Both imports work, `download_by_godlo` accepts kwargs

**Step 4: Update requirements.txt**

Change line 37 comment and line 41 pin:
```
# Spatial data download (Kartograf 0.4.1)
```
```
kartograf @ git+https://github.com/Daldek/Kartograf.git@v0.4.1
```

**Step 5: Commit**

```bash
git add backend/requirements.txt
git commit -m "feat(core): upgrade Kartograf v0.4.0 → v0.4.1"
```

---

## Task 2: Add `--category` parameter to download_landcover.py

**Files:**
- Modify: `backend/scripts/download_landcover.py`

**Step 1: Add `category` parameter to `download_landcover()` function**

Add `category: str = "pt"` parameter after `provider`. Pass `category=category` to all three download methods (`download_by_teryt`, `download_by_godlo`, `download_by_bbox`). Update output filename to include category when category != "pt" (e.g., `bdot10k_hydro_godlo_X.gpkg`).

**Step 2: Add `--category` CLI argument**

Add to Data source argument group:
```python
provider_group.add_argument(
    "--category",
    type=str,
    default="pt",
    choices=["pt", "hydro"],
    help="BDOT10k category: 'pt' (land cover) or 'hydro' (hydrography) (default: pt)",
)
```

Pass `category=args.category` to `download_landcover()`.

**Step 3: Update version references in file**

Update all `0.4.0` references to `0.4.1` in docstrings, logger messages, and error messages (4 occurrences).

**Step 4: Test manually**

Run:
```bash
cd backend && .venv/bin/python -m scripts.download_landcover --help
```
Expected: Shows `--category` option with choices `pt`, `hydro`

**Step 5: Commit**

```bash
git add backend/scripts/download_landcover.py
git commit -m "feat(core): add --category hydro support to download_landcover (Kartograf v0.4.1)"
```

---

## Task 3: Add `--geometry` support to download_dem.py

**Files:**
- Modify: `backend/scripts/download_dem.py`

**Step 1: Add `download_for_geometry()` function**

```python
def download_for_geometry(
    geometry_path: Path,
    output_dir: Path,
    scale: str = "1:10000",
    layer: str | None = None,
    skip_existing: bool = True,
) -> list[Path]:
    """Download NMT data for area covered by geometry file (SHP/GPKG)."""
    from kartograf import find_sheets_for_geometry

    logger.info(f"Finding sheets for geometry: {geometry_path}")
    sheets = find_sheets_for_geometry(str(geometry_path), target_scale=scale, layer=layer)
    logger.info(f"Found {len(sheets)} sheets for geometry")

    if not sheets:
        logger.warning("No sheets found for geometry")
        return []

    return download_sheets(sheets, output_dir, skip_existing=skip_existing)
```

**Step 2: Add CLI arguments**

Add `--geometry` and `--layer` to location group:
```python
location_group.add_argument(
    "--geometry",
    type=str,
    help="Path to SHP/GPKG file for tile selection (alternative to --lat/--lon)",
)
location_group.add_argument(
    "--layer",
    type=str,
    default=None,
    help="Layer name in GPKG file (default: first layer)",
)
```

In argument validation, add geometry handling before the `else` error:
```python
elif args.geometry:
    # handled below
    sheets = None
```

In download section, add geometry branch:
```python
if args.geometry:
    downloaded = download_for_geometry(
        geometry_path=Path(args.geometry),
        output_dir=output_dir,
        scale=args.scale,
        layer=args.layer,
        skip_existing=skip_existing,
    )
```

**Step 3: Update version references**

Update all `0.4.0` to `0.4.1` in docstrings and logger messages (7 occurrences).

**Step 4: Test**

Run:
```bash
cd backend && .venv/bin/python -m scripts.download_dem --help
```
Expected: Shows `--geometry` and `--layer` options

**Step 5: Commit**

```bash
git add backend/scripts/download_dem.py
git commit -m "feat(core): add --geometry support to download_dem (Kartograf v0.4.1)"
```

---

## Task 4: Integrate hydro download + geometry into prepare_area.py

**Files:**
- Modify: `backend/scripts/prepare_area.py`

**Step 1: Add `with_hydro` and `geometry_path` parameters to `prepare_area()`**

Add parameters:
```python
with_hydro: bool = False,
geometry_path: Path | None = None,
geometry_layer: str | None = None,
```

**Step 2: Add hydro download step before DEM processing (new Step 2.5)**

After mosaic creation (Step 3) and before DEM processing (Step 4), insert:
```python
# Step 3.5: Download BDOT10k hydrographic data for stream burning (optional)
burn_streams_path = None
if with_hydro:
    logger.info("=" * 60)
    logger.info("Step 3.5: Downloading BDOT10k hydrographic data")
    logger.info("=" * 60)

    try:
        from scripts.download_landcover import download_landcover

        hydro_dir = output_dir.parent / "hydro" if output_dir else Path("../data/hydro")
        hydro_dir.mkdir(parents=True, exist_ok=True)

        # Download hydro data for each sheet
        from utils.sheet_finder import get_sheets_for_point_with_buffer
        hydro_sheets = get_sheets_for_point_with_buffer(lat, lon, buffer_km, scale)

        for sheet_code in hydro_sheets:
            gpkg = download_landcover(
                output_dir=hydro_dir,
                provider="bdot10k",
                godlo=sheet_code,
                category="hydro",
            )
            if gpkg and gpkg.exists():
                burn_streams_path = gpkg
                logger.info(f"Hydro data downloaded: {gpkg}")

        stats["hydro_downloaded"] = burn_streams_path is not None
    except Exception as e:
        logger.warning(f"Hydro download failed: {e}")
        stats["errors"].append(f"Hydro download: {e}")
```

Then pass `burn_streams_path` to `process_dem()`:
```python
dem_stats = process_dem(
    input_path=mosaic_path,
    stream_threshold=stream_threshold,
    batch_size=batch_size,
    dry_run=False,
    save_intermediates=save_intermediates,
    output_dir=output_dir if save_intermediates else None,
    clear_existing=True,
    burn_streams_path=burn_streams_path,  # NEW
)
```

**Step 3: Add geometry-based sheet finding as alternative**

If `geometry_path` is provided, use it instead of point+buffer for finding sheets:
```python
if geometry_path:
    from kartograf import find_sheets_for_geometry
    sheets = find_sheets_for_geometry(str(geometry_path), target_scale=scale, layer=geometry_layer)
else:
    sheets = get_sheets_for_point_with_buffer(lat, lon, buffer_km, scale)
```

Note: When geometry is used, lat/lon become optional (not required).

**Step 4: Add CLI arguments**

```python
# Hydro options
hydro_group = parser.add_argument_group("Hydrographic data (requires Kartograf 0.4.1+)")
hydro_group.add_argument(
    "--with-hydro",
    action="store_true",
    help="Download BDOT10k hydrographic data and burn streams into DEM",
)

# Geometry options
geo_group = parser.add_argument_group("Geometry-based tile selection (requires Kartograf 0.4.1+)")
geo_group.add_argument(
    "--geometry",
    type=str,
    help="Path to SHP/GPKG file for precise tile selection",
)
geo_group.add_argument(
    "--layer",
    type=str,
    default=None,
    help="Layer name in GPKG file (default: first layer)",
)
```

Make `--lat`/`--lon` not required (required only if `--geometry` not provided).

**Step 5: Update version references**

Update `0.4.0` to `0.4.1` (2 occurrences).

**Step 6: Commit**

```bash
git add backend/scripts/prepare_area.py
git commit -m "feat(core): add --with-hydro and --geometry to prepare_area (Kartograf v0.4.1)"
```

---

## Task 5: Update all documentation version references

**Files:**
- Modify: `CLAUDE.md` (1 reference)
- Modify: `docs/KARTOGRAF_INTEGRATION.md` (11+ references, add new sections)
- Modify: `docs/IMPLEMENTATION_PROMPT.md` (1 reference)
- Modify: `docs/QA_REPORT.md` (1 reference — fix v0.3.0 → v0.4.1)
- Modify: `backend/scripts/README.md` (4 references)

**Step 1: Update CLAUDE.md**

Line 180: `v0.4.0` → `v0.4.1`

**Step 2: Update IMPLEMENTATION_PROMPT.md**

Line 28: `v0.4.0` → `v0.4.1`, add BDOT10k hydro to capabilities list.

**Step 3: Fix QA_REPORT.md**

Line 83: `0.3.0` → `0.4.1` (this was missed in previous audit).

**Step 4: Update scripts/README.md**

All 4 references: `0.4.0` → `0.4.1`. Add documentation for new `--category`, `--geometry`, `--with-hydro` options.

**Step 5: Update KARTOGRAF_INTEGRATION.md**

- Update all `0.4.0`/`v0.4.0` references to `0.4.1`/`v0.4.1`
- Add new section for BDOT10k hydro category (SWRS, SWKN, SWRM, PTWP layers)
- Add new section for geometry file selection
- Add note about rtree fix
- Update feature checklist

**Step 6: Commit**

```bash
git add CLAUDE.md docs/KARTOGRAF_INTEGRATION.md docs/IMPLEMENTATION_PROMPT.md docs/QA_REPORT.md backend/scripts/README.md
git commit -m "docs: update Kartograf version references v0.4.0 → v0.4.1 across 5 files"
```

---

## Task 6: Run existing tests

**Step 1: Run full test suite**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```
Expected: All existing tests pass (no regressions from upgrade)

**Step 2: Run linter**

```bash
cd backend && .venv/bin/python -m ruff check .
```
Expected: No errors

**Step 3: Commit if any fixes needed**

---

## Task 7: E2E Test — Download NMT for N-33-131-C-b-2

**Prerequisites:** PostGIS running (`docker compose up -d db`)

**Step 1: Download NMT sheet**

```bash
cd backend && .venv/bin/python -c "
from scripts.download_dem import download_sheets
from pathlib import Path

output_dir = Path('../data/e2e_test')
output_dir.mkdir(parents=True, exist_ok=True)

files = download_sheets(['N-33-131-C-b-2'], output_dir)
print(f'Downloaded: {len(files)} files')
for f in files:
    print(f'  {f} ({f.stat().st_size / 1024 / 1024:.1f} MB)')
"
```
Expected: 1 ASC file downloaded (~25-60 MB)

**Step 2: Download BDOT10k hydro data**

```bash
cd backend && .venv/bin/python -c "
from scripts.download_landcover import download_landcover
from pathlib import Path

output_dir = Path('../data/e2e_test/hydro')
output_dir.mkdir(parents=True, exist_ok=True)

gpkg = download_landcover(
    output_dir=output_dir,
    provider='bdot10k',
    godlo='N-33-131-C-b-2',
    category='hydro',
)
print(f'Downloaded: {gpkg}')
if gpkg and gpkg.exists():
    print(f'Size: {gpkg.stat().st_size / 1024:.1f} KB')

    # Show layers
    import sqlite3
    conn = sqlite3.connect(str(gpkg))
    tables = conn.execute(
        \"SELECT table_name FROM gpkg_contents\"
    ).fetchall()
    print(f'Layers: {[t[0] for t in tables]}')
    for table_name, in tables:
        count = conn.execute(f'SELECT COUNT(*) FROM \"{table_name}\"').fetchone()[0]
        print(f'  {table_name}: {count} features')
    conn.close()
"
```
Expected: GPKG file with hydrographic layers (SWRS, SWKN, SWRM, PTWP — whichever exist in the area)

**Step 3: Commit E2E data note (no data files)**

Note: Data files go in `data/` which is gitignored. No commit needed here.

---

## Task 8: E2E Test — Process DEM with stream burning

**Step 1: Process DEM at 1m resolution with burned streams**

```bash
cd backend && .venv/bin/python -c "
import time
from pathlib import Path
from scripts.process_dem import process_dem

# Find NMT file
nmt_dir = Path('../data/e2e_test')
nmt_files = list(nmt_dir.glob('*.asc'))
if not nmt_files:
    nmt_files = list(nmt_dir.glob('*.tif'))
input_path = nmt_files[0]

# Find hydro GPKG
hydro_dir = Path('../data/e2e_test/hydro')
hydro_files = list(hydro_dir.glob('*.gpkg'))
burn_path = hydro_files[0] if hydro_files else None

print(f'Input: {input_path}')
print(f'Burn streams: {burn_path}')

start = time.time()
stats = process_dem(
    input_path=input_path,
    stream_threshold=5000,
    save_intermediates=True,
    output_dir=nmt_dir / 'intermediates',
    clear_existing=True,
    burn_streams_path=burn_path,
    burn_depth_m=5.0,
)
elapsed = time.time() - start

print()
print('=' * 60)
print('RESULTS')
print('=' * 60)
print(f'Grid: {stats[\"ncols\"]}x{stats[\"nrows\"]} ({stats[\"cellsize\"]}m)')
print(f'Total cells: {stats[\"total_cells\"]:,}')
print(f'Valid cells: {stats[\"valid_cells\"]:,}')
print(f'Max accumulation: {stats[\"max_accumulation\"]:,}')
print(f'Mean slope: {stats[\"mean_slope\"]:.1f}%')
if 'burn_cells' in stats:
    print(f'Burned cells: {stats[\"burn_cells\"]:,}')
print(f'Stream cells (>=5000): {stats[\"stream_cells\"]:,}')
if 'stream_segments' in stats:
    print(f'Stream segments: {stats[\"stream_segments\"]:,}')
if 'stream_segments_inserted' in stats:
    print(f'Stream segments inserted: {stats[\"stream_segments_inserted\"]:,}')
print(f'Records inserted: {stats[\"inserted\"]:,}')
print(f'Time: {elapsed:.1f}s')
print()
print('Intermediate rasters saved:')
for f in sorted((nmt_dir / 'intermediates').glob('*.tif')):
    print(f'  {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)')
"
```

Expected output should include:
- All 10 intermediate rasters (DEM, burned, filled, flowdir, flowacc, slope, streams, stream_order, twi, aspect)
- burn_cells > 0 (streams were burned)
- stream_segments > 0 (vectorized streams)
- All records inserted to DB

**Step 2: Verify intermediate rasters**

```bash
ls -la ../data/e2e_test/intermediates/*.tif
```
Expected: 10 GeoTIFF files

---

## Task 9: E2E Test — Delineate watershed + morphometry

**Step 1: Find point with highest accumulation and run full analysis**

```bash
cd backend && .venv/bin/python -c "
import sys, time
sys.path.insert(0, '.')
from core.database import get_db
from core.watershed import find_nearest_stream, traverse_upstream, build_boundary, calculate_watershed_area_km2
from core.morphometry import build_morphometric_params
from utils.geometry import transform_pl1992_to_wgs84
from sqlalchemy import text

db = next(get_db())

# Find the cell with highest accumulation (= main outlet of the sheet)
result = db.execute(text('''
    SELECT id, ST_X(geom) as x, ST_Y(geom) as y,
           elevation, flow_accumulation, slope
    FROM flow_network
    WHERE is_stream = TRUE
    ORDER BY flow_accumulation DESC
    LIMIT 1
''')).fetchone()

print(f'Max accumulation cell: id={result.id}, acc={result.flow_accumulation:,}')
print(f'  Position: ({result.x:.1f}, {result.y:.1f}) EPSG:2180')

# Transform to WGS84 for reference
from shapely.geometry import Point
lat, lon = transform_pl1992_to_wgs84(result.x, result.y)
print(f'  WGS84: ({lat:.6f}, {lon:.6f})')

# Use find_nearest_stream from that point
point = Point(result.x, result.y)
outlet = find_nearest_stream(point, db, max_distance_m=100)
print(f'Outlet: id={outlet.id}, acc={outlet.flow_accumulation:,}')

# Traverse upstream
start = time.time()
cells = traverse_upstream(outlet.id, db, max_cells=10_000_000)
elapsed_traverse = time.time() - start
print(f'Watershed cells: {len(cells):,} (traverse: {elapsed_traverse:.1f}s)')

# Build boundary
actual_cell_size = (cells[0].cell_area ** 0.5) if cells else 1.0
boundary = build_boundary(cells, method='polygonize', cell_size=actual_cell_size)
area_km2 = calculate_watershed_area_km2(cells)
print(f'Area: {area_km2:.4f} km2')
print(f'Boundary vertices: {len(boundary.exterior.coords)}')

# Morphometry
start = time.time()
morph = build_morphometric_params(
    cells=cells,
    boundary=boundary,
    outlet=outlet,
    cn=75,
    include_stream_coords=False,
)
elapsed_morph = time.time() - start

print()
print('=' * 60)
print('MORPHOMETRIC PARAMETERS')
print('=' * 60)
for key, value in morph.items():
    if isinstance(value, float):
        print(f'  {key}: {value:.4f}')
    elif key not in ('main_stream_coords', 'source', 'crs'):
        print(f'  {key}: {value}')
print(f'Morphometry time: {elapsed_morph:.1f}s')

db.close()
"
```

Expected: Full morphometric output with area_km2, perimeter_km, length_km, channel_length_km, channel_slope_m_per_m, elevation stats, slope stats, CN, etc.

---

## Task 10: Update PROGRESS.md and CHANGELOG.md

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/CHANGELOG.md`

**Step 1: Update PROGRESS.md**

- Update Kartograf row: `v0.4.0` → `v0.4.1` with new features
- Update "Ostatnia sesja" with what was done
- Add E2E test results

**Step 2: Update CHANGELOG.md**

Add new entry for v0.4.1 upgrade:
- Kartograf v0.4.0 → v0.4.1
- BDOT10k hydro category support
- Geometry file selection
- rtree fix (automatic)
- E2E test results

**Step 3: Commit**

```bash
git add docs/PROGRESS.md docs/CHANGELOG.md
git commit -m "docs: update PROGRESS and CHANGELOG with Kartograf v0.4.1 and E2E results"
```

---

## Task 11: Write comprehensive session report

**Step 1: Write report to `docs/plans/2026-02-08-kartograf-v041-report.md`**

Include:
- Summary of all changes made
- E2E test results (all numbers, timings)
- Intermediate raster layers generated
- Stream burning results
- Vectorization results
- Watershed delineation results
- Morphometric parameters table
- Any issues encountered and how they were resolved

**Step 2: Final commit**

```bash
git add docs/plans/
git commit -m "docs: comprehensive session report — Kartograf v0.4.1 upgrade + E2E test"
```
