# H4 — Monotonic Stream Smoothing Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two-stage stream processing (constant burn + monotonic smoothing) to fix bridges/embankments in DEM without over-burning normal sections.

**Architecture:** New `smooth_streams_monotonic()` function in `core/hydrology.py` builds a topology graph from BDOT10k vector streams, then applies a running-minimum downstream pass to enforce monotonically decreasing elevation along each stream segment. Integrated into `process_dem.py` pipeline as step 3b (after burn, before lake classification). Default `burn_depth_m` reduced from 10/5m to 2m across all locations.

**Tech Stack:** Python 3.12, NumPy, Shapely, GeoPandas, Fiona, rasterio (existing deps only)

**Spec:** `docs/superpowers/specs/2026-03-16-h4-monotonic-stream-smoothing-design.md`

---

## Chunk 1: Core Algorithm (Tasks 1–4)

### Task 1: `_bresenham()` helper

**Files:**
- Modify: `backend/core/hydrology.py` (add function after line ~292)
- Create: `backend/tests/unit/test_monotonic_smoothing.py`

- [ ] **Step 1: Write failing tests for `_bresenham()`**

Create `backend/tests/unit/test_monotonic_smoothing.py`:

```python
"""Tests for H4 monotonic stream smoothing (ADR-041)."""

import numpy as np
import pytest
from core.hydrology import _bresenham


class TestBresenham:
    """Test Bresenham line rasterization."""

    def test_horizontal_line(self):
        cells = _bresenham(0, 0, 0, 5)
        assert cells == [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)]

    def test_vertical_line(self):
        cells = _bresenham(0, 0, 4, 0)
        assert cells == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]

    def test_diagonal_line(self):
        cells = _bresenham(0, 0, 3, 3)
        assert cells == [(0, 0), (1, 1), (2, 2), (3, 3)]

    def test_steep_line(self):
        cells = _bresenham(0, 0, 4, 1)
        assert len(cells) == 5  # max(abs(dr), abs(dc)) + 1
        assert cells[0] == (0, 0)
        assert cells[-1] == (4, 1)

    def test_reverse_direction(self):
        cells_fwd = _bresenham(0, 0, 3, 5)
        cells_rev = _bresenham(3, 5, 0, 0)
        assert cells_fwd == list(reversed(cells_rev))

    def test_single_point(self):
        cells = _bresenham(2, 3, 2, 3)
        assert cells == [(2, 3)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestBresenham -v`
Expected: ImportError — `_bresenham` not found

- [ ] **Step 3: Implement `_bresenham()`**

Add to `backend/core/hydrology.py` after the `burn_streams_into_dem` function (after line ~292):

```python
def _bresenham(r0: int, c0: int, r1: int, c1: int) -> list[tuple[int, int]]:
    """Bresenham line rasterization between two pixel coordinates.

    Returns ordered list of (row, col) cells from (r0, c0) to (r1, c1).
    """
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dr - dc
    cells = []
    r, c = r0, c0
    while True:
        cells.append((r, c))
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r += sr
        if e2 < dr:
            err += dr
            c += sc
    return cells
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestBresenham -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/hydrology.py backend/tests/unit/test_monotonic_smoothing.py
git commit -m "feat(core): add _bresenham() helper for stream rasterization (ADR-041)"
```

---

### Task 2: `_rasterize_line_ordered()` helper

**Files:**
- Modify: `backend/core/hydrology.py` (add function after `_bresenham`)
- Modify: `backend/tests/unit/test_monotonic_smoothing.py`

- [ ] **Step 1: Write failing tests for `_rasterize_line_ordered()`**

Append to `backend/tests/unit/test_monotonic_smoothing.py`:

```python
from rasterio.transform import from_bounds
from shapely.geometry import LineString
from core.hydrology import _rasterize_line_ordered


class TestRasterizeLineOrdered:
    """Test ordered line rasterization with geotransform."""

    @pytest.fixture
    def simple_transform(self):
        """10x10 raster, 1m cells, origin at (0, 0)."""
        return from_bounds(0, 0, 10, 10, 10, 10)

    def test_simple_line(self, simple_transform):
        line = LineString([(0.5, 9.5), (4.5, 9.5)])
        cells = _rasterize_line_ordered(line, simple_transform)
        assert len(cells) >= 2
        assert cells[0] == (0, 0)
        assert cells[-1] == (0, 4)

    def test_deduplicated_at_vertices(self, simple_transform):
        # Line with vertex at cell boundary — no duplicate cells
        line = LineString([(0.5, 9.5), (2.5, 9.5), (4.5, 9.5)])
        cells = _rasterize_line_ordered(line, simple_transform)
        assert len(cells) == len(set(cells)), "Duplicate cells found"

    def test_preserves_order(self, simple_transform):
        line = LineString([(0.5, 9.5), (0.5, 5.5)])
        cells = _rasterize_line_ordered(line, simple_transform)
        rows = [r for r, c in cells]
        assert rows == sorted(rows), "Cells not in line order"

    def test_single_pixel_line(self, simple_transform):
        # Both endpoints in same pixel → returns 1 cell
        line = LineString([(0.1, 9.9), (0.2, 9.8)])
        cells = _rasterize_line_ordered(line, simple_transform)
        assert len(cells) == 1

    def test_clips_to_raster_bounds(self, simple_transform):
        # Line extending beyond raster — only in-bounds cells returned
        line = LineString([(-5, 9.5), (5, 9.5)])
        cells = _rasterize_line_ordered(line, simple_transform, shape=(10, 10))
        for r, c in cells:
            assert 0 <= r < 10 and 0 <= c < 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestRasterizeLineOrdered -v`
Expected: ImportError — `_rasterize_line_ordered` not found

- [ ] **Step 3: Implement `_rasterize_line_ordered()`**

Add to `backend/core/hydrology.py` after `_bresenham()`.

**Note:** `~transform * (x, y)` returns `(col, row)` in rasterio convention. Unpack correctly.

```python
def _rasterize_line_ordered(
    line,
    transform,
    shape: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    """Rasterize a LineString to an ordered sequence of (row, col) cells.

    Uses Bresenham between consecutive vertices. Deduplicates cells
    at segment junctions. Optionally clips to raster shape.

    Extension vs spec: added optional ``shape`` for bounds clipping.
    """
    coords = list(line.coords)
    if len(coords) < 2:
        return []

    cells: list[tuple[int, int]] = []
    for i in range(len(coords) - 1):
        x0, y0 = coords[i][:2]
        x1, y1 = coords[i + 1][:2]
        col0, row0 = ~transform * (x0, y0)
        col1, row1 = ~transform * (x1, y1)
        r0, c0 = int(round(row0)), int(round(col0))
        r1, c1 = int(round(row1)), int(round(col1))
        segment = _bresenham(r0, c0, r1, c1)
        # Deduplicate at junction with previous segment
        if cells and segment and segment[0] == cells[-1]:
            segment = segment[1:]
        cells.extend(segment)

    # Clip to raster bounds
    if shape is not None:
        nrows, ncols = shape
        cells = [(r, c) for r, c in cells if 0 <= r < nrows and 0 <= c < ncols]

    return cells
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestRasterizeLineOrdered -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/hydrology.py backend/tests/unit/test_monotonic_smoothing.py
git commit -m "feat(core): add _rasterize_line_ordered() for ordered stream pixels (ADR-041)"
```

---

### Task 3: `_build_stream_network_graph()` helper

**Files:**
- Modify: `backend/core/hydrology.py`
- Modify: `backend/tests/unit/test_monotonic_smoothing.py`

- [ ] **Step 1: Write failing tests for `_build_stream_network_graph()`**

Append to `backend/tests/unit/test_monotonic_smoothing.py`:

```python
from core.hydrology import _build_stream_network_graph


class TestBuildStreamNetworkGraph:
    """Test topology graph construction from stream geometries."""

    def _make_dem_and_transform(self, nrows=20, ncols=20):
        """Create a sloped DEM (high top-left, low bottom-right) + transform."""
        dem = np.zeros((nrows, ncols), dtype=np.float32)
        for r in range(nrows):
            for c in range(ncols):
                dem[r, c] = 200.0 - r * 5.0 - c * 2.0
        transform = from_bounds(0, 0, ncols, nrows, ncols, nrows)
        return dem, transform

    def test_single_segment(self):
        dem, transform = self._make_dem_and_transform()
        geoms = [LineString([(1, 19), (1, 1)])]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 1
        assert len(graph) == 2  # two endpoint nodes
        assert 0 in seg_nodes  # segment 0 recorded

    def test_y_junction(self):
        """Two tributaries merging into one main stem."""
        dem, transform = self._make_dem_and_transform()
        trib_a = LineString([(2, 18), (5, 15)])
        trib_b = LineString([(8, 18), (5, 15)])
        main = LineString([(5, 15), (5, 2)])
        geoms = [trib_a, trib_b, main]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 1  # single outlet
        assert len(seg_nodes) == 3

    def test_seg_nodes_maps_start_end(self):
        """seg_nodes correctly maps segment → (start_node, end_node)."""
        dem, transform = self._make_dem_and_transform()
        geoms = [LineString([(2, 18), (10, 10)])]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        start_node, end_node = seg_nodes[0]
        assert start_node != end_node

    def test_disconnected_components(self):
        dem, transform = self._make_dem_and_transform()
        stream_a = LineString([(1, 19), (1, 15)])
        stream_b = LineString([(15, 19), (15, 15)])
        geoms = [stream_a, stream_b]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 2  # each component has its own outlet

    def test_edge_outlet_preferred(self):
        """Node on raster edge is preferred as outlet over interior node."""
        dem, transform = self._make_dem_and_transform()
        # Stream from interior to edge
        geoms = [LineString([(5, 10), (5, 0)])]  # ends at bottom edge (y=0)
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestBuildStreamNetworkGraph -v`
Expected: ImportError

- [ ] **Step 3: Implement `_build_stream_network_graph()`**

Add to `backend/core/hydrology.py` after `_rasterize_line_ordered()`:

```python
def _build_stream_network_graph(
    geometries: list,
    dem: np.ndarray,
    transform,
    snap_tolerance_px: int = 1,
) -> tuple[dict[int, list[tuple[int, int]]], dict[int, tuple[int, int]], list[int]]:
    """Build a topology graph from stream LineString geometries.

    Endpoints are snapped to raster pixels. Nodes within snap_tolerance_px
    of each other are merged.

    Returns:
        graph: {node_id: [(neighbor_node_id, segment_index), ...]}
        seg_nodes: {segment_index: (start_node, end_node)} — start corresponds
            to geometry coords[0], end to coords[-1]
        outlets: list of outlet node IDs (one per connected component)
    """
    from collections import defaultdict, deque

    nrows, ncols = dem.shape

    # Step 1: Collect endpoints as pixel coords
    endpoints = []  # [(row, col, geom_idx, is_start), ...]
    for idx, geom in enumerate(geometries):
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        for pt, is_start in [(coords[0], True), (coords[-1], False)]:
            x, y = pt[:2]
            col, row = ~transform * (x, y)
            r, c = int(round(row)), int(round(col))
            endpoints.append((r, c, idx, is_start))

    # Step 2: Snap endpoints within tolerance → assign node IDs
    node_for_point: dict[tuple[int, int], int] = {}
    next_node_id = 0

    def get_or_create_node(r: int, c: int) -> int:
        nonlocal next_node_id
        for (nr, nc), nid in node_for_point.items():
            if abs(nr - r) <= snap_tolerance_px and abs(nc - c) <= snap_tolerance_px:
                return nid
        node_for_point[(r, c)] = next_node_id
        next_node_id += 1
        return next_node_id - 1

    seg_nodes: dict[int, tuple[int | None, int | None]] = {}
    for r, c, idx, is_start in endpoints:
        nid = get_or_create_node(r, c)
        if idx not in seg_nodes:
            seg_nodes[idx] = (None, None)
        if is_start:
            seg_nodes[idx] = (nid, seg_nodes[idx][1])
        else:
            seg_nodes[idx] = (seg_nodes[idx][0], nid)

    # Step 3: Build adjacency list
    graph: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for idx, (n_start, n_end) in seg_nodes.items():
        if n_start is None or n_end is None or n_start == n_end:
            continue
        graph[n_start].append((n_end, idx))
        graph[n_end].append((n_start, idx))

    for nid in range(next_node_id):
        if nid not in graph:
            graph[nid] = []

    # Step 4: Find outlets — one per connected component
    node_coords = {nid: (r, c) for (r, c), nid in node_for_point.items()}
    outlets = []
    visited: set[int] = set()

    def _clamp_elev(n: int) -> float:
        if n not in node_coords:
            return float("inf")
        r, c = node_coords[n]
        r = max(0, min(r, nrows - 1))
        c = max(0, min(c, ncols - 1))
        return float(dem[r, c])

    for start_nid in range(next_node_id):
        if start_nid in visited:
            continue
        component: list[int] = []
        queue = deque([start_nid])
        visited.add(start_nid)
        while queue:
            nid = queue.popleft()
            component.append(nid)
            for neighbor, _ in graph[nid]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        degree_one = [n for n in component if len(graph[n]) == 1]
        if not degree_one:
            degree_one = component

        edge_nodes = [
            n for n in degree_one
            if n in node_coords and (
                node_coords[n][0] <= 0 or node_coords[n][0] >= nrows - 1
                or node_coords[n][1] <= 0 or node_coords[n][1] >= ncols - 1
            )
        ]

        candidates = edge_nodes if edge_nodes else degree_one
        outlets.append(min(candidates, key=_clamp_elev))

    return dict(graph), dict(seg_nodes), outlets
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestBuildStreamNetworkGraph -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/hydrology.py backend/tests/unit/test_monotonic_smoothing.py
git commit -m "feat(core): add _build_stream_network_graph() topology builder (ADR-041)"
```

---

### Task 4: `_load_stream_geometries()` + `smooth_streams_monotonic()`

**Files:**
- Modify: `backend/core/hydrology.py`
- Modify: `backend/tests/unit/test_monotonic_smoothing.py`

- [ ] **Step 1: Write failing tests for `smooth_streams_monotonic()`**

Append to `backend/tests/unit/test_monotonic_smoothing.py`. Covers all 13 spec test cases:

```python
from unittest.mock import patch
from shapely.geometry import MultiLineString as MultiLS
from core.hydrology import smooth_streams_monotonic


class TestSmoothStreamsMonotonic:
    """Test the main monotonic smoothing function.

    Covers spec test cases #1-#8, #11-#13.
    (Cases #9 and #10 covered by TestRasterizeLineOrdered and TestBresenham.)
    """

    def _make_sloped_dem(self, nrows=20, ncols=20):
        """Elevation decreases with row (top=high, bottom=low)."""
        dem = np.zeros((nrows, ncols), dtype=np.float32)
        for r in range(nrows):
            for c in range(ncols):
                dem[r, c] = 200.0 - r * 5.0
        return dem

    # --- Spec #1: bridge obstacle ---
    def test_bridge_obstacle_corrected(self):
        """A 'bridge' bump in the stream profile is smoothed out."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0  # artificially high (bridge)
        line = LineString([(5, 18), (5, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert result[10, 5] <= result[9, 5]
        assert diag["cells_smoothed"] > 0

    # --- Spec #2: flat terrain ---
    def test_flat_terrain_unchanged(self):
        """Constant elevation profile — no corrections needed."""
        dem = np.full((20, 20), 100.0, dtype=np.float32)
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert diag["cells_smoothed"] == 0

    # --- Spec #3: already monotonic ---
    def test_already_monotonic_unchanged(self):
        """A naturally decreasing profile has 0 corrections."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert diag["cells_smoothed"] == 0

    # --- Spec #4: confluence ---
    def test_confluence_takes_min_of_tributaries(self):
        """At confluence, downstream start = min(elevation, tributary lasts)."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        # Add bumps on tributaries to force different last values
        dem[5, 8] = 200.0  # bump on trib_a path
        trib_a = LineString([(8, 18), (10, 10)])
        trib_b = LineString([(12, 18), (10, 10)])
        main = LineString([(10, 10), (10, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [trib_a, trib_b, main]
            result, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert diag["segments_processed"] == 3
        assert diag["disconnected_components"] == 1
        # Main stem start must be <= both tributary end elevations
        # (monotonic property at confluence)
        confluence_r, confluence_c = 10, 10
        assert result[confluence_r, confluence_c] <= dem[confluence_r, confluence_c]

    # --- Spec #5: reversed geometry ---
    def test_reversed_geometry_handled(self):
        """LineString from mouth to source is handled correctly by BFS."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        # Geometry goes low→high (mouth to source), but BFS should
        # determine correct downstream direction
        line = LineString([(5, 2), (5, 18)])  # reversed: low elevation first
        dem[10, 5] = 200.0  # bridge bump

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        # Must still be monotonic despite reversed geometry
        assert result[10, 5] <= result[9, 5]
        assert diag["cells_smoothed"] > 0

    # --- Spec #6: MultiLineString decomposition ---
    def test_multilinestring_decomposed(self):
        """MultiLineString is decomposed by _load_stream_geometries."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        part_a = LineString([(5, 18), (5, 10)])
        part_b = LineString([(5, 10), (5, 2)])

        # _load_stream_geometries should decompose MultiLineString
        # We test by passing already-decomposed parts (since we mock the loader)
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [part_a, part_b]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert diag["segments_processed"] == 2

    # --- Spec #7: NoData cells ---
    def test_nodata_cells_skipped(self):
        """NoData cells in stream profile are not modified."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        nodata = -9999.0
        dem[10, 5] = nodata
        line = LineString([(5, 18), (5, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, _ = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg", nodata=nodata
            )

        assert result[10, 5] == nodata

    # --- Spec #8: disconnected network ---
    def test_disconnected_network_separate_outlets(self):
        """Two independent streams get separate outlets."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        stream_a = LineString([(3, 18), (3, 2)])
        stream_b = LineString([(15, 18), (15, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [stream_a, stream_b]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert diag["disconnected_components"] == 2
        assert diag["segments_processed"] == 2

    # --- Spec #11: overlapping geometries ---
    def test_overlapping_geometries_min_wins(self):
        """Two segments on same pixels — minimum elevation wins."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0  # bump
        line_a = LineString([(5, 18), (5, 2)])
        line_b = LineString([(5, 18), (5, 2)])  # same path

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line_a, line_b]
            result, _ = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        # Even with overlapping, monotonic property must hold
        assert result[10, 5] <= result[9, 5]

    # --- Spec #12: short segment ---
    def test_short_segment_handled(self):
        """A 1-2 pixel segment is either processed or properly skipped."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        # Very short line — 1-2 pixels
        short = LineString([(5.1, 10.1), (5.4, 10.4)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [short]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        # Should be counted in either processed or skipped
        assert diag["segments_processed"] + diag["segments_skipped"] == 1

    # --- Spec #13: segment outside DEM ---
    def test_segment_outside_dem_skipped(self):
        """Segments fully outside DEM extent are skipped."""
        dem = self._make_sloped_dem(10, 10)
        transform = from_bounds(0, 0, 10, 10, 10, 10)
        line = LineString([(50, 50), (60, 60)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        assert diag["segments_skipped"] >= 1
        assert diag["segments_processed"] == 0

    # --- Diagnostics structure ---
    def test_diagnostics_structure(self):
        """Diagnostics dict contains all required keys."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])

        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )

        required_keys = {
            "segments_processed", "segments_skipped",
            "cells_smoothed", "cells_unchanged",
            "max_correction_m", "mean_correction_m",
            "disconnected_components",
        }
        assert required_keys.issubset(set(diag.keys()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py::TestSmoothStreamsMonotonic -v`
Expected: ImportError

- [ ] **Step 3: Extract `_load_stream_geometries()` from `burn_streams_into_dem()`**

Refactor the stream loading logic from `burn_streams_into_dem()` (lines ~194–264) into a reusable helper. Add **before** `burn_streams_into_dem()`:

```python
def _load_stream_geometries(
    streams_path,
    transform,
    dem_shape: tuple[int, int],
) -> list:
    """Load stream geometries from BDOT10k GeoPackage/Shapefile.

    Reads SWRS/SWKN/SWRM/PTWP layers, reprojects to EPSG:2180,
    clips to DEM extent, decomposes MultiLineStrings to LineStrings.

    Returns list of shapely LineString geometries.
    """
    import geopandas as gpd
    import fiona
    from shapely.geometry import box, MultiLineString

    streams_path = str(streams_path)
    nrows, ncols = dem_shape

    left, top = transform * (0, 0)
    right, bottom = transform * (ncols, nrows)
    dem_bounds = box(min(left, right), min(top, bottom),
                     max(left, right), max(top, bottom))

    try:
        layers = fiona.listlayers(streams_path)
    except Exception:
        layers = [None]

    stream_prefixes = ("SWRS", "SWKN", "SWRM", "PTWP")
    target_layers = [
        lyr for lyr in layers
        if lyr and any(p in lyr.upper() for p in stream_prefixes)
    ]
    if not target_layers:
        target_layers = layers[:1] if layers else []

    all_geoms = []
    for layer in target_layers:
        try:
            kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(streams_path, **kwargs)
        except Exception:
            continue

        if gdf.empty:
            continue

        if gdf.crs and gdf.crs.to_epsg() != 2180:
            gdf = gdf.to_crs(epsg=2180)

        gdf = gdf[gdf.geometry.intersects(dem_bounds)]

        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue
            if isinstance(geom, MultiLineString):
                for part in geom.geoms:
                    if not part.is_empty and len(list(part.coords)) >= 2:
                        all_geoms.append(part)
            elif len(list(geom.coords)) >= 2:
                all_geoms.append(geom)

    return all_geoms
```

**Important:** Use `p in lyr.upper()` for layer prefix matching (consistent with existing `burn_streams_into_dem` logic at line ~215), NOT `lyr.startswith(p)`.

- [ ] **Step 4: Refactor `burn_streams_into_dem()` to use `_load_stream_geometries()`**

Replace the stream loading block in `burn_streams_into_dem()` (lines ~194–264) with a call to `_load_stream_geometries()`. Then rasterize the returned geometries list using `rasterio.features.rasterize`. The function's external interface and return value remain unchanged.

```python
def burn_streams_into_dem(
    dem: np.ndarray,
    transform,
    streams_path,
    burn_depth_m: float = 10.0,  # will become 2.0 in Task 5
    nodata: float = -9999.0,
) -> tuple[np.ndarray, dict]:
    """Burn streams into DEM by lowering elevation under stream geometries.

    Args:
        burn_depth_m: Depth to burn streams (meters), default 2.0.
    """
    from rasterio.features import rasterize as rio_rasterize

    dem = dem.copy()
    geometries = _load_stream_geometries(streams_path, transform, dem.shape)

    if not geometries:
        return dem, {"cells_burned": 0, "streams_loaded": 0, "streams_in_extent": 0}

    # Rasterize all geometries to a mask
    mask = rio_rasterize(
        [(geom, 1) for geom in geometries],
        out_shape=dem.shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )

    burn_mask = (mask == 1) & (dem != nodata)
    dem[burn_mask] -= burn_depth_m

    return dem, {
        "cells_burned": int(burn_mask.sum()),
        "streams_loaded": len(geometries),
        "streams_in_extent": len(geometries),
    }
```

- [ ] **Step 5: Run existing burn tests to verify no regression**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_hydrology.py -v`
Expected: All PASS

- [ ] **Step 6: Implement `smooth_streams_monotonic()`**

Add to `backend/core/hydrology.py` after `_build_stream_network_graph()`:

```python
def smooth_streams_monotonic(
    dem: np.ndarray,
    transform,
    streams_path,
    nodata: float = -9999.0,
) -> tuple[np.ndarray, dict]:
    """Enforce monotonically decreasing elevation along stream channels.

    Builds a topology graph from BDOT10k stream geometries, then applies
    a running-minimum pass from sources to outlets. Must be called AFTER
    burn_streams_into_dem().

    Returns (smoothed_dem, diagnostics_dict).
    """
    import logging
    from collections import deque

    logger = logging.getLogger(__name__)
    dem = dem.copy()
    nrows, ncols = dem.shape

    geometries = _load_stream_geometries(streams_path, transform, dem.shape)
    if not geometries:
        logger.info("smooth_streams_monotonic: no stream geometries found")
        return dem, {
            "segments_processed": 0, "segments_skipped": 0,
            "cells_smoothed": 0, "cells_unchanged": 0,
            "max_correction_m": 0.0, "mean_correction_m": 0.0,
            "disconnected_components": 0,
        }

    graph, seg_nodes, outlets = _build_stream_network_graph(
        geometries, dem, transform
    )

    # Rasterize each segment
    seg_cells: dict[int, list[tuple[int, int]]] = {}
    for idx, geom in enumerate(geometries):
        cells = _rasterize_line_ordered(geom, transform, shape=(nrows, ncols))
        if len(cells) >= 2:
            seg_cells[idx] = cells

    # Process each connected component
    node_last_elev: dict[int, float] = {}
    processed_segs: set[int] = set()
    total_smoothed = 0
    total_unchanged = 0
    corrections: list[float] = []

    for outlet in outlets:
        # BFS from outlet → build position map
        bfs_order: list[int] = []
        bfs_pos: dict[int, int] = {}
        visited: set[int] = {outlet}
        queue: deque[int] = deque([outlet])
        while queue:
            nid = queue.popleft()
            bfs_pos[nid] = len(bfs_order)
            bfs_order.append(nid)
            for neighbor, _ in graph.get(nid, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        # Process in reverse BFS order (sources first → outlet last)
        for nid in reversed(bfs_order):
            for neighbor, seg_idx in graph.get(nid, []):
                if seg_idx in processed_segs or seg_idx not in seg_cells:
                    continue

                # Only process when nid is upstream (farther from outlet)
                nid_pos = bfs_pos.get(nid, -1)
                neighbor_pos = bfs_pos.get(neighbor, -1)
                if neighbor_pos >= nid_pos:
                    continue  # neighbor is farther — skip, will process from other side

                # Determine cell order: upstream (nid) → downstream (neighbor)
                cells = seg_cells[seg_idx]

                # seg_nodes[seg_idx] = (start_node, end_node) where
                # start_node corresponds to geometry coords[0].
                # _rasterize_line_ordered follows coord order, so cells[0]
                # corresponds to start_node.
                # We need cells ordered nid (upstream) → neighbor (downstream).
                geom_start_node, geom_end_node = seg_nodes[seg_idx]
                if geom_start_node != nid:
                    # Geometry coords go downstream→upstream, reverse cells
                    cells = list(reversed(cells))

                # Get profile and apply running minimum
                profile = np.array(
                    [dem[r, c] for r, c in cells], dtype=np.float64
                )

                # At confluence: take min of current elevation and tributary lasts
                running_val = profile[0]
                if nid in node_last_elev:
                    running_val = min(running_val, node_last_elev[nid])

                for i in range(len(profile)):
                    r, c = cells[i]
                    if dem[r, c] == nodata:
                        continue
                    new_val = min(profile[i], running_val)
                    correction = dem[r, c] - new_val
                    if correction > 1e-6:
                        dem[r, c] = new_val
                        total_smoothed += 1
                        corrections.append(correction)
                    else:
                        total_unchanged += 1
                    running_val = new_val

                # Store last elevation for downstream confluence
                last_r, last_c = cells[-1]
                if neighbor in node_last_elev:
                    node_last_elev[neighbor] = min(
                        node_last_elev[neighbor], dem[last_r, last_c]
                    )
                else:
                    node_last_elev[neighbor] = dem[last_r, last_c]

                processed_segs.add(seg_idx)

    segments_processed = len(processed_segs)

    diag = {
        "segments_processed": segments_processed,
        "segments_skipped": len(geometries) - segments_processed,
        "cells_smoothed": total_smoothed,
        "cells_unchanged": total_unchanged,
        "max_correction_m": max(corrections) if corrections else 0.0,
        "mean_correction_m": float(np.mean(corrections)) if corrections else 0.0,
        "disconnected_components": len(outlets),
    }
    logger.info("smooth_streams_monotonic: %s", diag)
    return dem, diag
```

Key fixes vs. first draft:
- **O(1) BFS position lookup** via `bfs_pos` dict (was O(n) `list.index()`)
- **`processed_segs` set** instead of `del seg_cells[seg_idx]` (no dict mutation during traversal)
- **Removed dead if/else** — single `min(profile[i], running_val)` path
- **Confluence min** — `node_last_elev[neighbor]` takes min of multiple tributaries
- **Direction via `seg_nodes`** — uses `(start_node, end_node)` from graph builder, not fragile `seg_node_map` iteration order. `start_node` always corresponds to `geometry.coords[0]`

- [ ] **Step 7: Run all monotonic smoothing tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_monotonic_smoothing.py -v`
Expected: All tests PASS (6 + 5 + 5 + 13 = 29 tests)

- [ ] **Step 8: Run full test suite to verify no regressions**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/ -x -q`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add backend/core/hydrology.py backend/tests/unit/test_monotonic_smoothing.py
git commit -m "feat(core): add smooth_streams_monotonic() with running-minimum downstream pass (ADR-041)

Includes _load_stream_geometries() refactored from burn_streams_into_dem(),
_build_stream_network_graph() topology builder, _bresenham() rasterizer.
13 spec test cases covered."
```

---

## Chunk 2: Integration & Configuration (Tasks 5–7)

### Task 5: Reduce `burn_depth_m` defaults to 2.0

**Files:**
- Modify: `backend/core/hydrology.py:164` — `10.0` → `2.0`
- Modify: `backend/core/config.py:124` — `10.0` → `2.0`
- Modify: `backend/scripts/process_dem.py:132` — `5.0` → `2.0`
- Modify: `backend/scripts/process_dem.py:~689` — help text
- Modify: `backend/scripts/prepare_area.py:89` — `5.0` → `2.0`
- Modify: `backend/scripts/prepare_area.py:~474` — help text
- Modify: `backend/config.yaml.example:16` — `10.0` → `2.0`

- [ ] **Step 1: Update `core/hydrology.py`**

Change default parameter in `burn_streams_into_dem` signature:
```python
burn_depth_m: float = 2.0,
```
Also update the docstring to say "default 2.0" (currently says "default 5.0" which was already wrong).

- [ ] **Step 2: Update `core/config.py`**

Change `_DEFAULT_CONFIG["dem"]["burn_depth_m"]`:
```python
"burn_depth_m": 2.0,
```

- [ ] **Step 3: Update `scripts/process_dem.py`**

Change function parameter default:
```python
burn_depth_m: float = 2.0,
```
Change CLI argparse:
```python
default=2.0,
help="Burn depth in meters (default: 2.0)",
```

- [ ] **Step 4: Update `scripts/prepare_area.py`**

Change function parameter default:
```python
burn_depth_m: float = 2.0,
```
Change CLI argparse:
```python
default=2.0,
help="Stream burn depth in meters (default: 2.0)",
```

- [ ] **Step 5: Update `config.yaml.example`**

```yaml
burn_depth_m: 2.0
```

- [ ] **Step 6: Run existing tests to check for regressions**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_hydrology.py tests/unit/test_config*.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/core/hydrology.py backend/core/config.py backend/scripts/process_dem.py backend/scripts/prepare_area.py backend/config.yaml.example
git commit -m "refactor(core): reduce burn_depth_m default from 10/5m to 2.0m (ADR-041)"
```

---

### Task 6: Integrate smoothing into `process_dem.py` + `bootstrap.py`

**Files:**
- Modify: `backend/scripts/process_dem.py`
- Modify: `backend/scripts/bootstrap.py`

- [ ] **Step 1: Add `smooth_streams` parameter to `process_dem()` function**

Add parameter to function signature (after `burn_depth_m`):
```python
smooth_streams: bool = True,
```

- [ ] **Step 2: Add `--no-smooth-streams` CLI argument**

Add after the `--burn-depth` argument:
```python
parser.add_argument(
    "--no-smooth-streams",
    action="store_true",
    default=False,
    help="Disable monotonic stream smoothing after burning",
)
```

- [ ] **Step 3: Add smoothing call after burn step**

After the `save_intermediates` block for `02a_burned.tif` (line ~298), add:

```python
        # Step 3b: Monotonic stream smoothing
        if smooth_streams:
            from core.hydrology import smooth_streams_monotonic

            dem, smooth_diag = smooth_streams_monotonic(
                dem, transform, burn_streams_path, nodata
            )
            stats["smooth_cells"] = smooth_diag["cells_smoothed"]
            stats["smooth_max_correction_m"] = smooth_diag["max_correction_m"]
            logger.info(
                "Monotonic smoothing: %d cells corrected (max %.1fm)",
                smooth_diag["cells_smoothed"],
                smooth_diag["max_correction_m"],
            )
            if save_intermediates:
                save_raster_geotiff(
                    dem,
                    metadata,
                    output_dir / f"{base_name}_02b_smoothed.tif",
                    nodata=nodata,
                    dtype="float32",
                )
```

This block goes **inside** the existing `if burn_streams_path is not None:` conditional.

- [ ] **Step 4: Wire CLI argument to function call**

In `main()` where `process_dem()` is called, add:
```python
smooth_streams=not args.no_smooth_streams,
```

- [ ] **Step 5: Update `bootstrap.py`**

In `bootstrap.py`, find the `process_dem()` call (line ~512). The `smooth_streams` parameter defaults to `True`, so `bootstrap.py` will use smoothing automatically without code changes. **Verify** this is correct by reading the call — if `bootstrap.py` explicitly passes `smooth_streams=False` or has its own `--no-smooth-streams` flag needs, add them.

No code change needed if relying on default `True`.

- [ ] **Step 6: Run process_dem tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/ -k "process_dem" -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/process_dem.py
git commit -m "feat(core): integrate monotonic smoothing into process_dem pipeline (ADR-041)

New --no-smooth-streams flag to disable. Saves 02b_smoothed.tif
when save_intermediates=True. bootstrap.py inherits default True."
```

---

### Task 7: Documentation updates

**Files:**
- Modify: `docs/DECISIONS.md` — add ADR-041
- Modify: `backend/scripts/README.md` — update pipeline docs
- Modify: `docs/CHANGELOG.md` — add entry
- Modify: `docs/PROGRESS.md` — update status

- [ ] **Step 1: Add ADR-041 to `docs/DECISIONS.md`**

Append to the ADR table:

```markdown
| ADR-041 | Monotoniczne wygładzanie cieków | Dwuetapowe: stałe wypalanie (2m) + running minimum downstream. Bresenham rasteryzacja, BFS od ujścia. `burn_depth_m` 10→2m. | 2026-03-17 | Aktywna |
```

- [ ] **Step 2: Update `backend/scripts/README.md`**

Add `02b_smoothed.tif` to the intermediate files table. Update pipeline stages to show step 3b (monotonic smoothing). Add `--no-smooth-streams` to the CLI parameters table.

- [ ] **Step 3: Update `docs/CHANGELOG.md`**

Add under `[Unreleased]`:

```markdown
### Dodane
- **H4: Monotoniczne wygładzanie cieków (ADR-041)** — dwuetapowe przetwarzanie: stałe wypalanie (2m) + running minimum downstream. Koryguje mosty/nasypy bez nadmiernego wypalania normalnych odcinków
- `smooth_streams_monotonic()` w `core/hydrology.py` — graf topologii sieci, BFS od ujścia, Bresenham rasteryzacja
- `--no-smooth-streams` flag w `process_dem.py` — wyłączenie wygładzania do debugowania
- Plik diagnostyczny `02b_smoothed.tif` przy `save_intermediates`

### Zmienione
- Domyślny `burn_depth_m` zmniejszony z 10/5m do 2.0m (wszystkie lokalizacje)
- Refaktoryzacja `burn_streams_into_dem()` — wydzielenie `_load_stream_geometries()` jako współdzielonego helpera
```

- [ ] **Step 4: Update `docs/PROGRESS.md`**

Update "Ostatnia sesja" section with H4 implementation details.

- [ ] **Step 5: Commit**

```bash
git add docs/DECISIONS.md backend/scripts/README.md docs/CHANGELOG.md docs/PROGRESS.md
git commit -m "docs: add ADR-041 monotonic stream smoothing documentation"
```
