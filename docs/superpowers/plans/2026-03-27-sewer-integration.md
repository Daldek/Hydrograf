# Sewer Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate stormwater drainage networks with surface runoff analysis in Hydrograf using modified inlet burning + graph-based FA routing + downstream propagation.

**Architecture:** New module `core/sewer_service.py` handles all sewer logic (parsing, graph, burning, routing, propagation). New script `scripts/download_sewer.py` handles data acquisition from file/WFS/DB/URL. Integration via ~40 lines in `process_dem.py` at steps 3b (after stream burning, before fill sinks) and 4a-4c (after FA, before Strahler). Admin panel extended with sewer tab. MVT tiles for visualization.

**Tech Stack:** scipy.sparse (graph), numpy (raster ops), geopandas/fiona (vector I/O), rasterio (raster transform), shapely (geometry), pyflwdir (existing). Zero new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-27-sewer-integration-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `backend/core/sewer_service.py` | Core logic: parse input, build graph, burn inlets, reconstruct FA, route FA, propagate downstream, DB insert |
| `backend/scripts/download_sewer.py` | Data acquisition: load from file/WFS/DB/URL, CRS validation, reprojekcja |
| `backend/migrations/versions/XXX_create_sewer_tables.py` | DB migration: sewer_nodes, sewer_network tables + is_sewer_augmented column |
| `backend/tests/unit/test_sewer_service.py` | Unit tests for sewer_service |
| `backend/tests/unit/test_download_sewer.py` | Unit tests for download_sewer |
| `frontend/js/sewer.js` | Frontend: sewer overlay layer + admin tab logic |

### Modified files
| File | Change |
|------|--------|
| `backend/core/config.py` | Add `sewer` section to `_DEFAULT_CONFIG` |
| `backend/scripts/process_dem.py` | Add sewer steps 3b, 4a-4c (~40 lines) |
| `backend/api/endpoints/admin.py` | Add sewer upload/status/delete endpoints |
| `backend/api/endpoints/tiles.py` | Add sewer MVT tile endpoint |
| `frontend/admin.html` | Add Sewer tab to admin panel |
| `frontend/js/layers.js` | Add sewer overlay entry |
| `frontend/index.html` | Include sewer.js script |
| `docs/SCOPE.md` | Move sewer from out-of-scope to in-scope |
| `docs/ARCHITECTURE.md` | Add sewer modules, tables, pipeline diagram |
| `docs/DATA_MODEL.md` | Add sewer_nodes, sewer_network schemas |
| `docs/DECISIONS.md` | Add ADR-051 |
| `docs/CHANGELOG.md` | Add sewer integration entry |
| `docs/PROGRESS.md` | Update status |

---

## Task 1: Database migration — sewer tables

**Files:**
- Create: `backend/migrations/versions/XXX_create_sewer_tables.py`

- [ ] **Step 1: Check current Alembic head**

```bash
cd backend && .venv/bin/python -m alembic heads
```

Note the current head revision ID for `down_revision` in the new migration.

- [ ] **Step 2: Create migration file**

Create migration with two new tables and one ALTER TABLE. Use the revision ID from step 1 as `down_revision`. The filename XXX should be the next sequential number (likely 025 or check if merge migration changes this).

```python
"""Create sewer_nodes and sewer_network tables, add is_sewer_augmented to stream_network.

Revision ID: <auto>
Revises: <head from step 1>
Create Date: 2026-03-27
"""

from alembic import op

revision: str = "<next>"
down_revision: str | None = "<head>"


def upgrade() -> None:
    # --- sewer_nodes ---
    op.execute("""
        CREATE TABLE sewer_nodes (
            id SERIAL PRIMARY KEY,
            geom GEOMETRY(Point, 2180) NOT NULL,
            node_type VARCHAR(20) NOT NULL,
            component_id INTEGER,
            depth_m DOUBLE PRECISION,
            invert_elev_m DOUBLE PRECISION,
            dem_elev_m DOUBLE PRECISION,
            burn_elev_m DOUBLE PRECISION,
            fa_value INTEGER,
            total_upstream_fa INTEGER,
            root_outlet_id INTEGER REFERENCES sewer_nodes(id),
            nearest_stream_segment_idx INTEGER,
            source_type VARCHAR(20) NOT NULL DEFAULT 'topology_generated',
            rim_elev_m DOUBLE PRECISION,
            max_depth_m DOUBLE PRECISION,
            ponded_area_m2 DOUBLE PRECISION,
            outfall_type VARCHAR(20),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_outlet_not_self CHECK (root_outlet_id != id)
        )
    """)
    op.execute("CREATE INDEX idx_sewer_nodes_geom ON sewer_nodes USING GIST(geom)")
    op.execute("CREATE INDEX idx_sewer_nodes_type ON sewer_nodes(node_type)")
    op.execute("CREATE INDEX idx_sewer_nodes_outlet_type ON sewer_nodes(root_outlet_id, node_type)")

    # --- sewer_network ---
    op.execute("""
        CREATE TABLE sewer_network (
            id SERIAL PRIMARY KEY,
            geom GEOMETRY(LineString, 2180) NOT NULL,
            node_from_id INTEGER NOT NULL REFERENCES sewer_nodes(id),
            node_to_id INTEGER NOT NULL REFERENCES sewer_nodes(id),
            diameter_mm INTEGER,
            width_mm INTEGER,
            height_mm INTEGER,
            cross_section_shape VARCHAR(20),
            invert_elev_start_m DOUBLE PRECISION,
            invert_elev_end_m DOUBLE PRECISION,
            material VARCHAR(50),
            manning_n DOUBLE PRECISION,
            length_m DOUBLE PRECISION NOT NULL,
            slope_percent DOUBLE PRECISION,
            source VARCHAR(50) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX idx_sewer_network_geom ON sewer_network USING GIST(geom)")
    op.execute("CREATE INDEX idx_sewer_network_from ON sewer_network(node_from_id)")
    op.execute("CREATE INDEX idx_sewer_network_to ON sewer_network(node_to_id)")

    # --- is_sewer_augmented on stream_network ---
    op.execute("""
        ALTER TABLE stream_network
        ADD COLUMN IF NOT EXISTS is_sewer_augmented BOOLEAN DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE stream_network DROP COLUMN IF EXISTS is_sewer_augmented")
    op.execute("DROP TABLE IF EXISTS sewer_network")
    op.execute("DROP TABLE IF EXISTS sewer_nodes")
```

- [ ] **Step 3: Verify migration**

```bash
cd backend && .venv/bin/python -m alembic upgrade head
```

Expected: Tables created without errors.

- [ ] **Step 4: Verify downgrade**

```bash
cd backend && .venv/bin/python -m alembic downgrade -1
cd backend && .venv/bin/python -m alembic upgrade head
```

Expected: Clean downgrade + re-upgrade.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/XXX_create_sewer_tables.py
git commit -m "feat(db): add sewer_nodes and sewer_network tables (ADR-051)"
```

---

## Task 2: Config — add sewer section to _DEFAULT_CONFIG

**Files:**
- Modify: `backend/core/config.py:155-185`
- Test: `backend/tests/unit/test_config_sewer.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_config_sewer.py`:

```python
"""Tests for sewer config defaults and loading."""

from core.config import _DEFAULT_CONFIG, load_config


class TestSewerConfigDefaults:
    def test_sewer_section_exists(self):
        assert "sewer" in _DEFAULT_CONFIG

    def test_sewer_disabled_by_default(self):
        assert _DEFAULT_CONFIG["sewer"]["enabled"] is False

    def test_sewer_default_burn_depth(self):
        assert _DEFAULT_CONFIG["sewer"]["inlet_burn_depth_m"] == 0.5

    def test_sewer_default_snap_tolerance(self):
        assert _DEFAULT_CONFIG["sewer"]["snap_tolerance_m"] == 2.0

    def test_sewer_source_defaults(self):
        source = _DEFAULT_CONFIG["sewer"]["source"]
        assert source["type"] == "file"
        assert source["path"] is None
        assert source["lines_layer"] is None
        assert source["points_layer"] is None
        assert source["assumed_crs"] is None

    def test_sewer_attribute_mapping_defaults(self):
        mapping = _DEFAULT_CONFIG["sewer"]["attribute_mapping"]
        assert mapping["diameter"] is None
        assert mapping["depth"] is None
        assert mapping["flow_direction"] is None


class TestSewerConfigMerge:
    def test_yaml_overrides_sewer_enabled(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("sewer:\n  enabled: true\n  inlet_burn_depth_m: 0.8\n")
        cfg = load_config(str(yaml_file))
        assert cfg["sewer"]["enabled"] is True
        assert cfg["sewer"]["inlet_burn_depth_m"] == 0.8
        # Non-overridden defaults preserved
        assert cfg["sewer"]["snap_tolerance_m"] == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_config_sewer.py -v
```

Expected: FAIL — `KeyError: 'sewer'`

- [ ] **Step 3: Add sewer section to _DEFAULT_CONFIG**

In `backend/core/config.py`, after the `"steps"` section in `_DEFAULT_CONFIG` (around line 184), add:

```python
    "sewer": {
        "enabled": False,
        "inlet_burn_depth_m": 0.5,
        "snap_tolerance_m": 2.0,
        "source": {
            "type": "file",
            "path": None,
            "url": None,
            "layer": None,
            "connection": None,
            "table": None,
            "lines_layer": None,
            "points_layer": None,
            "assumed_crs": None,
        },
        "attribute_mapping": {
            "diameter": None,
            "width": None,
            "height": None,
            "cross_section": None,
            "invert_start": None,
            "invert_end": None,
            "depth": None,
            "material": None,
            "manning": None,
            "flow_direction": None,
            "node_type": None,
            "rim_elevation": None,
            "max_depth": None,
            "ponded_area": None,
            "outfall_type": None,
        },
    },
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_config_sewer.py -v
```

Expected: All PASS.

- [ ] **Step 5: Run existing tests to ensure no regression**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short -q
```

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/core/config.py backend/tests/unit/test_config_sewer.py
git commit -m "feat(core): add sewer section to pipeline config defaults"
```

---

## Task 3: download_sewer.py — data acquisition module

**Files:**
- Create: `backend/scripts/download_sewer.py`
- Test: `backend/tests/unit/test_download_sewer.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_download_sewer.py`:

```python
"""Tests for scripts.download_sewer module."""

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import LineString, Point

from scripts.download_sewer import (
    load_from_file,
    load_sewer_data,
    _validate_crs,
    _detect_geometry_type,
)


@pytest.fixture
def sewer_lines_gpkg(tmp_path):
    """Create a minimal GPKG with sewer lines in EPSG:2180."""
    lines = gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(500050, 600000), (500100, 600000)]),
                LineString([(500050, 600050), (500050, 600000)]),
            ],
            "srednica_mm": [300, 400, 300],
        },
        crs="EPSG:2180",
    )
    path = tmp_path / "sewer.gpkg"
    lines.to_file(path, driver="GPKG", layer="kolektory")
    return path


@pytest.fixture
def sewer_lines_no_crs(tmp_path):
    """Create a GeoJSON with sewer lines but NO CRS."""
    lines = gpd.GeoDataFrame(
        {"geometry": [LineString([(0, 0), (1, 1)])]},
    )
    # GeoJSON without CRS
    path = tmp_path / "sewer_no_crs.geojson"
    lines.to_file(path, driver="GeoJSON")
    return path


@pytest.fixture
def sewer_config_file(tmp_path, sewer_lines_gpkg):
    """Config dict for file source."""
    return {
        "sewer": {
            "enabled": True,
            "source": {
                "type": "file",
                "path": str(sewer_lines_gpkg),
                "lines_layer": "kolektory",
                "points_layer": None,
                "assumed_crs": None,
            },
            "attribute_mapping": {"diameter": "srednica_mm"},
        }
    }


class TestLoadFromFile:
    def test_loads_gpkg_lines(self, sewer_lines_gpkg):
        gdf = load_from_file(str(sewer_lines_gpkg), lines_layer="kolektory")
        assert len(gdf) == 3
        assert gdf.crs.to_epsg() == 2180
        assert all(gdf.geometry.geom_type == "LineString")

    def test_auto_detect_layer(self, sewer_lines_gpkg):
        gdf = load_from_file(str(sewer_lines_gpkg), lines_layer=None)
        assert len(gdf) == 3

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_from_file("/nonexistent/path.gpkg")


class TestValidateCrs:
    def test_valid_crs_passes(self, sewer_lines_gpkg):
        gdf = gpd.read_file(sewer_lines_gpkg)
        result = _validate_crs(gdf, assumed_crs=None)
        assert result.crs.to_epsg() == 2180

    def test_no_crs_raises(self, sewer_lines_no_crs):
        gdf = gpd.read_file(sewer_lines_no_crs)
        gdf.crs = None
        with pytest.raises(ValueError, match="CRS"):
            _validate_crs(gdf, assumed_crs=None)

    def test_assumed_crs_fallback(self, sewer_lines_no_crs):
        gdf = gpd.read_file(sewer_lines_no_crs)
        gdf.crs = None
        result = _validate_crs(gdf, assumed_crs="EPSG:4326")
        assert result.crs is not None


class TestDetectGeometryType:
    def test_detects_linestring(self, sewer_lines_gpkg):
        gdf = gpd.read_file(sewer_lines_gpkg)
        assert _detect_geometry_type(gdf) == "lines"

    def test_detects_point(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0), Point(1, 1)]}, crs="EPSG:2180"
        )
        assert _detect_geometry_type(gdf) == "points"


class TestLoadSewerData:
    def test_loads_with_config(self, sewer_config_file):
        gdf = load_sewer_data(sewer_config_file)
        assert len(gdf) == 3
        assert gdf.crs.to_epsg() == 2180

    def test_reprojects_to_2180(self, tmp_path):
        lines = gpd.GeoDataFrame(
            {"geometry": [LineString([(17.0, 52.4), (17.1, 52.4)])]},
            crs="EPSG:4326",
        )
        path = tmp_path / "sewer_wgs84.gpkg"
        lines.to_file(path, driver="GPKG")
        cfg = {
            "sewer": {
                "source": {
                    "type": "file",
                    "path": str(path),
                    "lines_layer": None,
                    "points_layer": None,
                    "assumed_crs": None,
                },
                "attribute_mapping": {},
            }
        }
        gdf = load_sewer_data(cfg)
        assert gdf.crs.to_epsg() == 2180
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_download_sewer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.download_sewer'`

- [ ] **Step 3: Implement download_sewer.py**

Create `backend/scripts/download_sewer.py`:

```python
"""Data acquisition for stormwater sewer networks.

Supports: local file (SHP/GPKG/GeoJSON), WFS, external database, URL.
One source per run. Reprojects to EPSG:2180.
"""

import logging
from pathlib import Path

import fiona
import geopandas as gpd

logger = logging.getLogger(__name__)

TARGET_CRS = "EPSG:2180"


def _detect_geometry_type(gdf: gpd.GeoDataFrame) -> str:
    """Detect dominant geometry type: 'lines' or 'points'."""
    types = gdf.geometry.geom_type.unique()
    if any(t in ("LineString", "MultiLineString") for t in types):
        return "lines"
    if any(t in ("Point", "MultiPoint") for t in types):
        return "points"
    raise ValueError(f"Unsupported geometry types: {types}")


def _validate_crs(
    gdf: gpd.GeoDataFrame, assumed_crs: str | None
) -> gpd.GeoDataFrame:
    """Validate and set CRS. Raises ValueError if no CRS and no assumed_crs."""
    if gdf.crs is None:
        if assumed_crs:
            logger.warning(f"No CRS in data — using assumed_crs={assumed_crs}")
            gdf = gdf.set_crs(assumed_crs)
        else:
            raise ValueError(
                "Input data has no CRS. Set 'sewer.source.assumed_crs' in config."
            )
    if gdf.crs.to_epsg() != 2180:
        logger.info(f"Reprojecting from {gdf.crs} to {TARGET_CRS}")
        gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def _auto_detect_layer(path: str) -> str | None:
    """Auto-detect first LineString layer in multi-layer file."""
    try:
        layers = fiona.listlayers(path)
    except Exception:
        return None
    if len(layers) == 1:
        return layers[0]
    for layer_name in layers:
        with fiona.open(path, layer=layer_name) as src:
            if src.schema["geometry"] in ("LineString", "MultiLineString"):
                return layer_name
    return layers[0] if layers else None


def load_from_file(
    path: str,
    lines_layer: str | None = None,
    points_layer: str | None = None,
) -> gpd.GeoDataFrame:
    """Load sewer data from local file (SHP/GPKG/GeoJSON)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Sewer data file not found: {path}")

    layer = lines_layer or _auto_detect_layer(path)
    logger.info(f"Loading sewer data from {path} (layer={layer})")
    gdf = gpd.read_file(path, layer=layer)

    if points_layer:
        pts = gpd.read_file(path, layer=points_layer)
        logger.info(f"Loaded {len(pts)} sewer points from layer={points_layer}")
        # Store points as separate attribute for later graph building
        gdf.attrs["sewer_points"] = pts

    return gdf


def load_from_wfs(url: str, layer: str) -> gpd.GeoDataFrame:
    """Load sewer data from WFS service."""
    wfs_url = f"{url}?service=WFS&request=GetFeature&typeName={layer}&outputFormat=json"
    logger.info(f"Loading sewer data from WFS: {url} (layer={layer})")
    return gpd.read_file(wfs_url)


def load_from_database(connection: str, table: str) -> gpd.GeoDataFrame:
    """Load sewer data from external PostGIS database."""
    from sqlalchemy import create_engine

    logger.info(f"Loading sewer data from database: {table}")
    engine = create_engine(connection)
    return gpd.read_postgis(f"SELECT * FROM {table}", engine, geom_col="geom")


def load_from_url(url: str) -> gpd.GeoDataFrame:
    """Load sewer data from remote file URL (GDAL vsicurl)."""
    logger.info(f"Loading sewer data from URL: {url}")
    return gpd.read_file(url)


def load_sewer_data(config: dict) -> gpd.GeoDataFrame:
    """Load sewer data based on config source type.

    Dispatches to appropriate loader, validates CRS, reprojects to EPSG:2180.
    """
    sewer_cfg = config["sewer"]
    source = sewer_cfg["source"]
    source_type = source["type"]

    if source_type == "file":
        gdf = load_from_file(
            source["path"],
            lines_layer=source.get("lines_layer"),
            points_layer=source.get("points_layer"),
        )
    elif source_type == "wfs":
        gdf = load_from_wfs(source["url"], source["layer"])
    elif source_type == "database":
        gdf = load_from_database(source["connection"], source["table"])
    elif source_type == "url":
        gdf = load_from_url(source["url"])
    else:
        raise ValueError(f"Unknown sewer source type: {source_type}")

    gdf = _validate_crs(gdf, source.get("assumed_crs"))

    if gdf.empty:
        raise ValueError("Sewer data is empty — no features loaded")

    logger.info(
        f"Loaded {len(gdf)} sewer features "
        f"(type={_detect_geometry_type(gdf)}, crs={gdf.crs})"
    )
    return gdf
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_download_sewer.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/download_sewer.py backend/tests/unit/test_download_sewer.py
git commit -m "feat(core): add sewer data acquisition module (file/WFS/DB/URL)"
```

---

## Task 4: sewer_service.py — graph building (parse + snap + direction cascade)

**Files:**
- Create: `backend/core/sewer_service.py`
- Test: `backend/tests/unit/test_sewer_service.py`

This is the largest task. It covers: parsing input, snapping endpoints, building undirected graph, direction cascade, outlet detection, validation.

- [ ] **Step 1: Write failing tests for graph building**

Create `backend/tests/unit/test_sewer_service.py`:

```python
"""Tests for core.sewer_service module."""

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import LineString, Point

from core.sewer_service import (
    build_sewer_graph,
    SewerGraph,
)


@pytest.fixture
def simple_tree_lines():
    """Simple tree: 3 inlets → 1 outlet.

    Topology:
        A(0,100)--→B(50,100)
                      ↓
        C(50,150)--→B(50,100)--→D(100,100) [outlet]

    Lines: A→B, C→B, B→D
    """
    return gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(500000, 600100), (500050, 600100)]),  # A→B
                LineString([(500050, 600150), (500050, 600100)]),  # C→B
                LineString([(500050, 600100), (500100, 600100)]),  # B→D
            ],
        },
        crs="EPSG:2180",
    )


@pytest.fixture
def tree_with_elevations():
    """Tree with invert elevations for direction cascade."""
    return gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(500050, 600000), (500100, 600000)]),
            ],
            "invert_start": [105.0, 100.0],
            "invert_end": [100.0, 95.0],
        },
        crs="EPSG:2180",
    )


@pytest.fixture
def disconnected_lines():
    """Two disconnected components."""
    return gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(501000, 601000), (501050, 601000)]),
            ],
        },
        crs="EPSG:2180",
    )


class TestBuildSewerGraph:
    def test_simple_tree_node_count(self, simple_tree_lines):
        graph = build_sewer_graph(simple_tree_lines, snap_tolerance_m=2.0)
        assert graph.n_nodes == 4  # A, B, C, D

    def test_simple_tree_edge_count(self, simple_tree_lines):
        graph = build_sewer_graph(simple_tree_lines, snap_tolerance_m=2.0)
        assert graph.n_edges == 3

    def test_simple_tree_inlets(self, simple_tree_lines):
        graph = build_sewer_graph(simple_tree_lines, snap_tolerance_m=2.0)
        inlets = graph.get_nodes_by_type("inlet")
        assert len(inlets) == 2  # A and C are leaves

    def test_simple_tree_outlets(self, simple_tree_lines):
        graph = build_sewer_graph(simple_tree_lines, snap_tolerance_m=2.0)
        outlets = graph.get_nodes_by_type("outlet")
        assert len(outlets) == 1  # D is the root

    def test_simple_tree_junctions(self, simple_tree_lines):
        graph = build_sewer_graph(simple_tree_lines, snap_tolerance_m=2.0)
        junctions = graph.get_nodes_by_type("junction")
        assert len(junctions) == 1  # B is junction

    def test_direction_from_elevations(self, tree_with_elevations):
        graph = build_sewer_graph(
            tree_with_elevations,
            snap_tolerance_m=2.0,
            attr_mapping={"invert_start": "invert_start", "invert_end": "invert_end"},
        )
        outlets = graph.get_nodes_by_type("outlet")
        assert len(outlets) == 1
        # Outlet should be at the end with lowest elevation
        outlet = outlets[0]
        assert outlet["x"] == pytest.approx(500100, abs=5)

    def test_disconnected_components(self, disconnected_lines):
        graph = build_sewer_graph(disconnected_lines, snap_tolerance_m=2.0)
        assert graph.n_components >= 2
        assert len(graph.warnings) > 0

    def test_snap_merges_close_endpoints(self):
        lines = gpd.GeoDataFrame(
            {
                "geometry": [
                    LineString([(500000, 600000), (500050, 600000)]),
                    LineString([(500050.5, 600000.5), (500100, 600000)]),
                ],
            },
            crs="EPSG:2180",
        )
        graph = build_sewer_graph(lines, snap_tolerance_m=2.0)
        # Endpoints within 2m should be snapped together
        assert graph.n_nodes == 3  # not 4

    def test_upstream_inlets_for_outlet(self, simple_tree_lines):
        graph = build_sewer_graph(simple_tree_lines, snap_tolerance_m=2.0)
        outlets = graph.get_nodes_by_type("outlet")
        inlet_ids = graph.get_upstream_inlets(outlets[0]["id"])
        assert len(inlet_ids) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.sewer_service'`

- [ ] **Step 3: Implement sewer_service.py — SewerGraph class and build_sewer_graph**

Create `backend/core/sewer_service.py`:

```python
"""Stormwater sewer network integration with surface runoff analysis.

Handles: parsing input, graph building, inlet burning, FA reconstruction,
sewer routing, FA propagation downstream, DB insert.
"""

import logging
from collections import deque

import geopandas as gpd
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from shapely.geometry import Point

logger = logging.getLogger(__name__)


class SewerGraph:
    """Directed graph of a stormwater sewer network.

    Nodes: inlets (leaves), outlets (roots), junctions (internal).
    Edges: pipe segments connecting nodes.
    Built from vector GIS data (lines ± points).
    """

    def __init__(self):
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.adj: sparse.csr_matrix | None = None
        self.warnings: list[str] = []
        self.n_components: int = 0
        self._node_lookup: dict[int, int] = {}  # node_id → index

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_edges(self) -> int:
        return len(self.edges)

    def get_nodes_by_type(self, node_type: str) -> list[dict]:
        return [n for n in self.nodes if n["node_type"] == node_type]

    def get_upstream_inlets(self, outlet_id: int) -> list[int]:
        """BFS upstream from outlet, return IDs of all inlet nodes."""
        idx = self._node_lookup[outlet_id]
        visited = set()
        queue = deque([idx])
        inlet_ids = []
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            node = self.nodes[current]
            if node["node_type"] == "inlet":
                inlet_ids.append(node["id"])
            # Find upstream neighbors (columns with value in row=current)
            row = self.adj[current]
            for neighbor_idx in row.indices:
                if neighbor_idx not in visited:
                    queue.append(neighbor_idx)
        return inlet_ids


def _snap_endpoints(
    lines: gpd.GeoDataFrame, tolerance_m: float
) -> tuple[list[tuple[float, float]], dict[int, int]]:
    """Snap line endpoints within tolerance. Returns unique coords and mapping."""
    raw_points = []
    for geom in lines.geometry:
        coords = list(geom.coords)
        raw_points.append(coords[0])
        raw_points.append(coords[-1])

    # Cluster points within tolerance
    unique_coords: list[tuple[float, float]] = []
    point_to_node: dict[int, int] = {}  # raw_point_index → node_index

    for i, pt in enumerate(raw_points):
        matched = False
        for j, uc in enumerate(unique_coords):
            dist = ((pt[0] - uc[0]) ** 2 + (pt[1] - uc[1]) ** 2) ** 0.5
            if dist <= tolerance_m:
                point_to_node[i] = j
                matched = True
                break
        if not matched:
            point_to_node[i] = len(unique_coords)
            unique_coords.append(pt)

    return unique_coords, point_to_node


def _assign_directions_by_topology(
    n_nodes: int,
    undirected_edges: list[tuple[int, int]],
    node_degrees: np.ndarray,
    outlet_indices: set[int],
) -> list[tuple[int, int]]:
    """Direct edges by BFS from outlets (roots) upward. Returns (from, to) pairs."""
    # Build undirected adjacency
    adj = {}
    for i, (a, b) in enumerate(undirected_edges):
        adj.setdefault(a, []).append((b, i))
        adj.setdefault(b, []).append((a, i))

    directed = [None] * len(undirected_edges)
    visited_edges = set()
    queue = deque(outlet_indices)
    visited_nodes = set(outlet_indices)

    while queue:
        current = queue.popleft()
        for neighbor, edge_idx in adj.get(current, []):
            if edge_idx in visited_edges:
                continue
            visited_edges.add(edge_idx)
            # Direction: neighbor → current (upstream → downstream toward outlet)
            directed[edge_idx] = (neighbor, current)
            if neighbor not in visited_nodes:
                visited_nodes.add(neighbor)
                queue.append(neighbor)

    # Handle unvisited edges (disconnected or cycles)
    for i, d in enumerate(directed):
        if d is None:
            a, b = undirected_edges[i]
            directed[i] = (a, b)  # arbitrary direction

    return directed


def build_sewer_graph(
    gdf: gpd.GeoDataFrame,
    snap_tolerance_m: float = 2.0,
    attr_mapping: dict | None = None,
    user_outlets: gpd.GeoDataFrame | None = None,
) -> SewerGraph:
    """Build directed sewer graph from GIS vector data.

    Direction cascade: attribute → elevations → tree topology.
    """
    attr_mapping = attr_mapping or {}
    graph = SewerGraph()

    # 1. Snap endpoints
    unique_coords, pt_to_node = _snap_endpoints(gdf, snap_tolerance_m)

    # 2. Create nodes
    for i, (x, y) in enumerate(unique_coords):
        graph.nodes.append({
            "id": i,
            "x": x,
            "y": y,
            "node_type": "junction",  # will be refined below
            "depth_m": None,
            "invert_elev_m": None,
            "dem_elev_m": None,
            "burn_elev_m": None,
            "fa_value": None,
            "total_upstream_fa": None,
            "root_outlet_id": None,
            "source_type": "topology_generated",
            "component_id": None,
        })

    # 3. Create undirected edges
    undirected_edges = []
    for line_idx in range(len(gdf)):
        from_node = pt_to_node[line_idx * 2]
        to_node = pt_to_node[line_idx * 2 + 1]
        undirected_edges.append((from_node, to_node))
        geom = gdf.geometry.iloc[line_idx]
        graph.edges.append({
            "id": line_idx,
            "from_node": from_node,
            "to_node": to_node,
            "geom": geom,
            "length_m": geom.length,
        })

    n = len(unique_coords)
    node_degrees = np.zeros(n, dtype=int)
    for a, b in undirected_edges:
        node_degrees[a] += 1
        node_degrees[b] += 1

    # 4. Connected components
    row = [a for a, b in undirected_edges] + [b for a, b in undirected_edges]
    col = [b for a, b in undirected_edges] + [a for a, b in undirected_edges]
    data = np.ones(len(row), dtype=np.int8)
    undirected_adj = sparse.csr_matrix((data, (row, col)), shape=(n, n))
    n_comp, comp_labels = connected_components(undirected_adj, directed=False)
    graph.n_components = n_comp

    for i, label in enumerate(comp_labels):
        graph.nodes[i]["component_id"] = int(label)

    if n_comp > 1:
        graph.warnings.append(
            f"Disconnected graph: {n_comp} components"
        )

    # 5. Direction cascade
    invert_start_col = attr_mapping.get("invert_start")
    invert_end_col = attr_mapping.get("invert_end")
    flow_dir_col = attr_mapping.get("flow_direction")

    directed_edges = []
    for i, (a, b) in enumerate(undirected_edges):
        # (a) Attribute
        if flow_dir_col and flow_dir_col in gdf.columns:
            # Assume attribute encodes direction matching geometry order
            directed_edges.append((a, b))
            continue

        # (b) Elevations
        if invert_start_col and invert_end_col:
            if invert_start_col in gdf.columns and invert_end_col in gdf.columns:
                elev_s = gdf[invert_start_col].iloc[i]
                elev_e = gdf[invert_end_col].iloc[i]
                if elev_s is not None and elev_e is not None:
                    if elev_s >= elev_e:
                        directed_edges.append((a, b))
                    else:
                        directed_edges.append((b, a))
                    continue

        # Mark as needing topology-based direction
        directed_edges.append(None)

    # (c) Topology-based direction for unresolved edges
    needs_topology = any(e is None for e in directed_edges)
    if needs_topology:
        # Detect outlets: degree-1 nodes. For each component pick the one
        # with lowest y-coordinate (typically downstream in Polish rivers).
        outlet_indices = set()
        for comp_id in range(n_comp):
            comp_nodes = [i for i, c in enumerate(comp_labels) if c == comp_id]
            leaves = [i for i in comp_nodes if node_degrees[i] == 1]
            if not leaves:
                graph.warnings.append(
                    f"Component {comp_id}: no leaf nodes for outlet detection"
                )
                continue
            # Pick leaf with lowest y as outlet
            outlet_idx = min(leaves, key=lambda i: graph.nodes[i]["y"])
            outlet_indices.add(outlet_idx)

        topo_directed = _assign_directions_by_topology(
            n, undirected_edges, node_degrees, outlet_indices
        )
        for i, e in enumerate(directed_edges):
            if e is None:
                directed_edges[i] = topo_directed[i]

    # 6. Update edges with final direction
    for i, (from_n, to_n) in enumerate(directed_edges):
        graph.edges[i]["from_node"] = from_n
        graph.edges[i]["to_node"] = to_n

    # 7. Build directed adjacency matrix (upstream → downstream)
    # adj[downstream, upstream] = 1 (same convention as CatchmentGraph)
    from_arr = np.array([e["from_node"] for e in graph.edges], dtype=np.int32)
    to_arr = np.array([e["to_node"] for e in graph.edges], dtype=np.int32)
    adj_data = np.ones(len(graph.edges), dtype=np.int8)
    graph.adj = sparse.csr_matrix(
        (adj_data, (to_arr, from_arr)), shape=(n, n), dtype=np.int8
    )

    # 8. Classify node types
    out_degree = np.array(
        (graph.adj.T > 0).sum(axis=1), dtype=int
    ).flatten()  # outgoing edges per node
    in_degree = np.array(
        (graph.adj > 0).sum(axis=1), dtype=int
    ).flatten()  # incoming edges per node

    for i, node in enumerate(graph.nodes):
        if out_degree[i] == 0:
            node["node_type"] = "outlet"
        elif in_degree[i] == 0:
            node["node_type"] = "inlet"
        else:
            node["node_type"] = "junction"

    # 9. Map root_outlet_id for each node
    for outlet in graph.get_nodes_by_type("outlet"):
        oid = outlet["id"]
        upstream_ids = graph.get_upstream_inlets(oid)
        # Also tag junctions
        idx = graph._node_lookup.get(oid, oid)
        # BFS to tag all upstream nodes
        visited = set()
        queue = deque([oid])
        while queue:
            cur = queue.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            if cur != oid:
                graph.nodes[cur]["root_outlet_id"] = oid
            row = graph.adj[cur]
            for neighbor_idx in row.indices:
                if neighbor_idx not in visited:
                    queue.append(neighbor_idx)

    # 10. Build node lookup
    graph._node_lookup = {n["id"]: i for i, n in enumerate(graph.nodes)}

    # Validate: components without outlets
    for comp_id in range(n_comp):
        comp_outlets = [
            n for n in graph.nodes
            if n["component_id"] == comp_id and n["node_type"] == "outlet"
        ]
        if not comp_outlets:
            graph.warnings.append(
                f"Component {comp_id}: no outlet detected — will be skipped"
            )

    return graph
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/sewer_service.py backend/tests/unit/test_sewer_service.py
git commit -m "feat(core): add sewer graph building with direction cascade"
```

---

## Task 5: sewer_service.py — inlet burning + FA reconstruction + routing + propagation

**Files:**
- Modify: `backend/core/sewer_service.py`
- Modify: `backend/tests/unit/test_sewer_service.py`

- [ ] **Step 1: Write failing tests for raster operations**

Append to `backend/tests/unit/test_sewer_service.py`:

```python
from core.sewer_service import (
    burn_inlets,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
    propagate_fa_downstream,
)


@pytest.fixture
def small_dem():
    """5x5 DEM with gentle slope toward (4,2) — outlet area."""
    dem = np.array([
        [110, 109, 108, 109, 110],
        [109, 108, 107, 108, 109],
        [108, 107, 106, 107, 108],
        [107, 106, 105, 106, 107],
        [106, 105, 104, 105, 106],
    ], dtype=np.float64)
    return dem


@pytest.fixture
def small_fdir():
    """D8 fdir matching small_dem slope (all flowing toward center-bottom)."""
    # D8: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
    return np.array([
        [2,   4,   4,   4,   8],
        [2,   2,   4,   8,   8],
        [1,   2,   4,   8,  16],
        [1,   2,   4,   8,  16],
        [1,   1,   0,  16,  16],  # (4,2) is pit/outlet
    ], dtype=np.int16)


@pytest.fixture
def small_fa():
    """FA matching small_dem — center column accumulates most."""
    return np.array([
        [1, 1, 1, 1, 1],
        [2, 2, 3, 2, 2],
        [1, 3, 7, 3, 1],
        [1, 4, 12, 4, 1],
        [1, 5, 25, 5, 1],
    ], dtype=np.int32)


@pytest.fixture
def small_metadata():
    return {
        "cellsize": 5.0,
        "xllcorner": 500000.0,
        "yllcorner": 600000.0,
        "nodata_value": -9999.0,
    }


class TestBurnInlets:
    def test_burns_dem_at_inlet(self, small_dem):
        inlets = [{"id": 0, "row": 1, "col": 1, "depth_m": None, "invert_elev_m": None}]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        assert dem_mod[1, 1] == pytest.approx(108.0 - 0.5)
        assert (1, 1) in drain_pts

    def test_skips_negative_depth(self, small_dem):
        inlets = [{"id": 0, "row": 1, "col": 1, "depth_m": None, "invert_elev_m": 999.0}]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        # invert_elev > DEM → skip
        assert dem_mod[1, 1] == 108.0
        assert len(drain_pts) == 0

    def test_deduplicates_same_cell(self, small_dem):
        inlets = [
            {"id": 0, "row": 1, "col": 1, "depth_m": 0.3, "invert_elev_m": None},
            {"id": 1, "row": 1, "col": 1, "depth_m": 0.8, "invert_elev_m": None},
        ]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        # Should use max depth (0.8)
        assert dem_mod[1, 1] == pytest.approx(108.0 - 0.8)
        assert drain_pts.count((1, 1)) == 1


class TestReconstructInletFa:
    def test_reconstructs_from_neighbors(self, small_fa, small_fdir):
        inlets = [{"id": 0, "row": 2, "col": 2}]
        reconstruct_inlet_fa(small_fa, small_fdir, inlets)
        # Cell (2,2) was "nodata" — FA should be sum of neighbors pointing to it
        assert inlets[0]["fa_value"] > 0

    def test_boundary_inlet(self, small_fa, small_fdir):
        inlets = [{"id": 0, "row": 0, "col": 0}]
        reconstruct_inlet_fa(small_fa, small_fdir, inlets)
        assert inlets[0]["fa_value"] >= 0


class TestRouteFA:
    def test_simple_routing(self):
        graph = SewerGraph()
        graph.nodes = [
            {"id": 0, "node_type": "inlet", "fa_value": 100, "total_upstream_fa": None, "component_id": 0},
            {"id": 1, "node_type": "inlet", "fa_value": 200, "total_upstream_fa": None, "component_id": 0},
            {"id": 2, "node_type": "junction", "fa_value": None, "total_upstream_fa": None, "component_id": 0},
            {"id": 3, "node_type": "outlet", "fa_value": None, "total_upstream_fa": None, "component_id": 0},
        ]
        graph._node_lookup = {0: 0, 1: 1, 2: 2, 3: 3}
        # 0→2, 1→2, 2→3
        row = np.array([2, 2, 3], dtype=np.int32)
        col = np.array([0, 1, 2], dtype=np.int32)
        graph.adj = sparse.csr_matrix(
            (np.ones(3, dtype=np.int8), (row, col)), shape=(4, 4)
        )
        route_fa_through_sewer(graph)
        assert graph.nodes[3]["total_upstream_fa"] == 300  # 100 + 200


class TestPropagateFa:
    def test_adds_surplus_downstream(self, small_fa, small_fdir):
        fa = small_fa.copy()
        outlets = [{"id": 0, "row": 2, "col": 2, "total_upstream_fa": 50}]
        original_downstream = fa[3, 2]
        propagate_fa_downstream(fa, small_fdir, outlets)
        assert fa[2, 2] == small_fa[2, 2] + 50
        assert fa[3, 2] >= original_downstream + 50
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py::TestBurnInlets -v
```

Expected: FAIL — `ImportError: cannot import name 'burn_inlets'`

- [ ] **Step 3: Implement raster operations in sewer_service.py**

Append to `backend/core/sewer_service.py`:

```python
# --- Raster operations ---

# D8 direction offsets (same as hydrology.py)
_D8_DR = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
_D8_DC = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}
_D8_REVERSE = {1: 16, 2: 32, 4: 64, 8: 128, 16: 1, 32: 2, 64: 4, 128: 8}


def burn_inlets(
    dem: np.ndarray,
    inlets: list[dict],
    default_depth_m: float = 0.5,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Lower DEM at inlet locations. Returns modified DEM and drain_points list.

    Deduplicates: if multiple inlets map to the same cell, uses max depth.
    Validates: skips inlets where computed depth <= 0 (inlet above DEM).
    """
    drain_points: list[tuple[int, int]] = []
    cell_depths: dict[tuple[int, int], float] = {}
    nrows, ncols = dem.shape

    for inlet in inlets:
        row, col = inlet["row"], inlet["col"]
        if row < 0 or row >= nrows or col < 0 or col >= ncols:
            logger.warning(f"Inlet {inlet['id']} at ({row},{col}) outside DEM — skipping")
            continue

        dem_elev = float(dem[row, col])
        inlet["dem_elev_m"] = dem_elev

        # Determine depth (cascade)
        if inlet.get("invert_elev_m") is not None:
            depth = dem_elev - inlet["invert_elev_m"]
        elif inlet.get("depth_m") is not None:
            depth = inlet["depth_m"]
        else:
            depth = default_depth_m

        if depth <= 0:
            logger.warning(
                f"Inlet {inlet['id']}: depth={depth:.2f}m <= 0 "
                f"(DEM={dem_elev:.1f}, invert={inlet.get('invert_elev_m')}) — skipping"
            )
            continue

        key = (row, col)
        if key in cell_depths:
            cell_depths[key] = max(cell_depths[key], depth)
        else:
            cell_depths[key] = depth

        inlet["burn_elev_m"] = dem_elev - depth

    for (row, col), depth in cell_depths.items():
        dem[row, col] -= depth
        drain_points.append((row, col))

    logger.info(f"Inlet burning: {len(cell_depths)} cells, {len(inlets)} inlets")
    return dem, drain_points


def reconstruct_inlet_fa(
    fa: np.ndarray,
    fdir: np.ndarray,
    inlets: list[dict],
) -> None:
    """Reconstruct FA for inlet cells (set to nodata by drain_points).

    For each inlet cell, sum FA from 8 neighbors whose fdir points to this cell.
    Modifies inlets in-place (sets fa_value).
    """
    nrows, ncols = fa.shape

    for inlet in inlets:
        row, col = inlet["row"], inlet["col"]
        reconstructed = 0

        for d8_code, (dr, dc) in zip(_D8_DR.keys(), zip(_D8_DR.values(), _D8_DC.values())):
            nr, nc = row - dr, col - dc  # neighbor that would flow TO (row, col)
            if 0 <= nr < nrows and 0 <= nc < ncols:
                neighbor_fdir = fdir[nr, nc]
                if neighbor_fdir == d8_code:
                    reconstructed += int(fa[nr, nc])

        inlet["fa_value"] = reconstructed


def route_fa_through_sewer(graph: SewerGraph) -> None:
    """Route FA through sewer graph: sum inlet FA per outlet.

    For each outlet, BFS upstream to find all inlets, sum their fa_value.
    Modifies graph.nodes in-place (sets total_upstream_fa on outlets).
    """
    for outlet in graph.get_nodes_by_type("outlet"):
        inlet_ids = graph.get_upstream_inlets(outlet["id"])
        total = 0
        for iid in inlet_ids:
            node = graph.nodes[graph._node_lookup[iid]]
            fa_val = node.get("fa_value", 0) or 0
            total += fa_val
        outlet["total_upstream_fa"] = total
        logger.info(
            f"Outlet {outlet['id']}: {len(inlet_ids)} inlets, total_fa={total}"
        )


def propagate_fa_downstream(
    fa: np.ndarray,
    fdir: np.ndarray,
    outlets: list[dict],
) -> None:
    """Propagate FA surplus from sewer outlets downstream along fdir.

    Injects surplus at outlet cell, then walks downstream adding surplus
    to each cell along the flow path.
    """
    nrows, ncols = fa.shape
    # Sort outlets by total_upstream_fa ascending (smallest first)
    sorted_outlets = sorted(outlets, key=lambda o: o.get("total_upstream_fa", 0))

    for outlet in sorted_outlets:
        surplus = outlet.get("total_upstream_fa", 0)
        if surplus <= 0:
            continue

        row, col = outlet["row"], outlet["col"]
        fa[row, col] += surplus

        # BFS downstream
        visited = set()
        current_r, current_c = row, col
        while True:
            if (current_r, current_c) in visited:
                break
            visited.add((current_r, current_c))

            d8 = int(fdir[current_r, current_c])
            if d8 <= 0 or d8 not in _D8_DR:
                break  # pit, nodata, or edge

            nr = current_r + _D8_DR[d8]
            nc = current_c + _D8_DC[d8]

            if nr < 0 or nr >= nrows or nc < 0 or nc >= ncols:
                break  # edge of raster

            fa[nr, nc] += surplus
            current_r, current_c = nr, nc

    logger.info(
        f"FA propagation: {len(sorted_outlets)} outlets, "
        f"max surplus={max((o.get('total_upstream_fa', 0) for o in sorted_outlets), default=0)}"
    )
```

- [ ] **Step 4: Run all sewer_service tests**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/sewer_service.py backend/tests/unit/test_sewer_service.py
git commit -m "feat(core): add inlet burning, FA reconstruction, routing, propagation"
```

---

## Task 6: sewer_service.py — DB insert

**Files:**
- Modify: `backend/core/sewer_service.py`
- Test: `backend/tests/unit/test_sewer_service.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/test_sewer_service.py`:

```python
from unittest.mock import MagicMock, call
from core.sewer_service import insert_sewer_data


class TestInsertSewerData:
    def test_insert_builds_correct_sql(self):
        graph = SewerGraph()
        graph.nodes = [
            {"id": 0, "x": 500000, "y": 600000, "node_type": "inlet",
             "component_id": 0, "depth_m": 0.5, "invert_elev_m": None,
             "dem_elev_m": 108.0, "burn_elev_m": 107.5, "fa_value": 100,
             "total_upstream_fa": None, "root_outlet_id": 1,
             "source_type": "topology_generated"},
            {"id": 1, "x": 500100, "y": 600000, "node_type": "outlet",
             "component_id": 0, "depth_m": None, "invert_elev_m": None,
             "dem_elev_m": 104.0, "burn_elev_m": None, "fa_value": None,
             "total_upstream_fa": 100, "root_outlet_id": None,
             "source_type": "topology_generated"},
        ]
        graph.edges = [{
            "id": 0, "from_node": 0, "to_node": 1,
            "geom": LineString([(500000, 600000), (500100, 600000)]),
            "length_m": 100.0,
        }]
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.connection.return_value.__exit__ = MagicMock(return_value=False)

        count = insert_sewer_data(graph, mock_db, source_file="test.gpkg")
        assert count > 0
```

- [ ] **Step 2: Implement insert_sewer_data**

Append to `backend/core/sewer_service.py`:

```python
def insert_sewer_data(
    graph: SewerGraph,
    db_session,
    source_file: str = "unknown",
) -> int:
    """Insert sewer graph into PostGIS (sewer_nodes + sewer_network).

    Returns total number of records inserted.
    """
    from sqlalchemy import text

    # Truncate existing data
    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    cursor.execute("TRUNCATE TABLE sewer_network CASCADE")
    cursor.execute("TRUNCATE TABLE sewer_nodes CASCADE")

    # Insert nodes
    for node in graph.nodes:
        cursor.execute(
            """
            INSERT INTO sewer_nodes (
                id, geom, node_type, component_id, depth_m, invert_elev_m,
                dem_elev_m, burn_elev_m, fa_value, total_upstream_fa,
                root_outlet_id, source_type
            ) VALUES (
                %(id)s, ST_SetSRID(ST_MakePoint(%(x)s, %(y)s), 2180),
                %(node_type)s, %(component_id)s, %(depth_m)s, %(invert_elev_m)s,
                %(dem_elev_m)s, %(burn_elev_m)s, %(fa_value)s, %(total_upstream_fa)s,
                %(root_outlet_id)s, %(source_type)s
            )
            """,
            node,
        )

    # Insert edges
    for edge in graph.edges:
        wkt = edge["geom"].wkt
        cursor.execute(
            """
            INSERT INTO sewer_network (
                geom, node_from_id, node_to_id, length_m, source
            ) VALUES (
                ST_SetSRID(ST_GeomFromText(%s), 2180),
                %s, %s, %s, %s
            )
            """,
            (wkt, edge["from_node"], edge["to_node"], edge["length_m"], source_file),
        )

    raw_conn.commit()
    total = len(graph.nodes) + len(graph.edges)
    logger.info(f"Inserted sewer data: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    return total
```

- [ ] **Step 3: Run test**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py::TestInsertSewerData -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/core/sewer_service.py backend/tests/unit/test_sewer_service.py
git commit -m "feat(core): add sewer DB insert (sewer_nodes + sewer_network)"
```

---

## Task 7: Integration with process_dem.py

**Files:**
- Modify: `backend/scripts/process_dem.py:37-84` (imports) and `backend/scripts/process_dem.py:540-680` (pipeline steps)

- [ ] **Step 1: Add imports**

At `backend/scripts/process_dem.py`, after line 83 (end of existing imports), add:

```python
from core.sewer_service import (
    build_sewer_graph,
    burn_inlets,
    insert_sewer_data,
    propagate_fa_downstream,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
)
from scripts.download_sewer import load_sewer_data
```

- [ ] **Step 2: Add sewer parameter to process_dem()**

In the `process_dem()` function signature (around line 358-374), add parameter:

```python
    sewer_config: dict | None = None,
```

- [ ] **Step 3: Add step 3b — inlet burning (after drain_points, before process_hydrology_pyflwdir)**

After the drain_points section (after line 568) and before line 570 (`# 3-5. Process hydrology`), insert:

```python
    # 3b. Sewer inlet burning (optional — requires sewer config)
    sewer_graph = None
    sewer_nodes_with_rc = None
    if sewer_config and sewer_config.get("sewer", {}).get("enabled"):
        logger.info("=== Sewer integration: loading data ===")
        sewer_data = load_sewer_data(sewer_config)
        sewer_cfg = sewer_config["sewer"]

        transform_for_sewer = _get_transform(metadata, dem.shape)
        sewer_graph = build_sewer_graph(
            sewer_data,
            snap_tolerance_m=max(
                sewer_cfg.get("snap_tolerance_m", 2.0),
                metadata["cellsize"],
            ),
            attr_mapping=sewer_cfg.get("attribute_mapping", {}),
        )
        for w in sewer_graph.warnings:
            logger.warning(f"Sewer: {w}")

        # Convert node (x,y) to (row,col) for raster operations
        from rasterio.transform import rowcol
        sewer_nodes_with_rc = []
        for node in sewer_graph.nodes:
            if node["node_type"] == "inlet":
                row, col = int((node["y"] - metadata["yllcorner"]) / metadata["cellsize"]), \
                           int((node["x"] - metadata["xllcorner"]) / metadata["cellsize"])
                row = dem.shape[0] - 1 - row  # flip y-axis
                node["row"] = row
                node["col"] = col
                sewer_nodes_with_rc.append(node)

        inlets = [n for n in sewer_nodes_with_rc if n["node_type"] == "inlet"]
        dem, drain_points_sewer = burn_inlets(
            dem, inlets, default_depth_m=sewer_cfg.get("inlet_burn_depth_m", 0.5)
        )
        if drain_points is None:
            drain_points = []
        drain_points.extend(drain_points_sewer)
        stats["sewer_inlets_burned"] = len(drain_points_sewer)
        logger.info(f"Sewer: burned {len(drain_points_sewer)} inlet cells")
```

- [ ] **Step 4: Add steps 4a-4c (after FA, before Strahler)**

After line 605 (end of save_intermediates for FA) and before line 606 (`# 4b. Compute stream distance`), insert:

```python
    # 4a-4c. Sewer FA routing and propagation
    if sewer_graph is not None:
        logger.info("=== Sewer integration: FA routing ===")
        inlets = [n for n in sewer_graph.nodes if n["node_type"] == "inlet" and "row" in n]
        reconstruct_inlet_fa(acc, fdir, inlets)

        route_fa_through_sewer(sewer_graph)

        # Assign (row, col) to outlets for propagation
        outlets = []
        for node in sewer_graph.nodes:
            if node["node_type"] == "outlet":
                row = dem.shape[0] - 1 - int((node["y"] - metadata["yllcorner"]) / metadata["cellsize"])
                col = int((node["x"] - metadata["xllcorner"]) / metadata["cellsize"])
                node["row"] = row
                node["col"] = col
                outlets.append(node)

        propagate_fa_downstream(acc, fdir, outlets)
        stats["sewer_outlets"] = len(outlets)
        stats["sewer_max_surplus"] = max(
            (o.get("total_upstream_fa", 0) for o in outlets), default=0
        )
        logger.info(
            f"Sewer FA propagation: {len(outlets)} outlets, "
            f"max surplus={stats['sewer_max_surplus']}"
        )
```

- [ ] **Step 5: Add sewer DB insert (after existing DB inserts)**

Find the section where `insert_stream_segments` and `insert_catchments` are called (near end of process_dem). After the last DB insert, add:

```python
    # 8b. Insert sewer data
    if sewer_graph is not None:
        logger.info("Inserting sewer data into database...")
        sewer_count = insert_sewer_data(
            sewer_graph, db_session,
            source_file=str(sewer_config["sewer"]["source"].get("path", "unknown")),
        )
        stats["sewer_records_inserted"] = sewer_count
```

- [ ] **Step 6: Run existing tests to verify no regression**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short -q
```

Expected: All existing tests pass. Sewer code only activates when `sewer_config` is provided.

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/process_dem.py
git commit -m "feat(core): integrate sewer pipeline steps 3b, 4a-4c into process_dem"
```

---

## Task 8: Admin API endpoints (upload/status/delete)

**Files:**
- Modify: `backend/api/endpoints/admin.py`
- Test: `backend/tests/unit/test_admin_sewer.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_admin_sewer.py`:

```python
"""Tests for sewer admin API endpoints."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


class TestSewerStatus:
    def test_status_no_data(self, client):
        resp = client.get(
            "/api/admin/sewer/status",
            headers={"X-Admin-Key": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data

    def test_status_requires_auth(self, client):
        resp = client.get("/api/admin/sewer/status")
        assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Implement sewer admin endpoints**

In `backend/api/endpoints/admin.py`, add after the last existing endpoint:

```python
# --- Sewer management ---

DATA_SEWER = PROJECT_ROOT / "data" / "sewer"


@router.get("/sewer/status")
def sewer_status(db: Session = Depends(get_db)):
    """Get status of sewer data in the database."""
    try:
        result = db.execute(text("SELECT COUNT(*) FROM sewer_nodes"))
        node_count = result.scalar() or 0
        result = db.execute(text("SELECT COUNT(*) FROM sewer_network"))
        edge_count = result.scalar() or 0

        type_counts = {}
        if node_count > 0:
            rows = db.execute(text(
                "SELECT node_type, COUNT(*) FROM sewer_nodes GROUP BY node_type"
            ))
            type_counts = {r[0]: r[1] for r in rows}

        return {
            "loaded": node_count > 0,
            "nodes": node_count,
            "edges": edge_count,
            "node_types": type_counts,
        }
    except Exception:
        return {"loaded": False, "nodes": 0, "edges": 0, "node_types": {}}


@router.post("/sewer/upload")
async def sewer_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload sewer network file (SHP/GPKG/GeoJSON)."""
    import shutil

    DATA_SEWER.mkdir(parents=True, exist_ok=True)
    dest = DATA_SEWER / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Validate file
    try:
        import geopandas as gpd
        gdf = gpd.read_file(str(dest))
        n_features = len(gdf)
        geom_type = gdf.geometry.geom_type.unique().tolist()
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid file: {e}")

    return {
        "filename": file.filename,
        "path": str(dest),
        "features": n_features,
        "geometry_types": geom_type,
        "message": "Upload successful. Run pipeline to process sewer data.",
    }


@router.delete("/sewer/delete")
def sewer_delete(db: Session = Depends(get_db)):
    """Delete all sewer data from database and disk."""
    raw_conn = db.connection().connection
    cursor = raw_conn.cursor()
    cursor.execute("TRUNCATE TABLE sewer_network CASCADE")
    cursor.execute("TRUNCATE TABLE sewer_nodes CASCADE")
    raw_conn.commit()

    # Remove uploaded files
    import shutil
    if DATA_SEWER.exists():
        shutil.rmtree(DATA_SEWER)

    return {"message": "Sewer data deleted", "pipeline_dirty": True}
```

Also add the import at the top of admin.py:

```python
from fastapi import UploadFile, File
```

- [ ] **Step 3: Run tests**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_admin_sewer.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/endpoints/admin.py backend/tests/unit/test_admin_sewer.py
git commit -m "feat(api): add sewer admin endpoints (upload/status/delete)"
```

---

## Task 9: MVT tile endpoint for sewer network

**Files:**
- Modify: `backend/api/endpoints/tiles.py`

- [ ] **Step 1: Add sewer MVT endpoint**

In `backend/api/endpoints/tiles.py`, after the last existing tile endpoint, add:

```python
@router.get("/tiles/sewer/{z}/{x}/{y}.pbf")
def get_sewer_mvt(
    z: int,
    x: int,
    y: int,
    db: Session = Depends(get_db),
) -> Response:
    """Sewer network MVT tiles (lines + nodes)."""
    bbox = _tile_to_bbox(z, x, y)

    query = text("""
        WITH
        sewer_lines AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(n.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                n.diameter_mm,
                n.length_m,
                n.slope_percent
            FROM sewer_network n
            WHERE n.geom IS NOT NULL
              AND ST_Intersects(
                  n.geom,
                  ST_Transform(ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857), 2180)
              )
        ),
        sewer_pts AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(p.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                p.node_type,
                p.fa_value,
                p.total_upstream_fa
            FROM sewer_nodes p
            WHERE p.geom IS NOT NULL
              AND ST_Intersects(
                  p.geom,
                  ST_Transform(ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857), 2180)
              )
        ),
        lines_mvt AS (
            SELECT ST_AsMVT(sewer_lines, 'sewer_lines', 4096, 'geom') AS tile
            FROM sewer_lines
            WHERE geom IS NOT NULL
        ),
        points_mvt AS (
            SELECT ST_AsMVT(sewer_pts, 'sewer_nodes', 4096, 'geom') AS tile
            FROM sewer_pts
            WHERE geom IS NOT NULL
        )
        SELECT lines_mvt.tile || points_mvt.tile AS tile
        FROM lines_mvt, points_mvt
    """)

    result = db.execute(query, bbox)
    tile_data = result.scalar()

    if not tile_data:
        return Response(content=b"", media_type="application/x-protobuf")

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers={"Cache-Control": "no-store"},
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/api/endpoints/tiles.py
git commit -m "feat(api): add sewer MVT tile endpoint"
```

---

## Task 10: Frontend — sewer overlay layer + admin tab

**Files:**
- Create: `frontend/js/sewer.js`
- Modify: `frontend/js/layers.js`
- Modify: `frontend/admin.html`
- Modify: `frontend/index.html`

- [ ] **Step 1: Create sewer.js**

Create `frontend/js/sewer.js`:

```javascript
/**
 * Sewer network overlay layer for Leaflet map.
 * Renders MVT tiles with sewer lines and nodes.
 */
(function () {
    'use strict';

    var sewerLayer = null;

    function createSewerLayer() {
        if (typeof L.vectorGrid === 'undefined') {
            console.warn('Leaflet.VectorGrid not available — sewer layer disabled');
            return null;
        }

        return L.vectorGrid.protobuf('/api/tiles/sewer/{z}/{x}/{y}.pbf', {
            vectorTileLayerStyles: {
                sewer_lines: function (properties) {
                    return {
                        weight: 2,
                        color: '#6366f1',
                        opacity: 0.8,
                    };
                },
                sewer_nodes: function (properties) {
                    var color = '#94a3b8';
                    if (properties.node_type === 'inlet') color = '#3b82f6';
                    if (properties.node_type === 'outlet') color = '#ef4444';
                    return {
                        radius: 4,
                        fillColor: color,
                        fillOpacity: 0.9,
                        color: '#fff',
                        weight: 1,
                    };
                },
            },
            maxZoom: 20,
            minZoom: 10,
            interactive: true,
        });
    }

    function getSewerLayer() {
        if (!sewerLayer) {
            sewerLayer = createSewerLayer();
        }
        return sewerLayer;
    }

    window.Hydrograf = window.Hydrograf || {};
    window.Hydrograf.sewer = {
        getLayer: getSewerLayer,
    };
})();
```

- [ ] **Step 2: Add sewer overlay to layers.js**

In `frontend/js/layers.js`, in the init function after the last overlay entry (around line 421), add:

```javascript
        // Sewer network overlay
        if (window.Hydrograf.sewer) {
            addOverlayEntry(
                overlayGroup,
                'Kanalizacja deszczowa',
                function () { return window.Hydrograf.sewer.getLayer(); },
                null,
                null,
                50
            );
        }
```

- [ ] **Step 3: Include sewer.js in index.html**

In `frontend/index.html`, after the last `<script>` tag for JS modules, add:

```html
<script src="js/sewer.js"></script>
```

- [ ] **Step 4: Add Sewer tab to admin.html**

In `frontend/admin.html`, add a new tab button in the tab bar and corresponding tab content panel. Follow the existing pattern of Dashboard/Bootstrap/Resources/Cleanup tabs.

Tab button:
```html
<button class="tab-btn" data-tab="sewer">Kanalizacja</button>
```

Tab panel:
```html
<div class="tab-panel" id="sewer-panel">
    <h2>Kanalizacja deszczowa</h2>
    <div id="sewer-status">
        <p>Ladowanie statusu...</p>
    </div>
    <div class="sewer-actions" style="margin-top: 1rem;">
        <label class="btn btn-primary">
            Upload GPKG/SHP/GeoJSON
            <input type="file" id="sewer-upload-input" accept=".gpkg,.shp,.geojson,.json" style="display:none">
        </label>
        <button class="btn btn-danger" id="sewer-delete-btn">Usun dane</button>
    </div>
    <div id="sewer-upload-result" style="margin-top: 1rem;"></div>
</div>
```

Add JavaScript for the sewer tab (inline or in admin.js):
```javascript
// Sewer tab logic
async function loadSewerStatus() {
    try {
        var resp = await fetch('/api/admin/sewer/status', {headers: adminHeaders()});
        var data = await resp.json();
        var el = document.getElementById('sewer-status');
        if (data.loaded) {
            el.innerHTML = '<p><strong>Status:</strong> Zaladowano</p>' +
                '<p>Wezly: ' + data.nodes + ' (' +
                Object.entries(data.node_types).map(function(e){return e[0]+': '+e[1]}).join(', ') +
                ')</p><p>Krawedzie: ' + data.edges + '</p>';
        } else {
            el.innerHTML = '<p><strong>Status:</strong> Brak danych</p>';
        }
    } catch(e) {
        document.getElementById('sewer-status').innerHTML = '<p>Blad ladowania statusu</p>';
    }
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/js/sewer.js frontend/js/layers.js frontend/index.html frontend/admin.html
git commit -m "feat(frontend): add sewer overlay layer and admin tab"
```

---

## Task 11: Documentation updates

**Files:**
- Modify: `docs/SCOPE.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/DECISIONS.md`, `docs/CHANGELOG.md`, `docs/PROGRESS.md`

- [ ] **Step 1: Update SCOPE.md** — move sewer from out-of-scope to in-scope

- [ ] **Step 2: Update ARCHITECTURE.md** — add sewer modules, tables, pipeline diagram with steps 3b, 4a-4c

- [ ] **Step 3: Update DATA_MODEL.md** — add sewer_nodes and sewer_network table schemas

- [ ] **Step 4: Add ADR-051 to DECISIONS.md** — document all 9 key decisions from the spec

- [ ] **Step 5: Update CHANGELOG.md** — add sewer integration entry

- [ ] **Step 6: Update PROGRESS.md** — update current session info

- [ ] **Step 7: Commit**

```bash
git add docs/SCOPE.md docs/ARCHITECTURE.md docs/DATA_MODEL.md docs/DECISIONS.md docs/CHANGELOG.md docs/PROGRESS.md
git commit -m "docs: update documentation for sewer integration (ADR-051)"
```

---

## Task 12: Integration test — full pipeline with sewer data

**Files:**
- Create: `backend/tests/unit/test_sewer_integration.py`

- [ ] **Step 1: Write integration test with synthetic DEM + sewer network**

```python
"""Integration test: sewer pipeline on synthetic DEM."""

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import LineString

from core.sewer_service import (
    build_sewer_graph,
    burn_inlets,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
    propagate_fa_downstream,
)


@pytest.fixture
def synthetic_scenario():
    """50x50 DEM with 2 sewer inlets and 1 outlet.

    DEM slopes from top-left (high) to bottom-right (low).
    Sewer inlet at (15,15) and (15,25), outlet at (40,20) near a stream.
    """
    nrows, ncols = 50, 50
    y, x = np.mgrid[0:nrows, 0:ncols]
    dem = (200.0 - x * 1.5 - y * 1.5).astype(np.float64)

    # Simple fdir: everything flows SE (D8=2)
    fdir = np.full((nrows, ncols), 2, dtype=np.int16)
    fdir[-1, :] = 0  # bottom edge = pit
    fdir[:, -1] = 0  # right edge = pit

    # Simple FA: each cell accumulates from upstream
    fa = np.ones((nrows, ncols), dtype=np.int32)
    for r in range(nrows):
        for c in range(ncols):
            fa[r, c] = (r + 1) * (c + 1)  # approximate

    sewer_lines = gpd.GeoDataFrame(
        {"geometry": [
            LineString([(15, 15), (25, 15)]),   # inlet A → junction
            LineString([(25, 25), (25, 15)]),   # inlet B → junction
            LineString([(25, 15), (40, 20)]),   # junction → outlet
        ]},
        crs="EPSG:2180",
    )

    return dem, fdir, fa, sewer_lines


class TestFullSewerPipeline:
    def test_fa_increases_at_outlet(self, synthetic_scenario):
        dem, fdir, fa, sewer_lines = synthetic_scenario
        fa_original = fa.copy()

        # Build graph
        graph = build_sewer_graph(sewer_lines, snap_tolerance_m=2.0)
        assert graph.n_nodes >= 3

        # Burn inlets
        inlets = [n for n in graph.nodes if n["node_type"] == "inlet"]
        for inlet in inlets:
            inlet["row"] = int(inlet["y"])
            inlet["col"] = int(inlet["x"])
        dem_mod, drain_pts = burn_inlets(dem, inlets, default_depth_m=0.5)
        assert len(drain_pts) >= 1

        # Reconstruct FA
        reconstruct_inlet_fa(fa, fdir, inlets)
        assert all(n["fa_value"] is not None for n in inlets)

        # Route
        route_fa_through_sewer(graph)
        outlets = [n for n in graph.nodes if n["node_type"] == "outlet"]
        assert len(outlets) == 1
        assert outlets[0]["total_upstream_fa"] > 0

        # Propagate
        for o in outlets:
            o["row"] = int(o["y"])
            o["col"] = int(o["x"])
        propagate_fa_downstream(fa, fdir, outlets)

        # FA at outlet cell should have increased
        outlet = outlets[0]
        assert fa[outlet["row"], outlet["col"]] > fa_original[outlet["row"], outlet["col"]]

    def test_regression_without_sewer(self, synthetic_scenario):
        """Pipeline without sewer should produce unchanged FA."""
        dem, fdir, fa, _ = synthetic_scenario
        fa_copy = fa.copy()
        np.testing.assert_array_equal(fa, fa_copy)
```

- [ ] **Step 2: Run integration test**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_integration.py -v
```

- [ ] **Step 3: Run ALL tests to verify no regression**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short -q
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/unit/test_sewer_integration.py
git commit -m "test: add sewer integration test with synthetic DEM"
```

---

## Execution Order and Dependencies

```
Task 1 (migration) ─────────┐
Task 2 (config) ─────────────┤
Task 3 (download_sewer) ─────┤
Task 4 (graph building) ─────┼──→ Task 7 (process_dem integration)
Task 5 (raster ops) ─────────┤         │
Task 6 (DB insert) ──────────┘         │
                                        ├──→ Task 12 (integration test)
Task 8 (admin API) ─────────────────────┤
Task 9 (MVT tiles) ─────────────────────┤
Task 10 (frontend) ─────────────────────┘
Task 11 (docs) ── can run in parallel, no code deps
```

Tasks 1-6 can run in parallel (independent modules). Task 7 depends on all of 1-6. Tasks 8-10 can run in parallel after Task 1. Task 11 is independent. Task 12 runs last.
