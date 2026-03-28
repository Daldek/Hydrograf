# Sewer Topology Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace heuristic sewer topology (snapping, direction cascade, auto-detect) with explicit user-defined topology (downstream_id or point+line layers) with strict validation.

**Architecture:** New `core/sewer_topology.py` module (parser + validator) sits between `download_sewer.py` (I/O) and `sewer_service.py` (graph + raster ops). Two-phase pipeline in `process_dem.py`: phase 1 = clean fdir for loop validation, phase 2 = burn + full hydrology.

**Tech Stack:** Python 3.12, geopandas, numpy, scipy.sparse, pyflwdir, fiona, shapely, FastAPI, PostgreSQL/PostGIS, Alembic

**Spec:** `docs/superpowers/specs/2026-03-27-sewer-topology-rebuild-design.md`

**Branch:** `fix/sewer-topology-rebuild`

**Test runner:** `cd backend && .venv/bin/python -m pytest`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/core/sewer_topology.py` | CREATE | ParsedTopology dataclass, parse_sewer_topology(), validate_against_fdir() |
| `backend/tests/unit/test_sewer_topology.py` | CREATE | Tests for parser (format A+B), validator (all rules), fdir loop detection |
| `backend/core/config.py` | MODIFY:185-217 | field_mapping, role_mapping, format in _DEFAULT_CONFIG |
| `backend/tests/unit/test_config_sewer.py` | MODIFY | Tests for new config sections, backward compat |
| `backend/migrations/versions/027_update_sewer_node_type_constraint.py` | CREATE | CHECK constraint: isolated→storage |
| `backend/scripts/download_sewer.py` | MODIFY | Return tuple (points, lines\|None), ZIP support, auto-detect format |
| `backend/tests/unit/test_download_sewer.py` | MODIFY | Tests for ZIP, auto-detect, tuple return |
| `backend/core/sewer_service.py` | MODIFY:22-546,713-766 | Remove snapping/cascade/auto-detect, new build_sewer_graph(ParsedTopology) |
| `backend/tests/unit/test_sewer_service.py` | MODIFY | Update fixtures and tests for new interface |
| `backend/scripts/process_dem.py` | MODIFY:581-710 | Two-phase pipeline, fdir loop validation |
| `backend/api/endpoints/admin.py` | MODIFY:734-872 | Upload auto-detect, config field_mapping/role_mapping |
| `frontend/js/admin/admin-sewer.js` | MODIFY | detected_format display, storage node color |

---

## Task 1: Config defaults — field_mapping, role_mapping, format

**Files:**
- Modify: `backend/core/config.py:185-217`
- Modify: `backend/tests/unit/test_config_sewer.py`

- [ ] **Step 1: Write failing tests for new config sections**

```python
# Append to backend/tests/unit/test_config_sewer.py

class TestSewerFieldMappingDefaults:
    def test_field_mapping_exists(self):
        from core.config import _DEFAULT_CONFIG
        assert "field_mapping" in _DEFAULT_CONFIG["sewer"]

    def test_field_mapping_has_node_id(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["node_id"] == "id"

    def test_field_mapping_has_node_role(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["node_role"] == "role"

    def test_field_mapping_has_downstream_id(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["downstream_id"] == "downstream_id"

    def test_field_mapping_has_edge_from_to(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["edge_from"] == "from_node"
        assert fm["edge_to"] == "to_node"

    def test_field_mapping_core_attrs_null(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["invert_elev"] is None
        assert fm["depth"] is None
        assert fm["diameter"] is None

    def test_field_mapping_extended_attrs_null(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        for key in ("rim_elevation", "max_depth", "ponded_area",
                     "outfall_type", "manning", "material",
                     "cross_section", "width", "height"):
            assert fm[key] is None, f"{key} should be None"


class TestSewerRoleMappingDefaults:
    def test_role_mapping_exists(self):
        from core.config import _DEFAULT_CONFIG
        assert "role_mapping" in _DEFAULT_CONFIG["sewer"]

    def test_role_mapping_four_roles(self):
        from core.config import _DEFAULT_CONFIG
        rm = _DEFAULT_CONFIG["sewer"]["role_mapping"]
        assert rm == {
            "inlet": "inlet",
            "outlet": "outlet",
            "junction": "junction",
            "storage": "storage",
        }


class TestSewerSourceFormat:
    def test_source_format_default_auto(self):
        from core.config import _DEFAULT_CONFIG
        assert _DEFAULT_CONFIG["sewer"]["source"]["format"] == "auto"


class TestSewerBackwardCompat:
    def test_attribute_mapping_still_present(self):
        """attribute_mapping kept for backward compat with old config.yaml files."""
        from core.config import _DEFAULT_CONFIG
        assert "attribute_mapping" in _DEFAULT_CONFIG["sewer"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_config_sewer.py -v --tb=short 2>&1 | tail -30`
Expected: FAIL — `field_mapping` not in config

- [ ] **Step 3: Update _DEFAULT_CONFIG in config.py**

Add `field_mapping`, `role_mapping`, and `format` to `_DEFAULT_CONFIG["sewer"]` in `backend/core/config.py` (around line 185-217). Keep existing `attribute_mapping` for backward compat.

New `source` section adds `"format": "auto"`.

New `field_mapping` section:
```python
"field_mapping": {
    "node_id": "id",
    "node_role": "role",
    "downstream_id": "downstream_id",
    "edge_from": "from_node",
    "edge_to": "to_node",
    "invert_elev": None,
    "depth": None,
    "diameter": None,
    "rim_elevation": None,
    "max_depth": None,
    "ponded_area": None,
    "outfall_type": None,
    "manning": None,
    "material": None,
    "cross_section": None,
    "width": None,
    "height": None,
},
"role_mapping": {
    "inlet": "inlet",
    "outlet": "outlet",
    "junction": "junction",
    "storage": "storage",
},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_config_sewer.py -v --tb=short 2>&1 | tail -30`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/config.py backend/tests/unit/test_config_sewer.py
git commit -m "feat(core): add field_mapping, role_mapping, format to sewer config defaults"
```

---

## Task 2: DB migration — node_type constraint (isolated → storage)

**Files:**
- Create: `backend/migrations/versions/027_update_sewer_node_type_constraint.py`

- [ ] **Step 1: Create migration file**

```python
"""Update sewer_nodes node_type constraint: replace 'isolated' with 'storage'.

Revision ID: 027
Revises: 026 (or current head — check with `alembic heads`)
"""

from alembic import op

revision = "027"
down_revision = None  # set to actual parent after checking alembic heads
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrate existing data first
    op.execute(
        "UPDATE sewer_nodes SET node_type = 'junction' "
        "WHERE node_type = 'isolated'"
    )
    # Drop old constraint and add new one
    op.execute("ALTER TABLE sewer_nodes DROP CONSTRAINT IF EXISTS chk_node_type")
    op.execute(
        "ALTER TABLE sewer_nodes ADD CONSTRAINT chk_node_type "
        "CHECK (node_type IN ('inlet', 'outlet', 'junction', 'storage'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sewer_nodes SET node_type = 'junction' "
        "WHERE node_type = 'storage'"
    )
    op.execute("ALTER TABLE sewer_nodes DROP CONSTRAINT IF EXISTS chk_node_type")
    op.execute(
        "ALTER TABLE sewer_nodes ADD CONSTRAINT chk_node_type "
        "CHECK (node_type IN ('inlet', 'outlet', 'junction', 'isolated'))"
    )
```

Note: Check actual Alembic head with `cd backend && .venv/bin/python -m alembic heads` and set `down_revision` accordingly. There may be a merge migration needed if 026 already exists on a different branch.

- [ ] **Step 2: Verify migration syntax**

Run: `cd backend && .venv/bin/python -m alembic heads` to check current head, then update `down_revision`.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/versions/027_update_sewer_node_type_constraint.py
git commit -m "feat(db): migration 027 — node_type constraint isolated→storage"
```

---

## Task 3: New module — sewer_topology.py (ParsedTopology + parse format A)

**Files:**
- Create: `backend/core/sewer_topology.py`
- Create: `backend/tests/unit/test_sewer_topology.py`

- [ ] **Step 1: Write failing tests for ParsedTopology and format A parsing**

```python
# backend/tests/unit/test_sewer_topology.py
"""Unit tests for core.sewer_topology module."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from core.sewer_topology import (
    ParsedTopology,
    TopologyValidationError,
    parse_sewer_topology,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_points_format_a():
    """Format A: 3 points with downstream_id (inlet→junction→outlet)."""
    return gpd.GeoDataFrame(
        {
            "id": ["n1", "n2", "n3"],
            "role": ["inlet", "junction", "outlet"],
            "downstream_id": ["n2", "n3", None],
            "geometry": [
                Point(500_000, 200_000),
                Point(500_100, 200_100),
                Point(500_200, 200_200),
            ],
        },
        crs="EPSG:2180",
    )


@pytest.fixture
def default_field_mapping():
    return {
        "node_id": "id",
        "node_role": "role",
        "downstream_id": "downstream_id",
        "edge_from": "from_node",
        "edge_to": "to_node",
        "invert_elev": None,
        "depth": None,
        "diameter": None,
    }


@pytest.fixture
def default_role_mapping():
    return {
        "inlet": "inlet",
        "outlet": "outlet",
        "junction": "junction",
        "storage": "storage",
    }


# ---------------------------------------------------------------------------
# Format A: points only
# ---------------------------------------------------------------------------

class TestParseFormatA:
    def test_basic_parse(self, simple_points_format_a, default_field_mapping,
                         default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        assert isinstance(topo, ParsedTopology)
        assert topo.source_format == "points_only"

    def test_node_count(self, simple_points_format_a, default_field_mapping,
                        default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        assert len(topo.nodes) == 3

    def test_edge_count_auto_generated(self, simple_points_format_a,
                                        default_field_mapping,
                                        default_role_mapping):
        """Format A auto-generates edges from downstream_id."""
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        # n1→n2, n2→n3 = 2 edges
        assert len(topo.edges) == 2

    def test_node_roles(self, simple_points_format_a, default_field_mapping,
                        default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        roles = {n["id"]: n["role"] for n in topo.nodes}
        assert roles == {"n1": "inlet", "n2": "junction", "n3": "outlet"}

    def test_edges_have_geometry(self, simple_points_format_a,
                                  default_field_mapping, default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        for edge in topo.edges:
            assert edge["geometry"] is not None
            assert edge["geometry"].geom_type == "LineString"

    def test_edge_direction(self, simple_points_format_a,
                            default_field_mapping, default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        from_to = [(e["from_id"], e["to_id"]) for e in topo.edges]
        assert ("n1", "n2") in from_to
        assert ("n2", "n3") in from_to


class TestParseFormatAWithRoleMapping:
    def test_custom_role_values(self, default_field_mapping):
        """User data has Polish role names."""
        gdf = gpd.GeoDataFrame(
            {
                "id": ["a", "b"],
                "role": ["wpust", "wylot"],
                "downstream_id": ["b", None],
                "geometry": [Point(500_000, 200_000), Point(500_100, 200_100)],
            },
            crs="EPSG:2180",
        )
        role_mapping = {
            "inlet": "wpust",
            "outlet": "wylot",
            "junction": "studzienka",
            "storage": "zbiornik",
        }
        topo = parse_sewer_topology(gdf, None, default_field_mapping, role_mapping)
        roles = {n["id"]: n["role"] for n in topo.nodes}
        assert roles == {"a": "inlet", "b": "outlet"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py -v --tb=short 2>&1 | tail -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sewer_topology'`

- [ ] **Step 3: Implement ParsedTopology and parse_sewer_topology (format A)**

```python
# backend/core/sewer_topology.py
"""Sewer topology parser and validator.

Parses user-provided sewer data (Format A: points with downstream_id,
Format B: points + lines) into a unified ParsedTopology structure.
Validates topology consistency with structured error reporting.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

logger = logging.getLogger(__name__)

VALID_ROLES = {"inlet", "outlet", "junction", "storage"}


@dataclass
class ParsedTopology:
    """Unified result of parsing both input formats."""

    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_format: str = "points_only"


class TopologyValidationError(Exception):
    """Raised when topology data fails validation."""

    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        messages = [e["message"] for e in errors]
        super().__init__(
            f"Topology validation failed ({len(errors)} errors):\n"
            + "\n".join(f"  - {m}" for m in messages)
        )


def _invert_role_mapping(role_mapping: dict) -> dict:
    """Invert {canonical: user_value} → {user_value: canonical}."""
    return {v: k for k, v in role_mapping.items()}


def _parse_nodes(
    points_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
    role_lookup: dict,
) -> list[dict]:
    """Extract nodes from points GeoDataFrame."""
    id_col = field_mapping["node_id"]
    role_col = field_mapping["node_role"]

    nodes = []
    for _, row in points_gdf.iterrows():
        geom = row.geometry
        raw_role = str(row[role_col]).strip()
        canonical_role = role_lookup.get(raw_role, raw_role)

        node = {
            "id": str(row[id_col]),
            "role": canonical_role,
            "x": geom.x,
            "y": geom.y,
        }

        # Core attributes
        for attr in ("invert_elev", "depth", "diameter"):
            col = field_mapping.get(attr)
            if col and col in points_gdf.columns:
                val = row[col]
                node[attr] = None if (val is None or val != val) else val

        # Extended attributes
        for attr in ("rim_elevation", "max_depth", "ponded_area",
                      "outfall_type", "manning", "material",
                      "cross_section", "width", "height"):
            col = field_mapping.get(attr)
            if col and col in points_gdf.columns:
                val = row[col]
                node[attr] = None if (val is None or val != val) else val

        nodes.append(node)

    return nodes


def _generate_edges_from_downstream(
    nodes: list[dict],
    points_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
) -> list[dict]:
    """Format A: generate LineString edges from downstream_id column."""
    ds_col = field_mapping["downstream_id"]
    id_col = field_mapping["node_id"]

    node_by_id = {n["id"]: n for n in nodes}
    edges = []

    for _, row in points_gdf.iterrows():
        from_id = str(row[id_col])
        ds_val = row.get(ds_col)
        if ds_val is None or (isinstance(ds_val, float) and ds_val != ds_val):
            continue  # outlet — no downstream
        to_id = str(ds_val)

        from_node = node_by_id[from_id]
        to_node = node_by_id[to_id]
        geom = LineString([(from_node["x"], from_node["y"]),
                           (to_node["x"], to_node["y"])])

        edges.append({
            "from_id": from_id,
            "to_id": to_id,
            "geometry": geom,
            "source": "auto_generated",
        })

    return edges


def parse_sewer_topology(
    points_gdf: gpd.GeoDataFrame,
    lines_gdf: gpd.GeoDataFrame | None,
    field_mapping: dict,
    role_mapping: dict,
) -> ParsedTopology:
    """Parse and validate sewer topology from user data.

    Format A (lines_gdf=None): points with downstream_id, auto-generate lines.
    Format B (lines_gdf given): points + lines with from_node/to_node.

    Raises TopologyValidationError with structured report on invalid data.
    """
    role_lookup = _invert_role_mapping(role_mapping)
    nodes = _parse_nodes(points_gdf, field_mapping, role_lookup)

    if lines_gdf is None:
        edges = _generate_edges_from_downstream(nodes, points_gdf, field_mapping)
        source_format = "points_only"
    else:
        edges = _parse_edges_from_lines(nodes, lines_gdf, field_mapping)
        source_format = "points_and_lines"

    errors = _validate_topology(nodes, edges)
    if errors:
        raise TopologyValidationError(errors)

    return ParsedTopology(
        nodes=nodes,
        edges=edges,
        source_format=source_format,
    )
```

Note: `_parse_edges_from_lines` and `_validate_topology` are stubs for now — implemented in Tasks 4 and 5.

Add minimal stubs to make format A tests pass:

```python
def _parse_edges_from_lines(
    nodes: list[dict],
    lines_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
) -> list[dict]:
    """Format B: parse edges from lines GeoDataFrame. (Implemented in Task 4.)"""
    raise NotImplementedError("Format B parsing — see Task 4")


def _validate_topology(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Validate topology consistency. Returns list of error dicts (empty=OK)."""
    # Minimal validation — full implementation in Task 5
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/sewer_topology.py backend/tests/unit/test_sewer_topology.py
git commit -m "feat(core): sewer_topology.py — ParsedTopology + format A parser"
```

---

## Task 4: sewer_topology.py — Format B parsing (points + lines)

**Files:**
- Modify: `backend/core/sewer_topology.py`
- Modify: `backend/tests/unit/test_sewer_topology.py`

- [ ] **Step 1: Write failing tests for format B**

Append to `test_sewer_topology.py`:

```python
from shapely.geometry import LineString as ShapelyLineString


@pytest.fixture
def points_and_lines_format_b():
    """Format B: separate point + line layers."""
    points = gpd.GeoDataFrame(
        {
            "id": ["n1", "n2", "n3"],
            "role": ["inlet", "junction", "outlet"],
            "geometry": [
                Point(500_000, 200_000),
                Point(500_100, 200_100),
                Point(500_200, 200_200),
            ],
        },
        crs="EPSG:2180",
    )
    lines = gpd.GeoDataFrame(
        {
            "from_node": ["n1", "n2"],
            "to_node": ["n2", "n3"],
            "diameter_mm": [300, 400],
            "geometry": [
                ShapelyLineString([(500_000, 200_000), (500_050, 200_050),
                                   (500_100, 200_100)]),
                ShapelyLineString([(500_100, 200_100), (500_150, 200_150),
                                   (500_200, 200_200)]),
            ],
        },
        crs="EPSG:2180",
    )
    return points, lines


class TestParseFormatB:
    def test_basic_parse(self, points_and_lines_format_b, default_field_mapping,
                         default_role_mapping):
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        assert isinstance(topo, ParsedTopology)
        assert topo.source_format == "points_and_lines"

    def test_node_count(self, points_and_lines_format_b, default_field_mapping,
                        default_role_mapping):
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        assert len(topo.nodes) == 3

    def test_edge_count(self, points_and_lines_format_b, default_field_mapping,
                        default_role_mapping):
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        assert len(topo.edges) == 2

    def test_edges_preserve_geometry(self, points_and_lines_format_b,
                                      default_field_mapping, default_role_mapping):
        """Format B edges keep original line geometry (not auto-generated straight)."""
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        # Original lines have 3 vertices each, auto-gen would have 2
        for edge in topo.edges:
            assert len(edge["geometry"].coords) == 3

    def test_edges_have_attributes(self, points_and_lines_format_b,
                                    default_field_mapping, default_role_mapping):
        default_field_mapping["diameter"] = "diameter_mm"
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        diameters = [e.get("diameter") for e in topo.edges]
        assert diameters == [300, 400]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py::TestParseFormatB -v --tb=short 2>&1 | tail -20`
Expected: FAIL — `NotImplementedError: Format B parsing`

- [ ] **Step 3: Implement _parse_edges_from_lines**

Replace the stub in `sewer_topology.py`:

```python
def _parse_edges_from_lines(
    nodes: list[dict],
    lines_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
) -> list[dict]:
    """Format B: parse edges from lines GeoDataFrame with from_node/to_node."""
    from_col = field_mapping["edge_from"]
    to_col = field_mapping["edge_to"]

    edges = []
    for _, row in lines_gdf.iterrows():
        edge = {
            "from_id": str(row[from_col]),
            "to_id": str(row[to_col]),
            "geometry": row.geometry,
            "source": "user_data",
        }

        # Pipe attributes from line layer
        for attr in ("diameter", "width", "height", "cross_section",
                      "manning", "material", "invert_elev"):
            col = field_mapping.get(attr)
            if col and col in lines_gdf.columns:
                val = row[col]
                edge[attr] = None if (val is None or val != val) else val

        edges.append(edge)

    return edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/sewer_topology.py backend/tests/unit/test_sewer_topology.py
git commit -m "feat(core): sewer_topology format B parser (points + lines)"
```

---

## Task 5: sewer_topology.py — Strict validation (all rules from spec §6.3)

**Files:**
- Modify: `backend/core/sewer_topology.py`
- Modify: `backend/tests/unit/test_sewer_topology.py`

- [ ] **Step 1: Write failing tests for each validation rule**

Append to `test_sewer_topology.py`:

```python
class TestValidationDuplicateId:
    def test_duplicate_node_id(self, default_field_mapping, default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n1", "n2"],
                "role": ["inlet", "junction", "outlet"],
                "downstream_id": ["n1", "n2", None],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "duplicate_id" for e in exc_info.value.errors)


class TestValidationInvalidRole:
    def test_unknown_role(self, default_field_mapping, default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["pump", "outlet"],
                "downstream_id": ["n2", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "invalid_role" for e in exc_info.value.errors)


class TestValidationMissingTarget:
    def test_downstream_id_not_found(self, default_field_mapping,
                                      default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["n99", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "missing_target" for e in exc_info.value.errors)


class TestValidationOutletHasDownstream:
    def test_outlet_with_downstream(self, default_field_mapping,
                                     default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["inlet", "outlet", "junction"],
                "downstream_id": ["n2", "n3", None],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "outlet_has_downstream"
                   for e in exc_info.value.errors)


class TestValidationMissingDownstream:
    def test_inlet_without_downstream(self, default_field_mapping,
                                       default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "outlet"],
                "downstream_id": [None, None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "missing_downstream"
                   for e in exc_info.value.errors)


class TestValidationCycleDetected:
    def test_cycle(self, default_field_mapping, default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["inlet", "junction", "junction"],
                "downstream_id": ["n2", "n3", "n1"],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "cycle_detected" for e in exc_info.value.errors)


class TestValidationNoOutlet:
    def test_component_without_outlet(self, default_field_mapping,
                                       default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "junction"],
                "downstream_id": ["n2", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        errors = exc_info.value.errors
        error_types = [e["type"] for e in errors]
        # junction without downstream → missing_downstream
        # OR component without outlet → no_outlet
        assert "missing_downstream" in error_types or "no_outlet" in error_types


class TestValidationNoInlet:
    def test_component_without_inlet(self, default_field_mapping,
                                      default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["junction", "outlet"],
                "downstream_id": ["n2", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "no_inlet" for e in exc_info.value.errors)


class TestValidationDirectionMismatch:
    def test_edge_to_inlet(self, default_field_mapping, default_role_mapping):
        """Format B: edge pointing TO an inlet is invalid (inlets are sources)."""
        points = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["junction", "inlet", "outlet"],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        lines = gpd.GeoDataFrame(
            {
                "from_node": ["n1", "n1"],
                "to_node": ["n2", "n3"],
                "geometry": [
                    ShapelyLineString([(0, 0), (1, 1)]),
                    ShapelyLineString([(0, 0), (2, 2)]),
                ],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(points, lines, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "direction_mismatch" for e in exc_info.value.errors)

    def test_edge_from_outlet(self, default_field_mapping, default_role_mapping):
        """Format B: edge originating FROM an outlet is invalid (outlets are sinks)."""
        points = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["inlet", "outlet", "junction"],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        lines = gpd.GeoDataFrame(
            {
                "from_node": ["n1", "n2"],
                "to_node": ["n2", "n3"],
                "geometry": [
                    ShapelyLineString([(0, 0), (1, 1)]),
                    ShapelyLineString([(1, 1), (2, 2)]),
                ],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(points, lines, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "direction_mismatch" for e in exc_info.value.errors)


class TestValidationOrphanEdge:
    def test_edge_references_missing_node(self, default_field_mapping,
                                           default_role_mapping):
        points = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "outlet"],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        lines = gpd.GeoDataFrame(
            {
                "from_node": ["n1", "n99"],
                "to_node": ["n2", "n2"],
                "geometry": [
                    ShapelyLineString([(0, 0), (1, 1)]),
                    ShapelyLineString([(5, 5), (1, 1)]),
                ],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(points, lines, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "orphan_edge" for e in exc_info.value.errors)


class TestValidationValidData:
    def test_valid_y_junction(self, default_field_mapping, default_role_mapping):
        """Y-junction: 2 inlets → junction → outlet. Must pass."""
        gdf = gpd.GeoDataFrame(
            {
                "id": ["i1", "i2", "j1", "o1"],
                "role": ["inlet", "inlet", "junction", "outlet"],
                "downstream_id": ["j1", "j1", "o1", None],
                "geometry": [
                    Point(0, 0), Point(0, 2),
                    Point(1, 1), Point(2, 1),
                ],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        assert len(topo.nodes) == 4
        assert len(topo.edges) == 3

    def test_storage_node_passes(self, default_field_mapping,
                                  default_role_mapping):
        """Storage treated as junction — no special validation."""
        gdf = gpd.GeoDataFrame(
            {
                "id": ["i1", "s1", "o1"],
                "role": ["inlet", "storage", "outlet"],
                "downstream_id": ["s1", "o1", None],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        assert len(topo.nodes) == 3
        roles = {n["id"]: n["role"] for n in topo.nodes}
        assert roles["s1"] == "storage"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py::TestValidationDuplicateId -v --tb=short 2>&1 | tail -10`
Expected: FAIL — validation is currently a stub returning `[]`

- [ ] **Step 3: Implement _validate_topology**

Replace the stub `_validate_topology` in `sewer_topology.py`:

```python
def _validate_topology(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Validate topology consistency. Returns list of error dicts (empty=OK)."""
    errors: list[dict] = []
    node_ids = set()
    node_by_id = {}

    # 1. Duplicate IDs
    seen_ids: dict[str, int] = defaultdict(int)
    for node in nodes:
        seen_ids[node["id"]] += 1
    for nid, count in seen_ids.items():
        if count > 1:
            errors.append({
                "type": "duplicate_id",
                "node_id": nid,
                "message": f"Node id={nid} appears {count} times",
            })
    if errors:
        return errors  # can't continue with duplicate IDs

    node_ids = {n["id"] for n in nodes}
    node_by_id = {n["id"]: n for n in nodes}

    # 2. Invalid roles
    for node in nodes:
        if node["role"] not in VALID_ROLES:
            errors.append({
                "type": "invalid_role",
                "node_id": node["id"],
                "message": (
                    f"Node id={node['id']}: role '{node['role']}' "
                    f"not in {VALID_ROLES}"
                ),
            })

    # 3. Outlet has downstream (check edges from outlet)
    # Build downstream map from edges
    downstream_map: dict[str, str] = {}
    for edge in edges:
        downstream_map[edge["from_id"]] = edge["to_id"]

    for node in nodes:
        nid = node["id"]
        has_downstream = nid in downstream_map

        if node["role"] == "outlet" and has_downstream:
            errors.append({
                "type": "outlet_has_downstream",
                "node_id": nid,
                "message": (
                    f"Outlet id={nid} has downstream_id="
                    f"{downstream_map[nid]} — outlets must be terminal"
                ),
            })

        if node["role"] != "outlet" and not has_downstream:
            errors.append({
                "type": "missing_downstream",
                "node_id": nid,
                "message": f"{node['role'].capitalize()} id={nid} has no downstream_id",
            })

    # 4. Direction mismatch (Format B): inlet should not be to_node, outlet should not be from_node
    node_role_by_id = {n["id"]: n["role"] for n in nodes}
    for edge in edges:
        to_role = node_role_by_id.get(edge["to_id"])
        from_role = node_role_by_id.get(edge["from_id"])
        if to_role == "inlet":
            errors.append({
                "type": "direction_mismatch",
                "node_id": edge["to_id"],
                "message": (
                    f"Edge {edge['from_id']}→{edge['to_id']}: "
                    f"node {edge['to_id']} is inlet (should not be downstream target)"
                ),
            })
        if from_role == "outlet":
            errors.append({
                "type": "direction_mismatch",
                "node_id": edge["from_id"],
                "message": (
                    f"Edge {edge['from_id']}→{edge['to_id']}: "
                    f"node {edge['from_id']} is outlet (should not be upstream source)"
                ),
            })

    # 5. Edge targets exist
    for edge in edges:
        if edge["from_id"] not in node_ids:
            errors.append({
                "type": "orphan_edge",
                "node_id": edge["from_id"],
                "message": f"Edge from_node={edge['from_id']}: no matching point",
            })
        if edge["to_id"] not in node_ids:
            errors.append({
                "type": "orphan_edge",
                "node_id": edge["to_id"],
                "message": f"Edge to_node={edge['to_id']}: no matching point",
            })

    if errors:
        return errors  # can't check topology with broken references

    # 5. Cycle detection (DFS)
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs_cycle(nid: str) -> str | None:
        visited.add(nid)
        in_stack.add(nid)
        ds = downstream_map.get(nid)
        if ds:
            if ds in in_stack:
                # Reconstruct cycle
                cycle = [nid, ds]
                cur = ds
                while downstream_map.get(cur) != ds:
                    cur = downstream_map[cur]
                    cycle.append(cur)
                return " → ".join(cycle)
            if ds not in visited:
                return _dfs_cycle(ds)
        in_stack.discard(nid)
        return None

    for node in nodes:
        if node["id"] not in visited:
            cycle_str = _dfs_cycle(node["id"])
            if cycle_str:
                errors.append({
                    "type": "cycle_detected",
                    "node_id": node["id"],
                    "message": f"Cycle: {cycle_str}",
                })
                break  # one cycle error is enough

    if errors:
        return errors

    # 6. Component analysis — find connected components
    # Build undirected adjacency
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adj[edge["from_id"]].add(edge["to_id"])
        adj[edge["to_id"]].add(edge["from_id"])

    component_map: dict[str, int] = {}
    comp_id = 0
    for node in nodes:
        nid = node["id"]
        if nid in component_map:
            continue
        # BFS to find component
        queue = deque([nid])
        component_map[nid] = comp_id
        while queue:
            cur = queue.popleft()
            for neighbor in adj.get(cur, []):
                if neighbor not in component_map:
                    component_map[neighbor] = comp_id
                    queue.append(neighbor)
        comp_id += 1

    # Check each component has outlet and inlet
    components: dict[int, list[dict]] = defaultdict(list)
    for node in nodes:
        cid = component_map.get(node["id"], -1)
        components[cid].append(node)

    for cid, comp_nodes in components.items():
        roles_in_comp = {n["role"] for n in comp_nodes}
        ids_in_comp = {n["id"] for n in comp_nodes}

        if "outlet" not in roles_in_comp:
            errors.append({
                "type": "no_outlet",
                "node_id": None,
                "message": f"Component {ids_in_comp} has no outlet",
            })
        if "inlet" not in roles_in_comp:
            errors.append({
                "type": "no_inlet",
                "node_id": None,
                "message": f"Component {ids_in_comp} has no inlet",
            })

    return errors
```

- [ ] **Step 4: Run all topology tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py -v --tb=short 2>&1 | tail -40`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/sewer_topology.py backend/tests/unit/test_sewer_topology.py
git commit -m "feat(core): sewer_topology strict validation — all rules from spec"
```

---

## Task 6: sewer_topology.py — validate_against_fdir (feedback loop detection)

**Files:**
- Modify: `backend/core/sewer_topology.py`
- Modify: `backend/tests/unit/test_sewer_topology.py`

- [ ] **Step 1: Write failing tests for fdir loop detection**

Append to `test_sewer_topology.py`:

```python
from core.sewer_topology import validate_against_fdir
from rasterio.transform import from_bounds


class TestValidateAgainstFdir:
    @pytest.fixture
    def small_fdir_no_loop(self):
        """10x10 fdir grid, all flowing SE (value=2 in D8). No loop."""
        # D8: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
        fdir = np.full((10, 10), 2, dtype=np.uint8)
        fdir[9, 9] = 0  # pit at SE corner
        transform = from_bounds(0, 0, 50, 50, 10, 10)
        return fdir, transform

    def test_no_loop_returns_empty(self, small_fdir_no_loop, default_field_mapping,
                                    default_role_mapping):
        fdir, transform = small_fdir_no_loop
        # Outlet at (row=2, col=2), inlet at (row=8, col=8)
        # Flow goes SE → outlet is upstream of inlet in fdir → no loop
        gdf = gpd.GeoDataFrame(
            {
                "id": ["i1", "o1"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["o1", None],
                "geometry": [
                    Point(42.5, 7.5),   # row=8, col=8 (near SE)
                    Point(12.5, 37.5),  # row=2, col=2 (near NW)
                ],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        errors = validate_against_fdir(topo, fdir, transform)
        assert errors == []

    def test_loop_detected(self, small_fdir_no_loop, default_field_mapping,
                            default_role_mapping):
        fdir, transform = small_fdir_no_loop
        # Outlet at (row=8, col=8) = downstream in fdir
        # Inlet at (row=2, col=2) = upstream in fdir
        # Flow goes SE from outlet → eventually reaches inlet area → LOOP
        gdf = gpd.GeoDataFrame(
            {
                "id": ["i1", "o1"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["o1", None],
                "geometry": [
                    Point(12.5, 37.5),  # row=2, col=2 (NW = upstream)
                    Point(42.5, 7.5),   # row=8, col=8 (SE = downstream)
                ],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        # Outlet at SE, fdir flows SE → outlet's downstream path hits pit at (9,9)
        # Inlet is at NW (2,2) — NOT on the path from outlet → no loop expected here
        # Need a scenario where outlet IS upstream of inlet in fdir
        # Actually: outlet at NW, fdir flows SE, inlet at SE
        # Outlet's fdir path: (2,2)→(3,3)→...→(8,8) which IS the inlet cell
        gdf2 = gpd.GeoDataFrame(
            {
                "id": ["i1", "o1"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["o1", None],
                "geometry": [
                    Point(42.5, 7.5),   # row=8, col=8 (SE = downstream in fdir)
                    Point(12.5, 37.5),  # row=2, col=2 (NW = upstream in fdir)
                ],
            },
            crs="EPSG:2180",
        )
        topo2 = parse_sewer_topology(gdf2, None, default_field_mapping,
                                      default_role_mapping)
        errors = validate_against_fdir(topo2, fdir, transform)
        assert len(errors) > 0
        assert errors[0]["type"] == "feedback_loop"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py::TestValidateAgainstFdir -v --tb=short 2>&1 | tail -10`
Expected: FAIL

- [ ] **Step 3: Implement validate_against_fdir**

Add to `sewer_topology.py`:

```python
# D8 direction offsets: value → (drow, dcol)
_D8_OFFSETS = {
    1: (0, 1),     # E
    2: (1, 1),     # SE
    4: (1, 0),     # S
    8: (1, -1),    # SW
    16: (0, -1),   # W
    32: (-1, -1),  # NW
    64: (-1, 0),   # N
    128: (-1, 1),  # NE
}

# Reverse D8: which fdir values point to a given (drow, dcol) offset?
_D8_REVERSE = {(-dr, -dc): val for val, (dr, dc) in _D8_OFFSETS.items()}


def _get_capture_zone(
    row: int, col: int, fdir: np.ndarray,
) -> set[tuple[int, int]]:
    """Get inlet capture zone: the cell itself + 8-neighbors whose fdir points to it."""
    nrows, ncols = fdir.shape
    zone = {(row, col)}
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if 0 <= nr < nrows and 0 <= nc < ncols:
                # Check if neighbor's fdir points to (row, col)
                neighbor_fdir = int(fdir[nr, nc])
                offset = _D8_OFFSETS.get(neighbor_fdir)
                if offset and (nr + offset[0], nc + offset[1]) == (row, col):
                    zone.add((nr, nc))
    return zone


def _trace_fdir_downstream(
    row: int, col: int, fdir: np.ndarray, max_steps: int = 10_000,
) -> set[tuple[int, int]]:
    """Trace fdir downstream from a cell. Returns set of visited cells."""
    nrows, ncols = fdir.shape
    path: set[tuple[int, int]] = set()
    r, c = row, col
    for _ in range(max_steps):
        if (r, c) in path:
            break  # cycle in fdir
        path.add((r, c))
        direction = int(fdir[r, c])
        offset = _D8_OFFSETS.get(direction)
        if offset is None:
            break  # pit or nodata
        nr, nc = r + offset[0], c + offset[1]
        if not (0 <= nr < nrows and 0 <= nc < ncols):
            break  # edge of raster
        r, c = nr, nc
    return path


def validate_against_fdir(
    topology: ParsedTopology,
    fdir: np.ndarray,
    transform,
) -> list[dict]:
    """Check for feedback loops: outlet's downstream fdir path must not
    reach any inlet's capture zone in the same component.

    Parameters
    ----------
    topology : ParsedTopology
        Parsed and validated topology.
    fdir : np.ndarray
        D8 flow direction grid (clean, no sewer pits).
    transform : Affine
        Rasterio affine transform for the fdir grid.

    Returns
    -------
    list[dict]
        List of error dicts (empty = OK).
    """
    errors: list[dict] = []
    nrows, ncols = fdir.shape

    # Map nodes to raster cells
    for node in topology.nodes:
        col_f, row_f = ~transform * (node["x"], node["y"])
        node["_row"] = int(round(row_f))
        node["_col"] = int(round(col_f))

    # Build component map from edges
    downstream_map: dict[str, str] = {}
    for edge in topology.edges:
        downstream_map[edge["from_id"]] = edge["to_id"]

    # Assign components
    node_by_id = {n["id"]: n for n in topology.nodes}
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in topology.edges:
        adj[edge["from_id"]].add(edge["to_id"])
        adj[edge["to_id"]].add(edge["from_id"])

    component_map: dict[str, int] = {}
    comp_id = 0
    for node in topology.nodes:
        nid = node["id"]
        if nid in component_map:
            continue
        queue = deque([nid])
        component_map[nid] = comp_id
        while queue:
            cur = queue.popleft()
            for neighbor in adj.get(cur, []):
                if neighbor not in component_map:
                    component_map[neighbor] = comp_id
                    queue.append(neighbor)
        comp_id += 1

    # Build capture zones for inlets per component
    comp_inlet_zones: dict[int, dict[str, set[tuple[int, int]]]] = defaultdict(dict)
    for node in topology.nodes:
        if node["role"] == "inlet":
            r, c = node["_row"], node["_col"]
            if 0 <= r < nrows and 0 <= c < ncols:
                cid = component_map[node["id"]]
                comp_inlet_zones[cid][node["id"]] = _get_capture_zone(r, c, fdir)

    # For each outlet, trace fdir downstream and check for inlet capture zones
    for node in topology.nodes:
        if node["role"] != "outlet":
            continue
        r, c = node["_row"], node["_col"]
        if not (0 <= r < nrows and 0 <= c < ncols):
            continue

        cid = component_map[node["id"]]
        inlet_zones = comp_inlet_zones.get(cid, {})
        if not inlet_zones:
            continue

        # All inlet zone cells for this component
        all_zone_cells: dict[tuple[int, int], str] = {}
        for inlet_id, zone in inlet_zones.items():
            for cell in zone:
                all_zone_cells[cell] = inlet_id

        path = _trace_fdir_downstream(r, c, fdir)
        for cell in path:
            if cell in all_zone_cells:
                inlet_id = all_zone_cells[cell]
                errors.append({
                    "type": "feedback_loop",
                    "node_id": node["id"],
                    "message": (
                        f"Outlet id={node['id']} drains to inlet "
                        f"id={inlet_id} capture zone"
                    ),
                })
                break  # one error per outlet

    return errors
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_topology.py -v --tb=short 2>&1 | tail -40`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/sewer_topology.py backend/tests/unit/test_sewer_topology.py
git commit -m "feat(core): sewer_topology validate_against_fdir — feedback loop detection"
```

---

## Task 7: download_sewer.py — tuple return, ZIP support, auto-detect format

**Files:**
- Modify: `backend/scripts/download_sewer.py`
- Modify: `backend/tests/unit/test_download_sewer.py`

- [ ] **Step 1: Write failing tests**

Append to `test_download_sewer.py`:

```python
import tempfile
import zipfile
from pathlib import Path


class TestLoadSewerDataTupleReturn:
    def test_returns_tuple(self, tmp_path):
        """load_sewer_data now returns (points_gdf, lines_gdf | None)."""
        # Create a minimal GPKG with point layer
        gdf = gpd.GeoDataFrame(
            {"id": ["n1"], "role": ["outlet"], "geometry": [Point(500_000, 200_000)]},
            crs="EPSG:2180",
        )
        path = tmp_path / "test.gpkg"
        gdf.to_file(path, layer="nodes", driver="GPKG")

        config = {
            "sewer": {
                "source": {"type": "file", "path": str(path), "points_layer": "nodes"},
                "field_mapping": {"node_id": "id", "node_role": "role"},
            }
        }
        result = load_sewer_data(config)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_points_only_returns_none_lines(self, tmp_path):
        gdf = gpd.GeoDataFrame(
            {"id": ["n1"], "role": ["outlet"], "geometry": [Point(500_000, 200_000)]},
            crs="EPSG:2180",
        )
        path = tmp_path / "test.gpkg"
        gdf.to_file(path, layer="nodes", driver="GPKG")

        config = {
            "sewer": {
                "source": {"type": "file", "path": str(path), "points_layer": "nodes"},
                "field_mapping": {"node_id": "id", "node_role": "role"},
            }
        }
        points, lines = load_sewer_data(config)
        assert points is not None
        assert lines is None


class TestAutoDetectFormat:
    def test_gpkg_two_layers_detected(self, tmp_path):
        """GPKG with point + line layers → returns both."""
        pts = gpd.GeoDataFrame(
            {"id": ["n1", "n2"], "role": ["inlet", "outlet"],
             "geometry": [Point(0, 0), Point(1, 1)]},
            crs="EPSG:2180",
        )
        lns = gpd.GeoDataFrame(
            {"from_node": ["n1"], "to_node": ["n2"],
             "geometry": [ShapelyLineString([(0, 0), (1, 1)])]},
            crs="EPSG:2180",
        )
        path = tmp_path / "sewer.gpkg"
        pts.to_file(path, layer="nodes", driver="GPKG")
        lns.to_file(path, layer="pipes", driver="GPKG")

        config = {
            "sewer": {
                "source": {
                    "type": "file", "path": str(path),
                    "format": "auto",
                    "points_layer": "nodes", "lines_layer": "pipes",
                },
                "field_mapping": {"node_id": "id", "node_role": "role"},
            }
        }
        points, lines = load_sewer_data(config)
        assert points is not None
        assert lines is not None
        assert len(lines) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_download_sewer.py::TestLoadSewerDataTupleReturn -v --tb=short 2>&1 | tail -10`
Expected: FAIL — `load_sewer_data` returns GeoDataFrame, not tuple

- [ ] **Step 3: Modify download_sewer.py**

Key changes to `backend/scripts/download_sewer.py`:

1. `load_from_file()` → return `tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None]`
2. `load_sewer_data()` → return `tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None]`
3. Add ZIP handling with `_load_from_zip()`
4. Add auto-detect format logic

The `load_from_file` function (lines 94-113) needs to:
- Read `points_layer` as main GeoDataFrame
- If `lines_layer` is specified, read it as second GeoDataFrame
- If format="auto" and GPKG, use `fiona.listlayers()` to detect

`load_sewer_data` (lines 149-182) needs to:
- Return `(points_gdf, lines_gdf)` tuple
- Support `format` config key

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_download_sewer.py -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 5: Run existing tests to check backward compat**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short -k sewer 2>&1 | tail -30`
Expected: ALL PASS (including old tests — any callers of `load_sewer_data` need update)

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/download_sewer.py backend/tests/unit/test_download_sewer.py
git commit -m "feat(core): download_sewer returns tuple (points, lines), ZIP + auto-detect"
```

---

## Task 8: sewer_service.py — remove heuristics, new build_sewer_graph(ParsedTopology)

**Files:**
- Modify: `backend/core/sewer_service.py`
- Modify: `backend/tests/unit/test_sewer_service.py`

- [ ] **Step 1: Write failing tests for new interface**

Replace fixture and key tests in `test_sewer_service.py`:

```python
"""Unit tests for core.sewer_service module (new topology interface)."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from core.sewer_topology import ParsedTopology, parse_sewer_topology
from core.sewer_service import (
    SewerGraph,
    build_sewer_graph,
    burn_inlets,
    propagate_fa_downstream,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
)


@pytest.fixture
def y_junction_topology():
    """Y-junction: 2 inlets → junction → outlet, pre-parsed."""
    gdf = gpd.GeoDataFrame(
        {
            "id": ["i1", "i2", "j1", "o1"],
            "role": ["inlet", "inlet", "junction", "outlet"],
            "downstream_id": ["j1", "j1", "o1", None],
            "geometry": [
                Point(500_000, 200_000),
                Point(500_000, 200_200),
                Point(500_100, 200_100),
                Point(500_200, 200_100),
            ],
        },
        crs="EPSG:2180",
    )
    field_mapping = {
        "node_id": "id", "node_role": "role",
        "downstream_id": "downstream_id",
        "edge_from": "from_node", "edge_to": "to_node",
    }
    role_mapping = {"inlet": "inlet", "outlet": "outlet",
                    "junction": "junction", "storage": "storage"}
    return parse_sewer_topology(gdf, None, field_mapping, role_mapping)


class TestBuildSewerGraphNew:
    def test_accepts_parsed_topology(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert isinstance(graph, SewerGraph)

    def test_node_count(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert graph.n_nodes == 4

    def test_edge_count(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert graph.n_edges == 3

    def test_node_types(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        inlets = graph.get_nodes_by_type("inlet")
        outlets = graph.get_nodes_by_type("outlet")
        junctions = graph.get_nodes_by_type("junction")
        assert len(inlets) == 2
        assert len(outlets) == 1
        assert len(junctions) == 1

    def test_upstream_inlets_from_outlet(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        outlets = graph.get_nodes_by_type("outlet")
        inlet_ids = graph.get_upstream_inlets(outlets[0]["id"])
        assert len(inlet_ids) == 2

    def test_adjacency_matrix(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        # adj[downstream, upstream] convention
        assert graph.adj.nnz == 3  # 3 directed edges
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py::TestBuildSewerGraphNew -v --tb=short 2>&1 | tail -10`
Expected: FAIL — `build_sewer_graph()` expects GeoDataFrame, not ParsedTopology

- [ ] **Step 3: Rewrite build_sewer_graph in sewer_service.py**

Replace `build_sewer_graph()` (lines 229-546) and remove `_snap_endpoints` (72-159), `_assign_directions_by_topology` (162-226), `_detect_outlets` (713-766).

New `build_sewer_graph()`:

```python
def build_sewer_graph(topology: "ParsedTopology") -> SewerGraph:
    """Build directed sewer graph from pre-validated ParsedTopology.

    Topology is explicit — nodes have roles, edges have from/to.
    No snapping, no direction heuristics, no auto-detect.
    """
    graph = SewerGraph()

    # 1. Create nodes with sequential indices
    node_id_to_idx: dict[str, int] = {}
    for i, node_data in enumerate(topology.nodes):
        node = {
            "id": node_data["id"],
            "idx": i,
            "node_type": node_data["role"],
            "x": node_data["x"],
            "y": node_data["y"],
        }
        # Copy optional attributes
        for attr in ("invert_elev", "depth", "diameter",
                      "rim_elevation", "max_depth", "ponded_area",
                      "outfall_type"):
            if attr in node_data:
                node[attr] = node_data[attr]

        graph.nodes.append(node)
        node_id_to_idx[node_data["id"]] = i

    # 2. Create edges
    n = len(graph.nodes)
    rows, cols = [], []

    for edge_data in topology.edges:
        from_idx = node_id_to_idx[edge_data["from_id"]]
        to_idx = node_id_to_idx[edge_data["to_id"]]

        edge = {
            "from_idx": from_idx,
            "to_idx": to_idx,
            "from_id": edge_data["from_id"],
            "to_id": edge_data["to_id"],
            "geometry": edge_data.get("geometry"),
            "source": edge_data.get("source", "user_data"),
            "length_m": (
                edge_data["geometry"].length if edge_data.get("geometry") else 0.0
            ),
        }
        # Copy pipe attributes
        for attr in ("diameter", "width", "height", "cross_section",
                      "manning", "material", "invert_elev"):
            if attr in edge_data:
                edge[attr] = edge_data[attr]

        graph.edges.append(edge)

        # adj[downstream, upstream] = 1 (convention from original code)
        rows.append(to_idx)
        cols.append(from_idx)

    # 3. Build adjacency matrix
    if n > 0:
        data = np.ones(len(rows), dtype=np.int8)
        graph.adj = sparse.csr_matrix(
            (data, (rows, cols)), shape=(n, n),
        )
    else:
        graph.adj = sparse.csr_matrix((0, 0), dtype=np.int8)

    # 4. Connected components
    if n > 0:
        n_comp, labels = connected_components(graph.adj, directed=False)
        graph.n_components = n_comp
        for i, node in enumerate(graph.nodes):
            node["component_id"] = int(labels[i])
    else:
        graph.n_components = 0

    # 5. Assign root_outlet_id via BFS from each outlet
    outlets = [n for n in graph.nodes if n["node_type"] == "outlet"]
    for outlet in outlets:
        outlet["root_outlet_id"] = None  # outlet has no root_outlet
        # BFS upstream
        visited = {outlet["idx"]}
        queue = deque([outlet["idx"]])
        while queue:
            cur = queue.popleft()
            # Find upstream neighbors: adj[cur, :] gives nodes that flow TO cur
            upstream = graph.adj[cur, :].nonzero()[1]
            for up_idx in upstream:
                if up_idx not in visited:
                    visited.add(up_idx)
                    graph.nodes[up_idx]["root_outlet_id"] = outlet["id"]
                    queue.append(up_idx)

    logger.info(
        "Built sewer graph: %d nodes, %d edges, %d components",
        graph.n_nodes, graph.n_edges, graph.n_components,
    )

    return graph
```

Update import at top of `sewer_service.py`:
```python
from __future__ import annotations
```

- [ ] **Step 4: Run new tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py::TestBuildSewerGraphNew -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 5: Remove old functions and update remaining tests**

Remove `_snap_endpoints`, `_assign_directions_by_topology`, `_detect_outlets`, and the old `build_sewer_graph`. Update or remove old test classes (`TestBuildSewerGraph`, `TestSnapEndpoints`, `TestUserOutlets`, `TestDirectionFromAttributes`) that test removed functions. Keep tests for `burn_inlets`, `reconstruct_inlet_fa`, `route_fa_through_sewer`, `propagate_fa_downstream`.

- [ ] **Step 6: Run full sewer test suite**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_sewer_service.py -v --tb=short 2>&1 | tail -30`
Expected: ALL PASS (old tests for removed functions deleted, new tests pass)

- [ ] **Step 7: Commit**

```bash
git add backend/core/sewer_service.py backend/tests/unit/test_sewer_service.py
git commit -m "refactor(core): sewer_service — remove heuristics, new build_sewer_graph(ParsedTopology)"
```

---

## Task 9: process_dem.py — two-phase pipeline with fdir loop validation

**Files:**
- Modify: `backend/scripts/process_dem.py:78-92,581-710`

- [ ] **Step 1: Update imports in process_dem.py**

Add imports at top (around line 78-92):

```python
from core.sewer_topology import (
    parse_sewer_topology,
    validate_against_fdir,
)
```

Update `build_sewer_graph` import — it now takes `ParsedTopology`, not `gdf`.

- [ ] **Step 2: Implement two-phase pipeline**

Replace the sewer section (lines ~581-710) with:

```python
# --- PHASE 1: Clean fdir (no sewer) for loop validation ---
sewer_graph = None
topology = None
if sewer_config and sewer_config.get("sewer", {}).get("enabled"):
    logger.info("Sewer enabled — running phase 1 (clean fdir for validation)")

    # Load sewer data
    sewer_cfg = sewer_config["sewer"]
    points_gdf, lines_gdf = load_sewer_data(sewer_config)

    # Parse topology
    field_mapping = sewer_cfg.get("field_mapping",
                                   sewer_cfg.get("attribute_mapping", {}))
    role_mapping = sewer_cfg.get("role_mapping", {
        "inlet": "inlet", "outlet": "outlet",
        "junction": "junction", "storage": "storage",
    })
    topology = parse_sewer_topology(
        points_gdf, lines_gdf, field_mapping, role_mapping,
    )

    # Phase 1: fill + fdir on clean DEM (no inlet burning)
    logger.info("Phase 1: computing clean fdir for loop validation")
    import pyflwdir
    dem_clean = dem.copy()
    # Use existing fill logic but WITHOUT sewer drain_points
    flw_clean = pyflwdir.from_dem(
        dem_clean,
        nodata=metadata.get("nodata", -9999),
        transform=transform,
        latlon=False,
    )
    fdir_clean = flw_clean.to_d8()

    # Map nodes to raster
    for node in topology.nodes:
        col_f, row_f = ~transform * (node["x"], node["y"])
        node["row"] = int(round(row_f))
        node["col"] = int(round(col_f))

    # Validate: check feedback loops
    loop_errors = validate_against_fdir(topology, fdir_clean, transform)
    if loop_errors:
        msg = "Sewer feedback loop detected:\n"
        for err in loop_errors:
            msg += f"  - {err['message']}\n"
        raise ValueError(msg)

    logger.info("Phase 1 complete — no feedback loops detected")

    # Phase 2: burn inlets + full hydrology
    inlets = [n for n in topology.nodes if n["node_type"] == "inlet"
              or n.get("role") == "inlet"]
    # Map topology nodes to graph nodes format expected by burn_inlets
    for node in topology.nodes:
        node["node_type"] = node.get("role", node.get("node_type"))

    dem, drain_points_sewer = burn_inlets(
        dem,
        [n for n in topology.nodes if n["node_type"] == "inlet"],
        default_depth_m=sewer_cfg.get("inlet_burn_depth_m", 0.5),
    )
    if drain_points is None:
        drain_points = []
    drain_points.extend(drain_points_sewer)

# ... existing fill + fdir + FA computation (now includes sewer drain_points) ...

# --- After FA computation: sewer routing ---
if topology is not None:
    sewer_graph = build_sewer_graph(topology)
    inlets = sewer_graph.get_nodes_by_type("inlet")
    # Map graph nodes to raster cells
    for node in sewer_graph.nodes:
        topo_node = next(
            (n for n in topology.nodes if n["id"] == node["id"]), None
        )
        if topo_node:
            node["row"] = topo_node["row"]
            node["col"] = topo_node["col"]

    reconstruct_inlet_fa(acc, fdir, inlets)
    route_fa_through_sewer(sewer_graph)
    outlets = sewer_graph.get_nodes_by_type("outlet")
    propagate_fa_downstream(acc, fdir, outlets)
```

Note: The exact integration depends on the current structure of `process_dem.py`. The developer should read lines 580-720 and adapt — the key change is:
1. Before existing fill/fdir/FA: parse topology, compute clean fdir, validate loops, burn inlets
2. After FA: build graph from topology, route FA

- [ ] **Step 3: Run integration tests**

Run: `cd backend && .venv/bin/python -m pytest tests/integration/test_sewer_pipeline.py -v --tb=short 2>&1 | tail -20`
Expected: Tests need updating (Task 10) — this step identifies what breaks.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/process_dem.py
git commit -m "feat(core): two-phase sewer pipeline with fdir loop validation"
```

---

## Task 10: Update integration tests for new pipeline

**Files:**
- Modify: `backend/tests/integration/test_sewer_pipeline.py`

- [ ] **Step 1: Update pipeline_state fixture**

The fixture needs to:
1. Create points GeoDataFrame (not lines)
2. Use `parse_sewer_topology()` instead of old `build_sewer_graph(gdf)`
3. Add phase 1 clean fdir + validation

Update the fixture to use the new API:

```python
from core.sewer_topology import parse_sewer_topology, validate_against_fdir

# In the fixture, replace:
#   sewer_graph = build_sewer_graph(sewer_gdf, ...)
# with:
field_mapping = {
    "node_id": "id", "node_role": "role",
    "downstream_id": "downstream_id",
    "edge_from": "from_node", "edge_to": "to_node",
    "diameter": "diameter_mm",
}
role_mapping = {
    "inlet": "inlet", "outlet": "outlet",
    "junction": "junction", "storage": "storage",
}
topology = parse_sewer_topology(points_gdf, None, field_mapping, role_mapping)

# Phase 1: clean fdir
# ... compute clean fdir ...
loop_errors = validate_against_fdir(topology, fdir_clean, transform)
assert loop_errors == [], f"Unexpected loop: {loop_errors}"

# Phase 2: burn + full hydrology
sewer_graph = build_sewer_graph(topology)
```

The synthetic sewer data fixture should be changed from LineString GeoDataFrame to Point GeoDataFrame with downstream_id.

- [ ] **Step 2: Run integration tests**

Run: `cd backend && .venv/bin/python -m pytest tests/integration/test_sewer_pipeline.py -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_sewer_pipeline.py
git commit -m "test(integration): update sewer pipeline tests for new topology interface"
```

---

## Task 11: admin.py — upload auto-detect, config field_mapping/role_mapping

**Files:**
- Modify: `backend/api/endpoints/admin.py:734-872`

- [ ] **Step 1: Update SewerConfigUpdate model (line 734)**

```python
class SewerConfigUpdate(BaseModel):
    """Request body for sewer config update."""

    enabled: bool = Field(..., description="Enable/disable sewer processing")
    source_path: str | None = Field(
        default=None, description="Path to sewer data file"
    )
    lines_layer: str | None = Field(
        default=None, description="Layer name for lines in multi-layer files"
    )
    points_layer: str | None = Field(
        default=None, description="Layer name for points in multi-layer files"
    )
    field_mapping: dict | None = Field(
        default=None, description="Column name mapping for topology fields"
    )
    role_mapping: dict | None = Field(
        default=None, description="Value mapping for node roles"
    )
```

- [ ] **Step 2: Update upload endpoint to report detected format**

In the upload endpoint (line 813-872), after successful `gpd.read_file()`, add format detection:

```python
# After reading the file successfully (around line 856)
import fiona

detected_format = "unknown"
layers_detected = []
try:
    layers = fiona.listlayers(str(dest))
    layers_detected = layers
    geom_types_per_layer = {}
    for layer_name in layers:
        layer_gdf = gpd.read_file(dest, layer=layer_name, rows=1)
        if not layer_gdf.empty:
            geom_types_per_layer[layer_name] = layer_gdf.geometry.iloc[0].geom_type

    has_points = any("Point" in gt for gt in geom_types_per_layer.values())
    has_lines = any("Line" in gt for gt in geom_types_per_layer.values())

    if has_points and has_lines:
        detected_format = "points_and_lines"
    elif has_points:
        detected_format = "points_only"
    elif has_lines:
        detected_format = "lines_only"
except Exception:
    pass  # fiona may fail on some formats

return {
    "filename": safe_name,
    "features": n_features,
    "geometry_types": geom_types,
    "detected_format": detected_format,
    "layers": layers_detected,
    "message": "Plik wgrany. Uruchom analizę, aby przetworzyć dane kanalizacyjne.",
}
```

- [ ] **Step 3: Update config endpoint to handle new fields**

In `sewer_config` endpoint (line 772-810), extend the config update dict to include `field_mapping`, `role_mapping`, `points_layer`:

```python
if body.field_mapping:
    updates.setdefault("field_mapping", {}).update(body.field_mapping)
if body.role_mapping:
    updates.setdefault("role_mapping", {}).update(body.role_mapping)
if body.points_layer:
    updates.setdefault("source", {})["points_layer"] = body.points_layer
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/endpoints/admin.py
git commit -m "feat(api): sewer upload auto-detect format, config field_mapping/role_mapping"
```

---

## Task 12: Frontend — detected_format display, storage node color

**Files:**
- Modify: `frontend/js/admin/admin-sewer.js`

- [ ] **Step 1: Update handleSewerUpload to show detected_format**

In `handleSewerUpload()` (around line 69-125), update the success display:

```javascript
// After successful upload response (around line 100)
const formatLabel = {
    'points_only': 'Format A (punkty z downstream_id)',
    'points_and_lines': 'Format B (punkty + linie)',
    'lines_only': 'Tylko linie (wymaga konwersji)',
    'unknown': 'Nierozpoznany format',
};
const fmt = formatLabel[data.detected_format] || data.detected_format;
const layers = data.layers && data.layers.length
    ? ` | Warstwy: ${data.layers.join(', ')}`
    : '';
resultEl.innerHTML =
    `<span class="text-success">Wgrany: ${data.features} obiektów ` +
    `(${data.geometry_types.join(', ')})</span><br>` +
    `<small class="text-muted">${fmt}${layers}</small>`;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/admin/admin-sewer.js
git commit -m "feat(frontend): show detected sewer format after upload"
```

---

## Task 13: Run full test suite + cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run full unit test suite**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -40`
Expected: ALL PASS. Fix any failures.

- [ ] **Step 2: Run integration tests**

Run: `cd backend && .venv/bin/python -m pytest tests/integration/ -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS (or skip if DB not available).

- [ ] **Step 3: Verify no regressions in existing tests**

Run: `cd backend && .venv/bin/python -m pytest tests/ --tb=short -q 2>&1 | tail -10`
Expected: 0 failures. Total test count should be similar to previous (1108) plus new topology tests.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: test suite cleanup after sewer topology rebuild"
```
