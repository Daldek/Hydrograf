"""Timing of the dynamic vector tile endpoints at the levels the map asks (Tile load).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 2, Risks „Tile load”: at one scale
MapLibre asks a vector tile one level lower than the Leaflet map did, each tile four
times the area, and the endpoints of ``api/endpoints/tiles.py`` answer them with
``ST_AsMVT`` and no simplification at query time. For each tiled vector layer the test
times its endpoint over the data of the database of ``DATABASE_URL`` (a deployment's;
the test loads no data of its own) at the layer's first level and at 1:10 000, against
the level one higher over the same ground, which the Leaflet map asked at the same
scale: the p95 of the map's level stays within four times the other's and under the 15 s
after which nginx cuts the tile proxy (``docker/nginx.conf``). A layer without data in
the database is skipped. The ``benchmark`` marker is no check of CI: the numbers, which
``-s`` prints, go to the step's Results.

Run: cd backend && uv run pytest tests/performance/test_tile_load.py -m benchmark -s
"""

import math
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from api.endpoints.tiles import get_landcover_tile, get_sewer_mvt, get_streams_mvt
from tests.conftest_db import requires_db

pytest_plugins = ["tests.conftest_db"]

Tile = tuple[int, int, int]
Extent = tuple[float, float, float, float]
Ask = Callable[[Session, int, int, int], object]

# nginx's proxy_read_timeout of location /api/tiles/
PROXY_TIMEOUT_MS = 15_000
# The map's tile holds four of the level above
BUDGET_FACTOR = 4
# The map's first levels (js/map.js: tiles_metadata.json of generate_tiles.py for the
# streams, 13 for the threshold of 1000 m²; the land cover's and the sewer's layers)
STREAMS_FIRST_LEVEL = 7
STREAMS_FIRST_LEVELS = {1000: 13}
LANDCOVER_FIRST_LEVEL = 7
SEWER_FIRST_LEVEL = 9
# A view at 1:10 000 is at zoom 14.77 of 512-px tiles: the map asks level 14
LEVEL_AT_10000 = 14
# How many tiles of the map's level a case times, spread over the data's extent (each
# with its four tiles of the level above), and how often each is asked
MAX_TILES = 16
REPEAT = 3
WORLD_M = 20037508.3427892

# The data's extent in EPSG:3857 [west, south, east, north] (the tables are EPSG:2180)
EXTENT = """
    SELECT ST_XMin(box), ST_YMin(box), ST_XMax(box), ST_YMax(box)
    FROM (SELECT ST_Transform(ST_SetSRID(ST_Extent(geom)::geometry, 2180), 3857) AS box
          FROM ({rows}) AS data) AS extent
"""
STREAMS_ROWS = "SELECT geom FROM stream_network WHERE threshold_m2 = :threshold"
LANDCOVER_ROWS = "SELECT geom FROM land_cover"
SEWER_ROWS = "SELECT geom FROM sewer_network UNION ALL SELECT geom FROM sewer_nodes"


def _extent(
    db: Session, rows: str, params: dict[str, Any] | None = None
) -> Extent | None:
    """The EPSG:3857 extent of the rows' geometries, None without any."""
    found = db.execute(text(EXTENT.format(rows=rows)), params or {}).fetchone()
    if found is None or found[0] is None:
        return None
    west, south, east, north = (float(value) for value in found)
    return west, south, east, north


def _tiles_over(extent: Extent, level: int) -> list[Tile]:
    """The tiles of a level over an EPSG:3857 extent, MAX_TILES at most, spread."""
    west, south, east, north = extent
    count: int = 2**level
    size = 2 * WORLD_M / count
    last = count - 1

    def index(metres: float) -> int:
        return min(last, max(0, math.floor(metres / size)))

    tiles = [
        (level, x, y)
        for x in range(index(west + WORLD_M), index(east + WORLD_M) + 1)
        for y in range(index(WORLD_M - north), index(WORLD_M - south) + 1)
    ]
    return tiles[:: math.ceil(len(tiles) / MAX_TILES)]


def _children(tiles: list[Tile]) -> list[Tile]:
    """The four tiles of the level above each tile: the same ground."""
    return [
        (z + 1, 2 * x + dx, 2 * y + dy)
        for z, x, y in tiles
        for dx in (0, 1)
        for dy in (0, 1)
    ]


def _p95_ms(db: Session, ask: Ask, tiles: list[Tile]) -> float:
    """The 95th percentile of the endpoint's time over the tiles [ms]."""
    times = []
    for _ in range(REPEAT):
        for z, x, y in tiles:
            start = time.perf_counter()
            ask(db, z, x, y)
            times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return times[min(len(times) - 1, int(len(times) * 0.95))]


def _assert_within_budget(
    db: Session, name: str, ask: Ask, extent: Extent, level: int
) -> None:
    """The p95 at the map's level: within four times the level above's, under 15 s."""
    tiles = _tiles_over(extent, level)
    above = _children(tiles)
    for z, x, y in tiles + above:  # a first pass, untimed: plans and caches warm
        ask(db, z, x, y)
    ours = _p95_ms(db, ask, tiles)
    theirs = _p95_ms(db, ask, above)
    print(
        f"\n  {name}: level {level} p95 {ours:.1f} ms ({len(tiles)} tiles), "
        f"level {level + 1} p95 {theirs:.1f} ms ({len(above)} tiles), "
        f"{ours / theirs:.2f}×"
    )
    assert ours <= BUDGET_FACTOR * theirs, (name, level, ours, theirs)
    assert ours < PROXY_TIMEOUT_MS, (name, level, ours)


@pytest.fixture
def db(db_engine: Engine) -> Iterator[Session]:
    """A session of the database's own data, rolled back at the end."""
    with Session(db_engine) as session:
        yield session
        session.rollback()


@requires_db
@pytest.mark.benchmark
@pytest.mark.db
@pytest.mark.parametrize("at_10000", [False, True], ids=["first-level", "1:10000"])
def test_streams_tiles_within_budget(db: Session, at_10000: bool) -> None:
    thresholds = [
        int(row[0])
        for row in db.execute(
            text("SELECT DISTINCT threshold_m2 FROM stream_network ORDER BY 1")
        )
    ]
    if not thresholds:
        pytest.skip("no streams in the database")
    for threshold in thresholds:
        extent = _extent(db, STREAMS_ROWS, {"threshold": threshold})
        assert extent is not None
        first = STREAMS_FIRST_LEVELS.get(threshold, STREAMS_FIRST_LEVEL)

        def ask(session: Session, z: int, x: int, y: int, t: int = threshold) -> object:
            return get_streams_mvt(z, x, y, threshold=t, db=session)

        level = LEVEL_AT_10000 if at_10000 else first
        _assert_within_budget(db, f"streams {threshold} m²", ask, extent, level)


@requires_db
@pytest.mark.benchmark
@pytest.mark.db
@pytest.mark.parametrize(
    "level", [LANDCOVER_FIRST_LEVEL, LEVEL_AT_10000], ids=["first-level", "1:10000"]
)
def test_landcover_tiles_within_budget(db: Session, level: int) -> None:
    extent = _extent(db, LANDCOVER_ROWS)
    if extent is None:
        pytest.skip("no land cover in the database")

    def ask(session: Session, z: int, x: int, y: int) -> object:
        return get_landcover_tile(z, x, y, db=session)

    _assert_within_budget(db, "land cover", ask, extent, level)


@requires_db
@pytest.mark.benchmark
@pytest.mark.db
@pytest.mark.parametrize(
    "level", [SEWER_FIRST_LEVEL, LEVEL_AT_10000], ids=["first-level", "1:10000"]
)
def test_sewer_tiles_within_budget(db: Session, level: int) -> None:
    extent = _extent(db, SEWER_ROWS)
    if extent is None:
        pytest.skip("no sewer in the database")

    def ask(session: Session, z: int, x: int, y: int) -> object:
        return get_sewer_mvt(z, x, y, db=session)

    _assert_within_budget(db, "sewer", ask, extent, level)
