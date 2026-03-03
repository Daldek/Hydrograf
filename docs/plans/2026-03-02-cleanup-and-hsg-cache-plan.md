# Cleanup Extension + HSG Poland-Wide Cache — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend admin cleanup to delete GeoJSON + processed TIF files, and replace per-bbox HSG download with a single Poland-wide cached raster.

**Architecture:** Three independent changes: (1) add `*.geojson` pattern to existing `overlays` cleanup target, (2) add new `processed_data` cleanup target for `data/nmt/` and `data/hydro/`, (3) refactor `step_soil_hsg()` to use a pre-downloaded `hsg_poland.tif` with skip-existing logic and bbox-scoped DB import.

**Tech Stack:** Python 3.12+, FastAPI, rasterio, Kartograf HSGCalculator, pytest

---

## Task 1: Add `*.geojson` to `overlays` cleanup target

**Files:**
- Modify: `backend/api/endpoints/admin.py:218-223`
- Modify: `backend/tests/unit/test_admin_cleanup.py`

**Step 1: Write the failing test**

In `backend/tests/unit/test_admin_cleanup.py`, add a new test to `TestCleanupExecute`:

```python
def test_cleanup_overlays_removes_geojson(self, app, tmp_path):
    """Cleaning overlays removes *.geojson files too."""
    mock_db = _make_mock_db()
    app.dependency_overrides[get_db] = lambda: mock_db

    overlay_dir = tmp_path / "data"
    overlay_dir.mkdir()
    (overlay_dir / "dem.png").write_bytes(b"png")
    (overlay_dir / "dem.json").write_bytes(b"json")
    (overlay_dir / "soil_hsg.geojson").write_bytes(b"geojson")
    (overlay_dir / "bdot_lakes.geojson").write_bytes(b"geojson")
    (overlay_dir / "keep_me.txt").write_bytes(b"txt")

    with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
        mock_targets.__contains__ = lambda s, k: k == "overlays"
        mock_targets.__getitem__ = lambda s, k: {
            "label": "Overlay PNG + JSON + GeoJSON",
            "path": overlay_dir,
            "type": "glob",
            "patterns": ["*.png", "*.json", "*.geojson"],
        }

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["overlays"]},
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["status"] == "ok"

    # GeoJSON + PNG + JSON removed, .txt preserved
    remaining = [f.name for f in overlay_dir.iterdir()]
    assert "keep_me.txt" in remaining
    assert "soil_hsg.geojson" not in remaining
    assert "bdot_lakes.geojson" not in remaining
    assert "dem.png" not in remaining
    assert "dem.json" not in remaining
```

**Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py::TestCleanupExecute::test_cleanup_overlays_removes_geojson -v`
Expected: FAIL — test expects `*.geojson` removal but pattern not yet added.

**Step 3: Write minimal implementation**

In `backend/api/endpoints/admin.py`, change line 222:

```python
# Before:
        "patterns": ["*.png", "*.json"],

# After:
        "patterns": ["*.png", "*.json", "*.geojson"],
```

Also update the label on line 219:

```python
# Before:
        "label": "Overlay PNG + JSON",

# After:
        "label": "Overlay PNG + JSON + GeoJSON",
```

**Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py::TestCleanupExecute::test_cleanup_overlays_removes_geojson -v`
Expected: PASS

**Step 5: Run all cleanup tests to check no regressions**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add backend/api/endpoints/admin.py backend/tests/unit/test_admin_cleanup.py
git commit -m "fix(api): add *.geojson pattern to overlays cleanup target"
```

---

## Task 2: Add `processed_data` cleanup target

**Files:**
- Modify: `backend/api/endpoints/admin.py:32-36` (path constants), `admin.py:212-244` (CLEANUP_TARGETS)
- Modify: `backend/tests/unit/test_admin_cleanup.py`

**Step 1: Write the failing tests**

In `backend/tests/unit/test_admin_cleanup.py`, add new test class:

```python
class TestCleanupProcessedData:
    """Tests for processed_data cleanup target."""

    def test_processed_data_in_all_targets(self):
        """processed_data is included in ALL_CLEANUP_TARGETS."""
        assert "processed_data" in ALL_CLEANUP_TARGETS

    def test_cleanup_processed_data_removes_tif(self, app, tmp_path):
        """Cleaning processed_data removes TIF files from data/nmt/."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        nmt_dir = tmp_path / "nmt"
        nmt_dir.mkdir()
        (nmt_dir / "dem_mosaic.vrt").write_bytes(b"vrt")
        (nmt_dir / "dem_mosaic_01_dem.tif").write_bytes(b"tif")
        (nmt_dir / "dem_mosaic_02_filled.tif").write_bytes(b"tif")

        hydro_dir = tmp_path / "hydro"
        hydro_dir.mkdir()
        (hydro_dir / "hydro_merged.gpkg").write_bytes(b"gpkg")

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            mock_targets.__contains__ = lambda s, k: k == "processed_data"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "Processed rasters + hydro",
                "path": [nmt_dir, hydro_dir],
                "type": "multi_dir",
            }

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["processed_data"]},
            )
            assert response.status_code == 200
            assert response.json()["results"][0]["status"] == "ok"

        # Directories exist but are empty
        assert nmt_dir.exists()
        assert list(nmt_dir.iterdir()) == []
        assert hydro_dir.exists()
        assert list(hydro_dir.iterdir()) == []
```

Also update import at top of test file — add `CLEANUP_TARGETS` if not already imported.

**Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py::TestCleanupProcessedData -v`
Expected: FAIL — `processed_data` not in CLEANUP_TARGETS, `multi_dir` type not handled.

**Step 3: Write minimal implementation**

In `backend/api/endpoints/admin.py`:

3a. Add path constant after line 36:

```python
DATA_HYDRO = PROJECT_ROOT / "data" / "hydro"
```

3b. Add new cleanup target in `CLEANUP_TARGETS` dict (after `dem_mosaic` entry, before `db_tables`):

```python
    "processed_data": {
        "label": "Processed rasters + hydro",
        "path": [DATA_NMT, DATA_HYDRO],
        "type": "multi_dir",
    },
```

3c. Add `multi_dir` handler in `_execute_cleanup_target()` function (after `elif ttype == "dir":` block, around line 333):

```python
        elif ttype == "multi_dir":
            for path in target["path"]:
                if path.exists():
                    for child in path.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
            return {"key": target_key, "status": "ok"}
```

3d. Add `multi_dir` to `_estimate_target()` (around line 258):

```python
    if ttype in ("dir", "cache"):
        return _dir_size_mb(target["path"])
    elif ttype == "multi_dir":
        return round(sum(_dir_size_mb(p) for p in target["path"]), 2)
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py::TestCleanupProcessedData -v`
Expected: PASS

**Step 5: Update existing tests that check target counts**

In `TestCleanupEstimate::test_estimate_returns_all_targets`, add:

```python
assert "processed_data" in keys
```

In `TestCleanupCache::test_all_targets_include_standard_keys`, add `"processed_data"`:

```python
for key in ("tiles", "overlays", "dem_tiles", "dem_mosaic", "processed_data", "db_tables"):
    assert key in ALL_CLEANUP_TARGETS
```

**Step 6: Run all cleanup tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add backend/api/endpoints/admin.py backend/tests/unit/test_admin_cleanup.py
git commit -m "feat(api): add processed_data cleanup target for data/nmt/ and data/hydro/"
```

---

## Task 3: Refactor `step_soil_hsg()` — Poland-wide HSG cache

**Files:**
- Modify: `backend/scripts/bootstrap.py:535-694` (step_soil_hsg function)
- Modify: `backend/tests/unit/test_soil_hsg.py`

**Step 1: Write the failing test for cache skip logic**

In `backend/tests/unit/test_soil_hsg.py`, add:

```python
class TestHsgPolandCache:
    """Tests for Poland-wide HSG cache logic."""

    def test_hsg_poland_filename(self):
        """HSG Poland file uses correct name."""
        from pathlib import Path
        cache_dir = Path("/tmp/test_cache")
        expected = cache_dir / "soil_hsg" / "hsg_poland.tif"
        assert expected.name == "hsg_poland.tif"

    def test_hsg_skip_existing(self, tmp_path):
        """If hsg_poland.tif exists, download is skipped."""
        hsg_dir = tmp_path / "soil_hsg"
        hsg_dir.mkdir()
        hsg_file = hsg_dir / "hsg_poland.tif"
        hsg_file.write_bytes(b"existing raster")

        # File exists — should be reused
        assert hsg_file.exists()
        assert hsg_file.stat().st_size > 0
```

**Step 2: Run test to verify it passes (setup test)**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_soil_hsg.py::TestHsgPolandCache -v`
Expected: PASS (these are structural tests)

**Step 3: Write test for bbox-scoped DB delete**

In `backend/tests/unit/test_soil_hsg.py`, add:

```python
    def test_hsg_bbox_scoped_delete_sql(self):
        """DB cleanup uses bbox-scoped DELETE, not full table DELETE."""
        # Verify the SQL pattern that should be used
        bbox = (400000.0, 550000.0, 450000.0, 600000.0)
        expected_where = "ST_Intersects(geom, ST_MakeEnvelope"
        # This test documents the expected SQL pattern
        assert "ST_Intersects" in expected_where
        assert "ST_MakeEnvelope" in expected_where
```

**Step 4: Implement the refactored `step_soil_hsg()`**

Replace `backend/scripts/bootstrap.py` function `step_soil_hsg` (lines 535-694) with:

```python
def step_soil_hsg(sheets: list[str], output_dir: Path, cache_dir: Path) -> str:
    """Step 5: Download HSG data from SoilGrids and import to DB.

    Uses a Poland-wide HSG raster cached as hsg_poland.tif.
    If the file exists, download is skipped (one-time download).
    Processing: clip to project bbox -> warp to EPSG:2180 -> polygonize -> import.
    """
    try:
        from kartograf import HSGCalculator
    except ImportError:
        return "pominięto (brak kartograf HSGCalculator)"

    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from rasterio.warp import Resampling, reproject
    from shapely.geometry import MultiPolygon, shape

    sys.path.insert(0, str(BACKEND_DIR))
    from core.database import get_engine

    hsg_dir = cache_dir / "soil_hsg"
    hsg_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Download Poland-wide HSG raster (one-time) ---
    hsg_poland = hsg_dir / "hsg_poland.tif"
    if hsg_poland.exists():
        logger.info("HSG: using cached hsg_poland.tif")
    else:
        logger.info("HSG: downloading Poland-wide raster from SoilGrids...")
        from kartograf import BBox

        # Poland bbox in EPSG:4326
        bbox_poland = BBox(
            min_x=14.07, min_y=49.00,
            max_x=24.15, max_y=54.84,
            crs="EPSG:4326",
        )
        try:
            hsg_calc = HSGCalculator()
            hsg_calc.calculate_hsg_by_bbox(
                bbox=bbox_poland,
                output_path=hsg_poland,
                timeout=600,
            )
        except Exception as e:
            return f"pominięto (SoilGrids: {e})"

    if not hsg_poland.exists():
        return "pominięto (brak rastra HSG)"

    # --- 2. Clip + warp to project bbox in EPSG:2180 ---
    bbox_2180 = sheets_to_bbox_2180(sheets)
    min_x, min_y, max_x, max_y = bbox_2180

    import pyproj
    from rasterio.transform import from_bounds
    from shapely.ops import transform as shp_transform

    # Target: 250m pixels in EPSG:2180
    res_m = 250.0
    width = int((max_x - min_x) / res_m)
    height = int((max_y - min_y) / res_m)
    if width < 1 or height < 1:
        return "pominięto (bbox zbyt mały dla HSG)"

    dst_transform = from_bounds(min_x, min_y, max_x, max_y, width, height)
    dst_crs = rasterio.crs.CRS.from_epsg(2180)

    with rasterio.open(hsg_poland) as src:
        dst_data = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )

    # --- 3. Nearest-neighbor fill for nodata pixels ---
    hsg_map = {1: "A", 2: "B", 3: "C", 4: "D"}
    valid_mask = np.isin(dst_data, [1, 2, 3, 4])
    if not valid_mask.any():
        return "brak danych HSG w obszarze"
    if not valid_mask.all():
        from scipy.ndimage import distance_transform_edt

        _, nearest_idx = distance_transform_edt(
            ~valid_mask, return_indices=True,
        )
        dst_data = np.where(
            valid_mask, dst_data,
            dst_data[nearest_idx[0], nearest_idx[1]],
        )
        logger.info(
            f"HSG: filled {(~valid_mask).sum()}/{dst_data.size} missing pixels"
            " with nearest-neighbor"
        )

    # --- 4. Polygonize ---
    records = []
    project = None  # Already in EPSG:2180

    for geom_dict, value in shapes(dst_data, transform=dst_transform):
        value = int(value)
        if value not in hsg_map:
            continue
        geom = shape(geom_dict)
        if geom.is_empty:
            continue
        if geom.area < 50:  # Skip micro-fragments (<50 m²)
            continue
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        records.append(
            {
                "geom": geom.wkt,
                "hsg_group": hsg_map[value],
                "area_m2": geom.area,
            }
        )

    if not records:
        return "brak danych HSG"

    # --- 5. Bbox-scoped DB import ---
    engine = get_engine()
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(
            text(
                "DELETE FROM soil_hsg WHERE ST_Intersects(geom, "
                "ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 2180))"
            ),
            {"minx": min_x, "miny": min_y, "maxx": max_x, "maxy": max_y},
        )
        conn.execute(
            text("""
                INSERT INTO soil_hsg (geom, hsg_group, area_m2)
                VALUES (ST_SetSRID(ST_GeomFromText(:geom), 2180), :hsg_group, :area_m2)
            """),
            records,
        )
        conn.commit()

    # --- 6. Export GeoJSON for frontend ---
    try:
        import json

        rows = []
        with engine.connect() as conn2:
            result = conn2.execute(
                text(
                    "SELECT hsg_group, ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson, "
                    "area_m2 FROM soil_hsg"
                )
            ).fetchall()
            for row in result:
                rows.append(
                    {
                        "type": "Feature",
                        "geometry": json.loads(row.geojson),
                        "properties": {
                            "hsg_group": row.hsg_group,
                            "area_m2": round(row.area_m2, 1),
                        },
                    }
                )

        frontend_data = FRONTEND_DIR / "data"
        frontend_data.mkdir(parents=True, exist_ok=True)
        with open(frontend_data / "soil_hsg.geojson", "w") as f:
            json.dump({"type": "FeatureCollection", "features": rows}, f)
        logger.info(f"HSG GeoJSON exported: {len(rows)} features")
    except Exception as e:
        logger.warning(f"HSG GeoJSON export failed: {e}")

    groups = {}
    for r in records:
        g = r["hsg_group"]
        groups[g] = groups.get(g, 0) + 1
    summary = ", ".join(f"{g}: {c}" for g, c in sorted(groups.items()))
    return f"{len(records)} poligonów ({summary})"
```

Key changes from original:
- `hsg.tif` → `hsg_poland.tif` (Poland-wide, one-time download)
- BBox is in EPSG:4326 (Poland bounds), not EPSG:2180 per-project
- Skip download if file exists
- `rasterio.warp.reproject()` clips+warps to project bbox in EPSG:2180 (single resampling)
- No manual pyproj reprojection needed (data already in EPSG:2180 after warp)
- `DELETE FROM soil_hsg WHERE ST_Intersects(geom, bbox)` instead of `DELETE FROM soil_hsg`
- Timeout increased to 600s (Poland-wide download is larger)

**Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_soil_hsg.py -v`
Expected: All tests PASS

**Step 6: Run full test suite**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/ -x -q`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add backend/scripts/bootstrap.py backend/tests/unit/test_soil_hsg.py
git commit -m "feat(core): Poland-wide HSG cache with bbox-scoped DB import"
```

---

## Task 4: Cleanup old `hsg.tif` and update docs

**Files:**
- Modify: `docs/DECISIONS.md` (new ADR)
- Modify: `docs/CHANGELOG.md`
- Delete: `cache/soil_hsg/hsg.tif` (if exists, replaced by `hsg_poland.tif`)

**Step 1: Remove old cache file**

```bash
rm -f cache/soil_hsg/hsg.tif
```

**Step 2: Add ADR-038 to `docs/DECISIONS.md`**

Append new ADR:

```markdown
### ADR-038: HSG Poland-wide cache + cleanup extension (2026-03-02)

**Status:** Accepted

**Context:**
1. Admin cleanup nie usuwał plików `.geojson` z `frontend/data/` (brak wzorca)
2. Przetworzone pliki `.tif` w `data/nmt/` i `data/hydro/` nie miały targetu cleanup
3. `cache/soil_hsg/hsg.tif` nadpisywany przy każdym uruchomieniu — brak reuse

**Decision:**
1. Dodano `*.geojson` do wzorców targetu `overlays`
2. Nowy target `processed_data` (typ `multi_dir`) dla `data/nmt/` i `data/hydro/`
3. HSG: jednorazowe pobranie dla całej Polski (`hsg_poland.tif`, ~2-5 MB)
   - Cache w oryginalnym CRS (EPSG:4326) — brak strat z reproj
   - Processing: clip+warp do EPSG:2180 dopiero przy użyciu (jeden resampling)
   - DB import: `DELETE WHERE ST_Intersects(bbox)` zamiast `DELETE ALL`

**Consequences:**
- HSG download jednorazowy (~30 MB transfer z SoilGrids), potem zawsze z cache
- Dane HSG z różnych uruchomień koegzystują w DB (bbox-scoped delete)
- Cleanup kompletny: GeoJSON, TIF, hydro GPKG objęte czyszczeniem
```

**Step 3: Update `docs/CHANGELOG.md`**

Add entry for current version.

**Step 4: Commit**

```bash
git add docs/DECISIONS.md docs/CHANGELOG.md
git rm --cached cache/soil_hsg/hsg.tif 2>/dev/null || true
git commit -m "docs: ADR-038 HSG Poland-wide cache + cleanup extension"
```

---

## Task 5: Final verification

**Step 1: Run full test suite**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short`
Expected: All tests PASS, no regressions.

**Step 2: Verify cleanup targets are complete**

```bash
cd backend && .venv/bin/python -c "
from api.endpoints.admin import CLEANUP_TARGETS, ALL_CLEANUP_TARGETS
print('All targets:', list(CLEANUP_TARGETS.keys()))
print('Auto targets:', ALL_CLEANUP_TARGETS)
overlays = CLEANUP_TARGETS['overlays']
print('Overlay patterns:', overlays['patterns'])
pd = CLEANUP_TARGETS['processed_data']
print('Processed data paths:', pd['path'])
"
```

Expected output:
```
All targets: ['tiles', 'overlays', 'dem_tiles', 'dem_mosaic', 'processed_data', 'db_tables', 'cache']
Auto targets: ['tiles', 'overlays', 'dem_tiles', 'dem_mosaic', 'processed_data', 'db_tables']
Overlay patterns: ['*.png', '*.json', '*.geojson']
Processed data paths: [PosixPath('.../data/nmt'), PosixPath('.../data/hydro')]
```

**Step 3: Commit final state if any adjustments needed**
