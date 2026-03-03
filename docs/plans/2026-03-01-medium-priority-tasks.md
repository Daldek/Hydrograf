# Medium Priority Tasks — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement 6 medium-priority backlog items using parallel subagent teams, each on an isolated branch.

**Architecture:** 6 independent teams work on feature branches off `develop`. Each team has 5 roles: Researcher, Developer, Tester, Docs, Team Lead (verifier). A dedicated Merge Agent resolves conflicts before merging to `develop`.

**Tech Stack:** Python 3.12, FastAPI, PostGIS, Leaflet.js, pytest, ruff, Shapely, rasterio, numpy

---

## Team Structure

Each team operates as a subagent group with these roles:

| Role | Responsibility |
|------|---------------|
| **Researcher** | Reads existing code, identifies patterns, dependencies, edge cases |
| **Developer** | Writes production code following TDD (test first) |
| **Tester** | Runs tests, lint (ruff), verifies expected behavior |
| **Docs** | Updates CHANGELOG.md, ADR if needed, inline docstrings where non-obvious |
| **Team Lead** | Creates branch, coordinates team, verifies completeness, commits |

## Branch Strategy

```
develop (base)
├── feature/scripts-tests        ← Team 1 (tests only, no conflicts)
├── feature/boundary-smoothing   ← Team 2 (core/stream_extraction + watershed_service)
├── feature/dem-tiles            ← Team 3 (scripts/bootstrap + frontend/js/map)
├── feature/building-raising     ← Team 4 (core/hydrology + scripts/bootstrap)
├── feature/thematic-layers      ← Team 5 (frontend/js/layers + api/endpoints/tiles)
└── feature/yaml-config          ← Team 6 (core/config + scripts/*)
```

**Conflict zones:** Teams 3 and 4 both modify `scripts/bootstrap.py` — merge Team 3 first (smaller change), then Team 4 rebases.

---

## Team 1: Tests for Scripts & Utils

**Branch:** `feature/scripts-tests`

**Goal:** Add unit tests for untested pure functions in `utils/` and `scripts/`. Target: ~40 new tests. No production code changes.

**Priority order** (by value/effort ratio):
1. `utils/dem_color.py` — pure numpy, trivial
2. `utils/sheet_finder.py` — pure functions, no I/O
3. `scripts/import_landcover.py` — in-memory GeoDataFrames
4. `scripts/bootstrap.py` — pure helpers (parse_bbox, StepTracker)
5. `scripts/generate_depressions.py` — numpy + tmp_path

**Files:**
- Create: `backend/tests/unit/test_dem_color.py`
- Create: `backend/tests/unit/test_sheet_finder.py`
- Create: `backend/tests/unit/test_import_landcover.py`
- Create: `backend/tests/unit/test_bootstrap.py`
- Create: `backend/tests/unit/test_generate_depressions.py`
- Read: `backend/utils/dem_color.py` (source)
- Read: `backend/utils/sheet_finder.py` (source)
- Read: `backend/scripts/import_landcover.py` (source)
- Read: `backend/scripts/bootstrap.py` (source)
- Read: `backend/scripts/generate_depressions.py` (source)
- Read: `backend/tests/unit/test_process_dem.py` (conventions reference)
- Read: `backend/tests/unit/test_download_landcover.py` (conventions reference)

### Task 1.1: Tests for `utils/dem_color.py`

**Context:** `dem_color.py` contains 2 pure numpy functions: `build_colormap(n_steps=256)` returns a `(n_steps, 3) uint8` array with hypsometric colors, and `compute_hillshade(dem, cellsize, azimuth=315, altitude=45)` returns a float64 array 0–1. Both have zero I/O dependencies.

**Step 1: Write failing tests**

```python
# backend/tests/unit/test_dem_color.py
import numpy as np
import pytest
from utils.dem_color import build_colormap, compute_hillshade


class TestBuildColormap:
    def test_default_256_steps(self):
        cmap = build_colormap()
        assert cmap.shape == (256, 3)
        assert cmap.dtype == np.uint8

    def test_custom_steps(self):
        cmap = build_colormap(n_steps=10)
        assert cmap.shape == (10, 3)

    def test_first_color_is_dark_green(self):
        cmap = build_colormap()
        # First stop: RGB(56, 128, 60)
        np.testing.assert_array_equal(cmap[0], [56, 128, 60])

    def test_last_color_is_near_white(self):
        cmap = build_colormap()
        # Last stop: RGB(245, 245, 240)
        np.testing.assert_array_equal(cmap[-1], [245, 245, 240])

    def test_monotonic_red_channel_trend(self):
        """Red channel generally increases from green valleys to white peaks."""
        cmap = build_colormap()
        assert cmap[-1, 0] > cmap[0, 0]

    def test_single_step(self):
        cmap = build_colormap(n_steps=1)
        assert cmap.shape == (1, 3)


class TestComputeHillshade:
    @pytest.fixture()
    def flat_dem(self):
        return np.ones((50, 50), dtype=np.float64) * 100.0

    @pytest.fixture()
    def north_slope_dem(self):
        """DEM sloping downward to the north (row 0 = high, row 49 = low)."""
        dem = np.zeros((50, 50), dtype=np.float64)
        for i in range(50):
            dem[i, :] = 100.0 - i * 2.0  # 2m drop per 5m cell
        return dem

    def test_flat_returns_uniform(self, flat_dem):
        hs = compute_hillshade(flat_dem, cellsize=5.0)
        assert hs.shape == flat_dem.shape
        # Flat terrain → uniform illumination
        assert np.std(hs) < 0.01

    def test_output_range_0_to_1(self, north_slope_dem):
        hs = compute_hillshade(north_slope_dem, cellsize=5.0)
        assert hs.min() >= 0.0
        assert hs.max() <= 1.0

    def test_dtype_float(self, flat_dem):
        hs = compute_hillshade(flat_dem, cellsize=5.0)
        assert hs.dtype == np.float64

    def test_shape_preserved(self, flat_dem):
        hs = compute_hillshade(flat_dem, cellsize=5.0)
        assert hs.shape == flat_dem.shape

    def test_slope_creates_variation(self, north_slope_dem):
        hs = compute_hillshade(north_slope_dem, cellsize=5.0)
        # Sloped terrain should have variation
        assert np.std(hs) > 0.0 or np.allclose(hs, hs[0, 0])
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_dem_color.py -v`
Expected: PASS (these functions already exist, tests should pass immediately — this is testing existing untested code, not TDD for new features)

**Step 3: Verify all pass, then commit**

```bash
git add backend/tests/unit/test_dem_color.py
git commit -m "test(unit): add tests for utils/dem_color.py (build_colormap, compute_hillshade)"
```

### Task 1.2: Tests for `utils/sheet_finder.py`

**Context:** `sheet_finder.py` has ~10 pure functions converting geographic coordinates to Polish map sheet codes (1:10k, 1:25k grids). All are pure math — no I/O, no external deps. Key functions: `coordinates_to_sheet_code(lat, lon, scale)`, `get_sheet_bounds(code)`, `get_sheets_for_bbox(min_lat, min_lon, max_lat, max_lon, scale)`, `get_neighboring_sheets(code)`, `get_sheets_for_point_with_buffer(lat, lon, buffer_km, scale)`.

**Step 1: Read source to understand exact function signatures**

Read: `backend/utils/sheet_finder.py` — note all public function signatures and known coordinate-to-sheet mappings.

**Step 2: Write failing tests**

```python
# backend/tests/unit/test_sheet_finder.py
import pytest
from utils.sheet_finder import (
    coordinates_to_sheet_code,
    get_sheet_bounds,
    get_sheets_for_bbox,
    get_neighboring_sheets,
    get_sheets_for_point_with_buffer,
)


class TestCoordinatesToSheetCode:
    def test_known_poznan_location(self):
        """Poznań center (~52.4°N, 16.9°E) should produce a valid sheet code."""
        code = coordinates_to_sheet_code(52.4, 16.9)
        assert isinstance(code, str)
        assert len(code) > 0

    def test_known_warszawa_location(self):
        """Warszawa center (~52.2°N, 21.0°E) should produce a valid sheet code."""
        code = coordinates_to_sheet_code(52.2, 21.0)
        assert isinstance(code, str)

    def test_same_point_returns_same_code(self):
        c1 = coordinates_to_sheet_code(52.4, 16.9)
        c2 = coordinates_to_sheet_code(52.4, 16.9)
        assert c1 == c2

    def test_different_points_may_differ(self):
        c1 = coordinates_to_sheet_code(50.0, 20.0)
        c2 = coordinates_to_sheet_code(54.0, 14.5)
        assert c1 != c2

    def test_out_of_poland_raises(self):
        with pytest.raises((ValueError, Exception)):
            coordinates_to_sheet_code(40.0, 10.0)  # Italy


class TestGetSheetBounds:
    def test_returns_four_values(self):
        code = coordinates_to_sheet_code(52.4, 16.9)
        bounds = get_sheet_bounds(code)
        assert len(bounds) == 4  # min_lat, min_lon, max_lat, max_lon

    def test_bounds_contain_original_point(self):
        lat, lon = 52.4, 16.9
        code = coordinates_to_sheet_code(lat, lon)
        min_lat, min_lon, max_lat, max_lon = get_sheet_bounds(code)
        assert min_lat <= lat <= max_lat
        assert min_lon <= lon <= max_lon

    def test_bounds_are_positive_area(self):
        code = coordinates_to_sheet_code(52.4, 16.9)
        min_lat, min_lon, max_lat, max_lon = get_sheet_bounds(code)
        assert max_lat > min_lat
        assert max_lon > min_lon


class TestGetSheetsForBbox:
    def test_single_sheet_bbox(self):
        """Tiny bbox within one sheet → at least 1 sheet."""
        sheets = get_sheets_for_bbox(52.40, 16.90, 52.41, 16.91)
        assert len(sheets) >= 1

    def test_larger_bbox_returns_more(self):
        small = get_sheets_for_bbox(52.40, 16.90, 52.41, 16.91)
        large = get_sheets_for_bbox(52.0, 16.0, 53.0, 18.0)
        assert len(large) >= len(small)

    def test_returns_strings(self):
        sheets = get_sheets_for_bbox(52.40, 16.90, 52.41, 16.91)
        assert all(isinstance(s, str) for s in sheets)


class TestGetNeighboringSheets:
    def test_returns_list(self):
        code = coordinates_to_sheet_code(52.4, 16.9)
        neighbors = get_neighboring_sheets(code)
        assert isinstance(neighbors, list)
        assert len(neighbors) >= 4  # at least 4 neighbors (NSEW)

    def test_does_not_include_self(self):
        code = coordinates_to_sheet_code(52.4, 16.9)
        neighbors = get_neighboring_sheets(code)
        assert code not in neighbors


class TestGetSheetsForPointWithBuffer:
    def test_returns_list(self):
        sheets = get_sheets_for_point_with_buffer(52.4, 16.9, buffer_km=5.0)
        assert isinstance(sheets, list)
        assert len(sheets) >= 1

    def test_larger_buffer_returns_more_or_equal(self):
        small = get_sheets_for_point_with_buffer(52.4, 16.9, buffer_km=1.0)
        large = get_sheets_for_point_with_buffer(52.4, 16.9, buffer_km=20.0)
        assert len(large) >= len(small)
```

**Step 3: Run tests**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_sheet_finder.py -v`
Expected: PASS (testing existing code)

**Step 4: Commit**

```bash
git add backend/tests/unit/test_sheet_finder.py
git commit -m "test(unit): add tests for utils/sheet_finder.py (coordinates, bounds, bbox, neighbors)"
```

### Task 1.3: Tests for `scripts/import_landcover.py`

**Context:** `import_landcover.py` has 6 functions. Testable without DB: `get_database_url()` (env var logic), `transform_to_2180(gdf)` (CRS reproject), `prepare_records(layers)` (dict of GeoDataFrames → list of dicts with WKB). Use `unittest.mock.patch` for env vars, `geopandas.GeoDataFrame` for in-memory data. Follow pattern from `test_download_landcover.py`.

**Step 1: Write failing tests**

```python
# backend/tests/unit/test_import_landcover.py
from unittest.mock import patch, MagicMock
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon

from scripts.import_landcover import (
    get_database_url,
    transform_to_2180,
    prepare_records,
)


class TestGetDatabaseUrl:
    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://test:test@localhost/testdb"})
    def test_from_env_var(self):
        url = get_database_url()
        assert "test" in url

    @patch.dict("os.environ", {}, clear=True)
    def test_fallback_default(self):
        url = get_database_url()
        assert isinstance(url, str)
        assert "postgresql" in url


class TestTransformTo2180:
    def test_already_2180_no_change(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [Polygon([(400000, 500000), (400100, 500000), (400100, 500100), (400000, 500100)])]},
            crs="EPSG:2180",
        )
        result = transform_to_2180(gdf)
        assert result.crs.to_epsg() == 2180

    def test_from_4326_transforms(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [Polygon([(16.9, 52.4), (16.91, 52.4), (16.91, 52.41), (16.9, 52.41)])]},
            crs="EPSG:4326",
        )
        result = transform_to_2180(gdf)
        assert result.crs.to_epsg() == 2180
        # Coordinates should now be in meters (Polish grid, ~300k-900k range)
        x = result.geometry.iloc[0].centroid.x
        assert 100_000 < x < 900_000


class TestPrepareRecords:
    def test_returns_list_of_dicts(self):
        poly = Polygon([(400000, 500000), (400100, 500000), (400100, 500100), (400000, 500100)])
        gdf = gpd.GeoDataFrame(
            {"geometry": [poly], "x_kod": ["PTLZ"]},
            crs="EPSG:2180",
        )
        layers = {"PTLZ": gdf}
        records = prepare_records(layers)
        assert isinstance(records, list)
        assert len(records) == 1
        assert "category" in records[0]
        assert "geom_wkb" in records[0] or "geom" in records[0]

    def test_correct_category_mapping(self):
        poly = Polygon([(400000, 500000), (400100, 500000), (400100, 500100), (400000, 500100)])
        gdf_las = gpd.GeoDataFrame({"geometry": [poly], "x_kod": ["PTLZ"]}, crs="EPSG:2180")
        gdf_woda = gpd.GeoDataFrame({"geometry": [poly], "x_kod": ["PTWP"]}, crs="EPSG:2180")
        layers = {"PTLZ": gdf_las, "PTWP": gdf_woda}
        records = prepare_records(layers)
        categories = {r["category"] for r in records}
        assert "las" in categories
        assert "woda" in categories

    def test_empty_layers_returns_empty(self):
        records = prepare_records({})
        assert records == []
```

**Step 2: Run tests, adjust imports if needed**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_import_landcover.py -v`

**Step 3: Fix any import path issues, then commit**

```bash
git add backend/tests/unit/test_import_landcover.py
git commit -m "test(unit): add tests for scripts/import_landcover.py (get_database_url, transform, prepare_records)"
```

### Task 1.4: Tests for `scripts/bootstrap.py` (pure helpers)

**Context:** `bootstrap.py` has testable pure functions: `parse_bbox(bbox_str)` (parses `"min_lon,min_lat,max_lon,max_lat"` → tuple), `StepTracker` class (progress tracking with start/done/fail/is_skipped). These have zero external dependencies.

**Step 1: Write tests**

```python
# backend/tests/unit/test_bootstrap.py
import io
import pytest
from scripts.bootstrap import parse_bbox, StepTracker


class TestParseBbox:
    def test_valid_bbox(self):
        result = parse_bbox("16.9,52.3,17.1,52.5")
        assert len(result) == 4
        assert result[0] == pytest.approx(16.9)
        assert result[1] == pytest.approx(52.3)

    def test_invalid_format_raises(self):
        with pytest.raises((ValueError, SystemExit, Exception)):
            parse_bbox("invalid")

    def test_three_values_raises(self):
        with pytest.raises((ValueError, SystemExit, Exception)):
            parse_bbox("16.9,52.3,17.1")


class TestStepTracker:
    def test_start_and_done(self):
        tracker = StepTracker(total_steps=3)
        tracker.start("Step 1")
        tracker.done()
        assert tracker.current_step == 1

    def test_skip_tracking(self):
        tracker = StepTracker(total_steps=3, skip_steps=[2])
        assert tracker.is_skipped(2)
        assert not tracker.is_skipped(1)

    def test_fail_records_error(self):
        tracker = StepTracker(total_steps=3)
        tracker.start("Step 1")
        tracker.fail("Something went wrong")
        # Should not raise, just record the failure
```

**Step 2: Run tests**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_bootstrap.py -v`

**Step 3: Commit**

```bash
git add backend/tests/unit/test_bootstrap.py
git commit -m "test(unit): add tests for scripts/bootstrap.py (parse_bbox, StepTracker)"
```

### Task 1.5: Final verification

**Step 1: Run full test suite**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -20`
Expected: All existing + new tests pass (563+ → ~600+)

**Step 2: Run ruff**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/ruff check backend/tests/unit/test_dem_color.py backend/tests/unit/test_sheet_finder.py backend/tests/unit/test_import_landcover.py backend/tests/unit/test_bootstrap.py`
Expected: Clean

---

## Team 2: Boundary Simplification (Catchment Smoothing)

**Branch:** `feature/boundary-smoothing`

**Goal:** Replace pixel-staircase catchment boundaries with smooth polygons using Chaikin smoothing in PostGIS. This also improves morphometric accuracy (perimeter, compactness).

**Files:**
- Modify: `backend/core/watershed_service.py:210-221` (add ST_ChaikinSmoothing to merge query)
- Modify: `backend/core/stream_extraction.py:464-478` (increase simplify tolerance)
- Create: `backend/tests/unit/test_boundary_smoothing.py`
- Read: `backend/tests/unit/test_watershed_service.py` (existing tests)
- Modify: `docs/DECISIONS.md` (new ADR-032)
- Modify: `docs/CHANGELOG.md`

### Task 2.1: Research — verify PostGIS ST_ChaikinSmoothing availability

**Step 1: Check PostGIS version in Docker**

Run: `cd /home/claude-agent/workspace/Hydrograf && docker compose exec db psql -U hydro_user -d hydro_db -c "SELECT postgis_full_version();" 2>/dev/null || echo "DB not running — check docs for PostGIS version"`

Expected: PostGIS 3.x — `ST_ChaikinSmoothing` available since PostGIS 2.5.

**Step 2: Test ST_ChaikinSmoothing on sample data**

Run:
```sql
SELECT ST_NPoints(geom) as original,
       ST_NPoints(ST_ChaikinSmoothing(geom, 3)) as smoothed
FROM stream_catchments
WHERE threshold_m2 = 1000
LIMIT 5;
```

Expected: Smoothed version has more points but curves instead of right angles.

### Task 2.2: Write failing test for smoothed merge

**Step 1: Write test**

```python
# backend/tests/unit/test_boundary_smoothing.py
from unittest.mock import MagicMock, patch
import pytest


class TestMergeCatchmentBoundariesSmoothing:
    def test_merge_query_uses_chaikin(self):
        """Verify the SQL query includes ST_ChaikinSmoothing."""
        from core.watershed_service import merge_catchment_boundaries
        import inspect
        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_ChaikinSmoothing" in source

    def test_merge_query_no_snap_to_grid(self):
        """Verify ST_SnapToGrid is NOT used (removed in session 42)."""
        from core.watershed_service import merge_catchment_boundaries
        import inspect
        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_SnapToGrid" not in source
```

**Step 2: Run test — should fail on missing ST_ChaikinSmoothing**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_boundary_smoothing.py -v`
Expected: FAIL — `assert "ST_ChaikinSmoothing" in source`

### Task 2.3: Implement smoothing in `merge_catchment_boundaries()`

**Step 1: Modify SQL query in `watershed_service.py`**

Current SQL (lines 210-221):
```sql
SELECT ST_AsBinary(
    ST_Multi(ST_MakeValid(
        ST_Buffer(ST_Buffer(
            ST_UnaryUnion(ST_Collect(geom)),
        0.1), -0.1)
    ))
) as geom
```

New SQL — add `ST_ChaikinSmoothing` after buffer-debuffer, before ST_Multi:
```sql
SELECT ST_AsBinary(
    ST_Multi(ST_MakeValid(
        ST_ChaikinSmoothing(
            ST_SimplifyPreserveTopology(
                ST_Buffer(ST_Buffer(
                    ST_UnaryUnion(ST_Collect(geom)),
                0.1), -0.1),
            5.0),
        3)
    ))
) as geom
```

Explanation:
- `ST_SimplifyPreserveTopology(geom, 5.0)` — removes redundant vertices (5m tolerance = pixel size), reduces vertex count before smoothing
- `ST_ChaikinSmoothing(geom, 3)` — 3 iterations of Chaikin corner-cutting, converts staircase to smooth curves
- Order matters: simplify first (reduce vertices), then smooth (add curves)

**Step 2: Run test — should now pass**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_boundary_smoothing.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/core/watershed_service.py backend/tests/unit/test_boundary_smoothing.py
git commit -m "feat(core): smooth catchment boundaries with ST_ChaikinSmoothing (ADR-032)"
```

### Task 2.4: Update simplification tolerance in preprocessing

**Step 1: Increase simplify tolerance in `stream_extraction.py`**

In `polygonize_subcatchments()` (line 464), change:
```python
simplify_tol = cellsize  # was: cellsize (5m)
```
to:
```python
simplify_tol = cellsize * 2  # 10m — more aggressive pre-simplification before DB storage
```

This reduces stored geometry size without visible quality loss at 5m NMT resolution.

**Step 2: Run existing tests**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/ -k "catchment or stream_extraction" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/core/stream_extraction.py
git commit -m "refactor(core): increase subcatchment simplify tolerance to 2×cellsize"
```

### Task 2.5: Write ADR-032, update docs

**Step 1: Add ADR-032 to `docs/DECISIONS.md`**

```markdown
### ADR-032: Wygładzanie granic zlewni (Chaikin smoothing)

**Data:** 2026-03-01
**Status:** Accepted

**Kontekst:** Granice zlewni generowane z rastra (rasterio.features.shapes) mają kształt schodkowy (pixel staircase) — każda krawędź składa się z ortogonalnych kroków 5m. Douglas-Peucker z tolerancją 5m redukuje nadmiarowe wierzchołki, ale nie wygładza narożników. Schodkowe granice zawyżają obwód, co wpływa na wskaźniki morfometryczne (Kc, Rc, Re).

**Decyzja:**
1. `ST_SimplifyPreserveTopology(geom, 5.0)` przed wygładzaniem — redukcja wierzchołków
2. `ST_ChaikinSmoothing(geom, 3)` — 3 iteracje wygładzania Chaikin corner-cutting
3. Zwiększenie tolerancji simplify w preprocessingu z `cellsize` do `2*cellsize`

**Konsekwencje:**
- Granice zlewni wizualnie gładkie, bez schodków
- Dokładniejsze wskaźniki morfometryczne (obwód bliższy rzeczywistości)
- Minimalny narzut wydajnościowy (~10-20ms per merge)
- Geometria w DB bez zmian (wygładzanie tylko runtime)
```

**Step 2: Update CHANGELOG.md**

**Step 3: Commit**

```bash
git add docs/DECISIONS.md docs/CHANGELOG.md
git commit -m "docs: ADR-032 boundary smoothing, update CHANGELOG"
```

---

## Team 3: DEM Tiles + Display Quality

**Branch:** `feature/dem-tiles`

**Goal:** Wire `generate_dem_tiles.py` into the bootstrap pipeline (Step 9) so the frontend uses tile pyramid instead of single PNG. Improve color ramp and hillshade quality.

**Files:**
- Modify: `backend/scripts/bootstrap.py:757-791` (step_overlays — add dem tiles generation)
- Modify: `backend/scripts/generate_dem_tiles.py` (adjust defaults)
- Modify: `backend/utils/dem_color.py` (multi-directional hillshade)
- Modify: `frontend/js/map.js:95-136` (loadDemOverlay — verify tile path)
- Create: `backend/tests/unit/test_dem_color_hillshade.py` (if not covered by Team 1)
- Modify: `docs/CHANGELOG.md`

### Task 3.1: Research — verify gdal2tiles availability

**Step 1: Check gdal2tiles in .venv**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -c "from osgeo import gdal; print(gdal.__version__)" 2>/dev/null || echo "GDAL not in venv"`

If not available, check system: `which gdal2tiles.py || dpkg -l | grep gdal`

**Step 2: Verify generate_dem_tiles.py runs standalone**

Read: `backend/scripts/generate_dem_tiles.py` (full file, understand CLI args and output structure)

### Task 3.2: Wire DEM tiles into bootstrap Step 9

**Step 1: Read current `step_overlays()` in `bootstrap.py`**

Read: `backend/scripts/bootstrap.py:757-791`

**Step 2: Add DEM tile generation after overlay PNG**

Add to `step_overlays()`, after the `generate_dem_overlay` call:

```python
# Generate DEM tile pyramid (for high-zoom display)
dem_tiles_dir = Path("frontend/data/dem_tiles")
dem_tiles_meta = Path("frontend/data/dem_tiles.json")
if not dem_tiles_dir.exists() or not dem_tiles_meta.exists():
    from scripts.generate_dem_tiles import generate_tiles as gen_dem_tiles
    gen_dem_tiles(
        input_path=str(vrt_path),
        output_dir=str(dem_tiles_dir),
        output_meta=str(dem_tiles_meta),
        source_crs="EPSG:2180",
        min_zoom=8,
        max_zoom=16,  # 16 sufficient for 5m NMT, saves disk space vs 18
        processes=4,
    )
    tracker.done()
else:
    print("  DEM tiles already exist, skipping")
```

**Step 3: Run ruff on modified file**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/ruff check backend/scripts/bootstrap.py`

**Step 4: Commit**

```bash
git add backend/scripts/bootstrap.py
git commit -m "feat(core): wire DEM tile generation into bootstrap step_overlays"
```

### Task 3.3: Improve multi-directional hillshade

**Step 1: Modify `compute_hillshade()` in `utils/dem_color.py`**

Replace single-direction hillshade with multi-directional (4 azimuths averaged):

```python
def compute_hillshade(dem, cellsize, azimuth=315, altitude=45):
    """Compute multi-directional hillshade for more natural terrain visualization.

    Uses 4 light directions (NW, NE, SE, SW) averaged with weights.
    """
    azimuths = [315, 45, 135, 225]
    weights = [0.4, 0.2, 0.2, 0.2]  # NW dominant (conventional cartographic lighting)

    dzdx = np.gradient(dem, cellsize, axis=1)
    dzdy = np.gradient(dem, cellsize, axis=0)
    slope = np.sqrt(dzdx**2 + dzdy**2)
    slope_rad = np.arctan(slope)
    aspect_rad = np.arctan2(-dzdy, dzdx)

    alt_rad = np.radians(altitude)

    result = np.zeros_like(dem, dtype=np.float64)
    for az, w in zip(azimuths, weights):
        az_rad = np.radians(360 - az + 90)
        hs = (np.cos(alt_rad) * np.sin(slope_rad) * np.cos(az_rad - aspect_rad)
              + np.sin(alt_rad) * np.cos(slope_rad))
        hs = np.clip(hs, 0, 1)
        result += w * hs

    return np.clip(result, 0, 1)
```

**Step 2: Run existing hillshade tests (from Team 1)**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_dem_color.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/utils/dem_color.py
git commit -m "feat(core): multi-directional hillshade (4 azimuths) for better terrain visualization"
```

### Task 3.4: Adjust max zoom for 5m NMT

**Step 1: Modify `generate_dem_tiles.py` defaults**

Change default `--max-zoom` from 18 to 16. At 5m NMT resolution, zoom 16 gives ~2.4m/pixel — sufficient. Zoom 18 would give ~0.6m/pixel with no additional detail, wasting disk space.

Read: `backend/scripts/generate_dem_tiles.py` and find the argparse `--max-zoom` default.

Change: `default=18` → `default=16`

**Step 2: Commit**

```bash
git add backend/scripts/generate_dem_tiles.py
git commit -m "refactor(core): reduce default DEM tile max zoom from 18 to 16 (matches 5m NMT resolution)"
```

### Task 3.5: Update docs

```bash
git add docs/CHANGELOG.md
git commit -m "docs: update CHANGELOG with DEM tiles + hillshade improvements"
```

---

## Team 4: Building Raising from BDOT10k

**Branch:** `feature/building-raising`

**Goal:** Download BUBD (building footprints) from BDOT10k via Kartograf, raise DEM values by +5m under building footprints before stream burning, to prevent unrealistic flow paths through buildings.

**Files:**
- Modify: `backend/core/hydrology.py:115-247` (add `raise_buildings_in_dem()` function, call before burn)
- Modify: `backend/scripts/bootstrap.py:383-470` (download BUBD, pass to process_dem)
- Modify: `backend/scripts/process_dem.py:118-605` (accept building_gpkg param)
- Create: `backend/tests/unit/test_building_raising.py`
- Modify: `docs/DECISIONS.md` (new ADR-033)
- Modify: `docs/CHANGELOG.md`

### Task 4.1: Research — verify BUBD availability in Kartograf

**Step 1: Check Kartograf API for BUBD category**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -c "from kartograf.providers.bdot10k import Bdot10kProvider; help(Bdot10kProvider)" 2>&1 | head -40`

Or check: `backend/.venv/bin/python -c "from kartograf import LandCoverManager; print(dir(LandCoverManager))"`

**Step 2: Identify BUBD layer names**

Expected BDOT10k layers: `OT_BUBD_A` (budynki — buildings), possibly `OT_BUIN_A` (budynki użyteczności publicznej).

### Task 4.2: Write failing test for building raising

**Step 1: Write test**

```python
# backend/tests/unit/test_building_raising.py
import numpy as np
import pytest
from unittest.mock import patch, MagicMock


class TestRaiseBuildingsInDem:
    @pytest.fixture()
    def flat_dem(self):
        """10x10 flat DEM at 100m elevation, 5m cells."""
        return np.ones((10, 10), dtype=np.float64) * 100.0

    @pytest.fixture()
    def dem_transform(self):
        """Affine transform: origin (400000, 500050), 5m cells."""
        from rasterio.transform import from_bounds
        return from_bounds(400000, 500000, 400050, 500050, 10, 10)

    def test_no_buildings_returns_unchanged(self, flat_dem, dem_transform):
        from core.hydrology import raise_buildings_in_dem
        result = raise_buildings_in_dem(
            flat_dem.copy(), dem_transform, crs_epsg=2180,
            building_gpkg=None
        )
        np.testing.assert_array_equal(result, flat_dem)

    def test_building_raises_dem(self, flat_dem, dem_transform):
        """Building footprint should raise DEM by building_raise_m."""
        from core.hydrology import raise_buildings_in_dem
        from shapely.geometry import box
        import tempfile, fiona, os
        from fiona.crs import from_epsg

        # Create a temp GPKG with one building polygon covering center 4 cells
        building = box(400020, 500020, 400030, 500030)  # 10m x 10m square
        tmp = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        tmp.close()
        try:
            schema = {"geometry": "Polygon", "properties": {"typ": "str"}}
            with fiona.open(tmp.name, "w", driver="GPKG",
                           schema=schema, crs=from_epsg(2180)) as dst:
                dst.write({
                    "geometry": building.__geo_interface__,
                    "properties": {"typ": "budynek"}
                })
            result = raise_buildings_in_dem(
                flat_dem.copy(), dem_transform, crs_epsg=2180,
                building_gpkg=tmp.name, building_raise_m=5.0
            )
            # Center cells should be raised
            assert result.max() > 100.0
            assert result.max() == pytest.approx(105.0)
            # Edge cells should remain unchanged
            assert result[0, 0] == pytest.approx(100.0)
        finally:
            os.unlink(tmp.name)
```

**Step 2: Run test — should fail (function doesn't exist)**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_building_raising.py -v`
Expected: FAIL — `ImportError: cannot import name 'raise_buildings_in_dem'`

### Task 4.3: Implement `raise_buildings_in_dem()`

**Step 1: Add function to `core/hydrology.py`**

Add before `burn_streams_into_dem()` (before line 115):

```python
def raise_buildings_in_dem(
    dem: np.ndarray,
    transform: "rasterio.Affine",
    crs_epsg: int,
    building_gpkg: str | None,
    building_raise_m: float = 5.0,
) -> np.ndarray:
    """Raise DEM elevation under building footprints to prevent flow through buildings.

    Args:
        dem: 2D numpy array of elevation values
        transform: rasterio Affine transform
        crs_epsg: CRS EPSG code of the DEM
        building_gpkg: path to GeoPackage with building polygons, or None to skip
        building_raise_m: meters to raise DEM under buildings (default 5.0)

    Returns:
        Modified DEM array with raised building areas
    """
    if building_gpkg is None:
        return dem

    import fiona
    from rasterio.features import rasterize
    from shapely.geometry import shape

    geometries = []
    with fiona.open(building_gpkg) as src:
        src_crs_epsg = src.crs.get("init", "").replace("epsg:", "") if src.crs else None
        for feat in src:
            geom = shape(feat["geometry"])
            if geom.is_valid and not geom.is_empty:
                geometries.append(geom)

    if not geometries:
        return dem

    # Reproject if needed
    if src_crs_epsg and int(src_crs_epsg) != crs_epsg:
        from pyproj import Transformer
        transformer = Transformer.from_crs(
            f"EPSG:{src_crs_epsg}", f"EPSG:{crs_epsg}", always_xy=True
        )
        from shapely.ops import transform as shp_transform
        geometries = [shp_transform(transformer.transform, g) for g in geometries]

    # Rasterize building footprints
    mask = rasterize(
        [(g, 1) for g in geometries],
        out_shape=dem.shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )

    dem[mask == 1] += building_raise_m
    return dem
```

**Step 2: Run test — should pass**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_building_raising.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/core/hydrology.py backend/tests/unit/test_building_raising.py
git commit -m "feat(core): raise_buildings_in_dem() raises DEM +5m under building footprints"
```

### Task 4.4: Wire into pipeline

**Step 1: Add `building_gpkg` parameter to `process_dem()`**

In `backend/scripts/process_dem.py`, add `building_gpkg: str | None = None` parameter to `process_dem()` function signature. Call `raise_buildings_in_dem()` after reading DEM, before `burn_streams_into_dem()`.

**Step 2: Add BUBD download to `bootstrap.py`**

In `step_process_dem()` or a new `step_buildings()`, download BUBD via Kartograf and pass path to `process_dem()`.

**Step 3: Run ruff + existing tests**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/ruff check backend/scripts/process_dem.py backend/scripts/bootstrap.py && backend/.venv/bin/python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -20`

**Step 4: Commit**

```bash
git add backend/scripts/process_dem.py backend/scripts/bootstrap.py
git commit -m "feat(core): wire building raising into preprocessing pipeline"
```

### Task 4.5: ADR-033 + docs

Add ADR-033 documenting the building raising decision. Update CHANGELOG.

```bash
git add docs/DECISIONS.md docs/CHANGELOG.md
git commit -m "docs: ADR-033 building raising from BDOT10k BUBD"
```

---

## Team 5: Thematic Layers (Land Cover + Soil Map)

**Branch:** `feature/thematic-layers`

**Goal:** Add land cover visualization as a map overlay. The `land_cover` table (101k records) is in the DB but has no frontend display. Serve as MVT tiles via the existing tile endpoint pattern.

**Files:**
- Modify: `backend/api/endpoints/tiles.py` (add land_cover tile endpoint)
- Modify: `frontend/js/layers.js:335-454` (add land cover entry to overlay panel)
- Modify: `frontend/js/map.js` (add land cover layer loading)
- Create: `backend/tests/unit/test_tiles_landcover.py`
- Modify: `docs/CHANGELOG.md`

### Task 5.1: Research — existing tile endpoint pattern

**Step 1: Read tiles.py for MVT generation pattern**

Read: `backend/api/endpoints/tiles.py` (full file)

Understand how `streams/{z}/{x}/{y}.pbf` generates MVT from PostGIS using `ST_AsMVT` + `ST_AsMVTGeom`.

### Task 5.2: Write failing test for land cover tiles

**Step 1: Write test**

```python
# backend/tests/unit/test_tiles_landcover.py
from unittest.mock import MagicMock, patch
import pytest


class TestLandCoverTileEndpoint:
    def test_endpoint_exists(self):
        """Verify /api/tiles/landcover/{z}/{x}/{y}.pbf route is registered."""
        from api.endpoints.tiles import router
        routes = [r.path for r in router.routes]
        assert "/tiles/landcover/{z}/{x}/{y}.pbf" in routes or \
               any("landcover" in r for r in routes)
```

**Step 2: Run test — should fail**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_tiles_landcover.py -v`
Expected: FAIL

### Task 5.3: Implement land cover tile endpoint

**Step 1: Add endpoint to `tiles.py`**

Follow the existing `streams` tile pattern. Add:

```python
@router.get("/tiles/landcover/{z}/{x}/{y}.pbf")
async def get_landcover_tile(z: int, x: int, y: int, db=Depends(get_db)):
    """Serve land cover data as MVT tiles."""
    envelope = _tile_envelope(z, x, y)
    query = text("""
        SELECT ST_AsMVT(tile, 'landcover', 4096, 'geom') AS mvt
        FROM (
            SELECT
                ST_AsMVTGeom(geom, :envelope, 4096, 64, true) AS geom,
                category,
                cn_value,
                bdot_class
            FROM land_cover
            WHERE geom && ST_Transform(:envelope, 2180)
        ) AS tile
    """)
    result = db.execute(query, {"envelope": envelope}).scalar()
    if not result:
        return Response(content=b"", media_type="application/x-protobuf")
    return Response(content=bytes(result), media_type="application/x-protobuf")
```

**Step 2: Run test — should pass**

**Step 3: Commit**

```bash
git add backend/api/endpoints/tiles.py backend/tests/unit/test_tiles_landcover.py
git commit -m "feat(api): add /api/tiles/landcover/{z}/{x}/{y}.pbf MVT endpoint"
```

### Task 5.4: Add land cover layer to frontend

**Step 1: Add layer loading in `map.js`**

Add `loadLandCoverVector()` function following `loadStreamsVector()` pattern. Use `L.vectorGrid.protobuf` with category-based styling:

```javascript
function loadLandCoverVector() {
    const CATEGORY_COLORS = {
        'las': '#2E7D32',
        'łąka': '#7CB342',
        'grunt_orny': '#D4A574',
        'zabudowa_mieszkaniowa': '#E53935',
        'zabudowa_przemysłowa': '#757575',
        'droga': '#424242',
        'woda': '#1565C0',
        'inny': '#BDBDBD'
    };

    landCoverLayer = L.vectorGrid.protobuf('/api/tiles/landcover/{z}/{x}/{y}.pbf', {
        vectorTileLayerStyles: {
            landcover: function(properties) {
                return {
                    fill: true,
                    fillColor: CATEGORY_COLORS[properties.category] || '#BDBDBD',
                    fillOpacity: 0.6,
                    stroke: false,
                    weight: 0,
                };
            }
        },
        maxZoom: 18,
        minZoom: 8,
        pane: 'overlayPane',
    });
    return landCoverLayer;
}
```

**Step 2: Add entry to layers panel in `layers.js`**

Add after HSG entry in `init()`:

```javascript
addBdotOverlayEntry(
    overlayGroup,
    'Pokrycie terenu (BDOT10k)',
    () => Hydrograf.map.getLandCoverLayer?.() || null,
    null,
    (opacity) => Hydrograf.map.setLandCoverOpacity?.(opacity),
    30,
    () => Hydrograf.map.loadLandCoverVector(),
);
```

**Step 3: Commit**

```bash
git add frontend/js/map.js frontend/js/layers.js
git commit -m "feat(frontend): add land cover overlay layer with category coloring"
```

### Task 5.5: Update docs

```bash
git add docs/CHANGELOG.md
git commit -m "docs: update CHANGELOG with thematic layers"
```

---

## Team 6: YAML Configuration File

**Branch:** `feature/yaml-config`

**Goal:** Add a `config.yaml` file for pipeline customization — non-standard paths, thresholds, resolution, custom vector sources. Replace hardcoded defaults with config-file values.

**Files:**
- Create: `backend/config.yaml.example` (template with comments)
- Modify: `backend/core/config.py` (add YAML loading)
- Modify: `backend/scripts/bootstrap.py` (read from config)
- Create: `backend/tests/unit/test_yaml_config.py`
- Modify: `docs/CHANGELOG.md`

### Task 6.1: Research — current config structure

**Step 1: Read existing config.py**

Read: `backend/core/config.py` (full file)

Identify all hardcoded values that should be configurable: DB URL, thresholds, DEM resolution, paths, constants.

### Task 6.2: Design config schema and write example

**Step 1: Create `config.yaml.example`**

```yaml
# Hydrograf Pipeline Configuration
# Copy to config.yaml and adjust values.

# Database
database:
  host: localhost
  port: 5432
  name: hydro_db
  user: hydro_user
  password: hydro_password  # CHANGE IN PRODUCTION

# DEM Processing
dem:
  resolution: "5m"           # GUGiK NMT resolution: "1m" or "5m"
  thresholds_m2: [1000, 10000, 100000]
  burn_depth_m: 10.0
  building_raise_m: 5.0      # DEM raise under buildings (0 = disabled)

# Paths (relative to project root)
paths:
  output_dir: "output"
  frontend_data: "frontend/data"
  dem_tiles_dir: "frontend/data/dem_tiles"

# Pipeline steps (true = run, false = skip)
steps:
  download_nmt: true
  process_dem: true
  landcover: true
  soil_hsg: true
  precipitation: true
  depressions: true
  tiles: true
  overlays: true

# Custom data sources (override BDOT10k defaults)
# custom_streams: "path/to/streams.gpkg"    # custom stream network
# custom_buildings: "path/to/buildings.gpkg" # custom building footprints
```

**Step 2: Commit**

```bash
git add backend/config.yaml.example
git commit -m "feat(core): add config.yaml.example template for pipeline customization"
```

### Task 6.3: Write failing test for config loading

**Step 1: Write test**

```python
# backend/tests/unit/test_yaml_config.py
import tempfile
import os
import pytest
import yaml


class TestLoadConfig:
    def test_load_from_file(self, tmp_path):
        from core.config import load_config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "database": {"host": "testhost", "port": 5433},
            "dem": {"resolution": "1m"},
        }))
        config = load_config(str(config_file))
        assert config["database"]["host"] == "testhost"
        assert config["database"]["port"] == 5433

    def test_missing_file_returns_defaults(self):
        from core.config import load_config
        config = load_config("/nonexistent/path.yaml")
        assert "database" in config
        assert "dem" in config

    def test_partial_config_merges_with_defaults(self, tmp_path):
        from core.config import load_config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"dem": {"resolution": "1m"}}))
        config = load_config(str(config_file))
        # dem.resolution overridden
        assert config["dem"]["resolution"] == "1m"
        # database still has defaults
        assert "host" in config["database"]

    def test_get_database_url_from_config(self, tmp_path):
        from core.config import load_config, get_database_url_from_config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "database": {
                "host": "myhost",
                "port": 5433,
                "name": "mydb",
                "user": "myuser",
                "password": "mypass",
            }
        }))
        config = load_config(str(config_file))
        url = get_database_url_from_config(config)
        assert "myhost" in url
        assert "5433" in url
        assert "mydb" in url
```

**Step 2: Run test — should fail**

Run: `cd /home/claude-agent/workspace/Hydrograf && backend/.venv/bin/python -m pytest backend/tests/unit/test_yaml_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_config'`

### Task 6.4: Implement config loading

**Step 1: Add `load_config()` and `get_database_url_from_config()` to `core/config.py`**

```python
import yaml
from copy import deepcopy

_DEFAULT_CONFIG = {
    "database": {
        "host": "localhost",
        "port": 5432,
        "name": "hydro_db",
        "user": "hydro_user",
        "password": "hydro_password",
    },
    "dem": {
        "resolution": "5m",
        "thresholds_m2": [1000, 10000, 100000],
        "burn_depth_m": 10.0,
        "building_raise_m": 5.0,
    },
    "paths": {
        "output_dir": "output",
        "frontend_data": "frontend/data",
        "dem_tiles_dir": "frontend/data/dem_tiles",
    },
    "steps": {
        "download_nmt": True,
        "process_dem": True,
        "landcover": True,
        "soil_hsg": True,
        "precipitation": True,
        "depressions": True,
        "tiles": True,
        "overlays": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(path: str) -> dict:
    """Load config from YAML file, merging with defaults. Missing file → defaults only."""
    import os
    config = deepcopy(_DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)
    return config


def get_database_url_from_config(config: dict) -> str:
    db = config["database"]
    return f"postgresql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['name']}"
```

**Step 2: Run test — should pass**

**Step 3: Commit**

```bash
git add backend/core/config.py backend/tests/unit/test_yaml_config.py
git commit -m "feat(core): add YAML config loading with defaults merge"
```

### Task 6.5: Wire config into bootstrap

**Step 1: Add `--config` flag to `bootstrap.py` argparser**

In `build_parser()`, add:
```python
parser.add_argument("--config", default="config.yaml", help="Path to YAML config file")
```

In `run_pipeline()`, load config and use values instead of hardcoded defaults.

**Step 2: Run ruff + existing tests**

**Step 3: Commit**

```bash
git add backend/scripts/bootstrap.py
git commit -m "feat(core): bootstrap.py reads --config YAML file for pipeline parameters"
```

### Task 6.6: Update docs

Add entry to CHANGELOG. Consider ADR if needed.

```bash
git add docs/CHANGELOG.md
git commit -m "docs: update CHANGELOG with YAML config support"
```

---

## Merge Strategy

After all teams complete their work:

### Merge Order (least to most conflict risk)

1. **Team 1** (`feature/scripts-tests`) — tests only, zero conflicts
2. **Team 2** (`feature/boundary-smoothing`) — core changes, no script overlap
3. **Team 5** (`feature/thematic-layers`) — frontend + API, minimal backend overlap
4. **Team 6** (`feature/yaml-config`) — `config.py` + `bootstrap.py`
5. **Team 3** (`feature/dem-tiles`) — `bootstrap.py` + `dem_color.py`
6. **Team 4** (`feature/building-raising`) — `hydrology.py` + `bootstrap.py` (most overlap with Team 3/6)

### Merge Agent Procedure

For each team branch, in the order above:

```bash
# 1. Checkout develop and pull latest
git checkout develop && git pull

# 2. Merge feature branch
git merge feature/<name> --no-ff -m "merge: feature/<name> into develop"

# 3. If conflicts:
#    a. Resolve conflicts preserving both changes
#    b. Run full test suite: backend/.venv/bin/python -m pytest backend/tests/ -v
#    c. Run ruff: backend/.venv/bin/ruff check backend/
#    d. Commit resolution

# 4. After successful merge, run full verification
backend/.venv/bin/python -m pytest backend/tests/ -v --tb=short
backend/.venv/bin/ruff check backend/

# 5. Delete merged branch
git branch -d feature/<name>
```

---

## Status Tracking

Each team updates their task status in this section. The Team Lead marks items after verification.

### Team 1: Scripts Tests
- [ ] Task 1.1: Tests for `dem_color.py`
- [ ] Task 1.2: Tests for `sheet_finder.py`
- [ ] Task 1.3: Tests for `import_landcover.py`
- [ ] Task 1.4: Tests for `bootstrap.py`
- [ ] Task 1.5: Full suite verification

### Team 2: Boundary Smoothing
- [ ] Task 2.1: Verify PostGIS ST_ChaikinSmoothing
- [ ] Task 2.2: Write failing test
- [ ] Task 2.3: Implement smoothing
- [ ] Task 2.4: Update preprocessing tolerance
- [ ] Task 2.5: ADR-032 + docs

### Team 3: DEM Tiles
- [ ] Task 3.1: Verify gdal2tiles availability
- [ ] Task 3.2: Wire into bootstrap
- [ ] Task 3.3: Multi-directional hillshade
- [ ] Task 3.4: Adjust max zoom
- [ ] Task 3.5: Update docs

### Team 4: Building Raising
- [ ] Task 4.1: Verify BUBD in Kartograf
- [ ] Task 4.2: Write failing test
- [ ] Task 4.3: Implement `raise_buildings_in_dem()`
- [ ] Task 4.4: Wire into pipeline
- [ ] Task 4.5: ADR-033 + docs

### Team 5: Thematic Layers
- [ ] Task 5.1: Research tile pattern
- [ ] Task 5.2: Write failing test
- [ ] Task 5.3: Implement land cover endpoint
- [ ] Task 5.4: Frontend land cover layer
- [ ] Task 5.5: Update docs

### Team 6: YAML Config
- [ ] Task 6.1: Research current config
- [ ] Task 6.2: Design schema + example
- [ ] Task 6.3: Write failing test
- [ ] Task 6.4: Implement config loading
- [ ] Task 6.5: Wire into bootstrap
- [ ] Task 6.6: Update docs

### Merge
- [ ] Merge Team 1 → develop
- [ ] Merge Team 2 → develop
- [ ] Merge Team 5 → develop
- [ ] Merge Team 6 → develop
- [ ] Merge Team 3 → develop
- [ ] Merge Team 4 → develop
- [ ] Final full test suite pass
- [ ] Update docs/PROGRESS.md
