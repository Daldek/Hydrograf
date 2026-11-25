"""The site of the browser tests: a synthetic catchment, the API and the pages.

``serve_site`` runs the DEM of the network tests (``tests.fixtures.pipeline_run``,
``river_network_dem``: a main river along column 85 with tributaries, here with a pit
dug for the depressions) through the pipeline into a private migrated database
(``tests.scratch_db``) and a temporary data root, as a bootstrap leaves them:

* the database: the stream networks and sub-catchments of ``THRESHOLDS_M2`` from
  ``process_dem``, the land cover and soil groups of ``land_cover_layout`` and
  ``soil_layout``, the BDOT10k lines along the main river (their flags matched as
  ``process_dem`` matches them), the depressions, and the sewer of
  ``tests/integration/test_sewer_pipeline.py`` (its Y of two inlets, a junction and an
  outlet, placed on this grid);
* ``/data/`` (FRONTEND_DATA_DIR): the DEM's image and, where GDAL's ``gdal2tiles.py``
  is present, its tiles with their metadata; the depressions' image; the BDOT10k lakes
  and streams and the soil groups as GeoJSON; and the results manifest with one result,
  a PNG pyramid of two levels (``RESULT_ZOOMS``);
* ``/tiles/``: the streams' tiles and ``tiles_metadata.json`` of ``generate_tiles.py``
  where tippecanoe is present; without it the map asks the dynamic endpoint.

The API runs under uvicorn on that database and data root (the admin key
``ADMIN_KEY``, no request limit to speak of), and a server of the tests' own serves
``frontend/`` and the data as ``docker/nginx.conf`` routes them: the pages through the
API (``X-Accel-Redirect``) with the two ``Content-Security-Policy`` values read from
that file, ``/api/`` proxied to the API.
"""

import http.client
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core import database
from core.db_bulk import update_stream_real_flags_all
from core.sewer_service import build_sewer_graph, insert_sewer_data
from core.sewer_topology import parse_sewer_topology
from scripts.bootstrap import HSG_MAP_TOLERANCE_M, export_bdot_geojson
from scripts.generate_dem_overlay import generate_overlay as dem_overlay
from scripts.generate_dem_tiles import generate_tiles as dem_tiles
from scripts.generate_depressions import (
    compute_depressions,
    generate_overlay,
    insert_depressions,
)
from scripts.process_dem import process_dem
from tests.fixtures.pipeline_run import (
    NETWORK_CELL_M,
    NETWORK_SHAPE,
    NETWORK_X0,
    NETWORK_Y1,
    land_cover_layout,
    river_network_dem,
    soil_layout,
)
from tests.integration.test_sewer_pipeline import SEWER_NODES
from tests.scratch_db import scratch_database

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
FRONTEND = REPOSITORY / "frontend"
NGINX_CONF = REPOSITORY / "docker" / "nginx.conf"

# The thresholds [m²] of the stream networks: 1000 is first drawn closer than the
# others (generate_tiles.THRESHOLD_MIN_ZOOM), 100 000 is the map's default
THRESHOLDS_M2 = (1_000, 10_000, 100_000)
# The pit of the depressions: (first row, end row), (first column, end column) of the
# cells dug PIT_DEPTH_M deep, on the eastern valley side north of T3 (row 75)
PIT_ROWS, PIT_COLS = (30, 34), (120, 124)
PIT_DEPTH_M = 8.0
MAIN_RIVER_COL = 85
# BDOT10k lines along the main river, (first row, last row) of the cells they join
BDOT_RIVER_ROWS = ((110, 170), (172, 230))
# A ditch (OT_SWRM_L) along row 190, east of the main river
BDOT_DITCH = ((190, 100), (190, 160))
# The result of an external analysis: its tile levels and its cells, (first row,
# end row) and (first column, end column), along the main river's lower course
RESULT_ID = "e2e-glebokosc"
RESULT_TITLE = "Głębokość wody (test)"
RESULT_ZOOMS = (14, 15)
RESULT_ROWS, RESULT_COLS = (120, 215), (70, 100)
RESULT_COLOR = (49, 130, 189, 255)
ADMIN_KEY = "klucz-e2e-hydrografu"
_TO_WGS84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
_READY_TIMEOUT_S = 180.0


@dataclass(frozen=True)
class Policies:
    """The ``Content-Security-Policy`` values of ``docker/nginx.conf``."""

    page: str
    admin: str


@dataclass(frozen=True)
class Site:
    """The served site of the browser tests.

    Attributes
    ----------
    base : str
        The pages, e.g. ``http://127.0.0.1:41234`` (the static server).
    api : str
        The API under uvicorn.
    root : Path
        The temporary data root.
    data_dir : Path
        FRONTEND_DATA_DIR, served under ``/data/``.
    tiles_dir : Path
        Served under ``/tiles/``.
    tiles_meta : dict or None
        ``tiles_metadata.json`` of the pre-generated streams' tiles; None when
        tippecanoe was missing and the map asks the dynamic endpoint.
    policies : Policies
        The CSP values the pages are sent with.
    database_url : str
        The private database.
    """

    base: str
    api: str
    root: Path
    data_dir: Path
    tiles_dir: Path
    tiles_meta: dict[str, Any] | None
    policies: Policies
    database_url: str

    def cell_lnglat(self, row: float, col: float) -> tuple[float, float]:
        """The centre of a cell of the DEM in degrees, (longitude, latitude)."""
        return cell_lnglat(row, col)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """The DEM's extent in degrees: west, south, east, north."""
        rows, cols = NETWORK_SHAPE
        corners = [
            cell_lnglat(r, c) for r in (-0.5, rows - 0.5) for c in (-0.5, cols - 0.5)
        ]
        lngs = [lng for lng, _ in corners]
        lats = [lat for _, lat in corners]
        return min(lngs), min(lats), max(lngs), max(lats)


def cell_xy(row: float, col: float) -> tuple[float, float]:
    """The centre of a cell of the DEM, EPSG:2180 [m]."""
    return (
        NETWORK_X0 + (col + 0.5) * NETWORK_CELL_M,
        NETWORK_Y1 - (row + 0.5) * NETWORK_CELL_M,
    )


def cell_lnglat(row: float, col: float) -> tuple[float, float]:
    """The centre of a cell of the DEM in degrees, (longitude, latitude)."""
    lng, lat = _TO_WGS84.transform(*cell_xy(row, col))
    return float(lng), float(lat)


def nginx_policies(conf: Path = NGINX_CONF) -> Policies:
    """Read the two CSP values of nginx's configuration.

    The page's is the server's own ``add_header``; the admin page's is the one of
    the location ``^~ /_site/admin/``, its file under the API's X-Accel-Redirect.
    """
    found: dict[str, str] = {}
    blocks: list[str] = []
    for line in conf.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        csp = re.match(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', stripped)
        if csp:
            found[blocks[-1]] = csp.group(1)
        if stripped.endswith("{"):
            blocks.append(stripped[:-1].strip())
        elif stripped == "}":
            blocks.pop()
    return Policies(page=found["server"], admin=found["location ^~ /_site/admin/"])


# --- the data ------------------------------------------------------------------------


def e2e_dem() -> np.ndarray:
    """The DEM of the network tests with the pit of the depressions dug in it."""
    dem = river_network_dem()
    dem[PIT_ROWS[0] : PIT_ROWS[1], PIT_COLS[0] : PIT_COLS[1]] -= PIT_DEPTH_M
    return dem


def _river_line(first_row: int, last_row: int) -> LineString:
    return LineString(
        [cell_xy(first_row, MAIN_RIVER_COL), cell_xy(last_row, MAIN_RIVER_COL)]
    )


def _grid_extent() -> tuple[float, float]:
    """Width and height of the grid [m]."""
    rows, cols = NETWORK_SHAPE
    return cols * NETWORK_CELL_M, rows * NETWORK_CELL_M


def _insert_layers(engine: Engine) -> None:
    """Insert the land cover, the soil groups and the BDOT10k lines."""
    width_m, height_m = _grid_extent()
    with engine.begin() as connection:
        for category, bdot_class, imperviousness, geometry in land_cover_layout(
            NETWORK_X0, NETWORK_Y1, width_m, height_m
        ):
            connection.execute(
                text(
                    "INSERT INTO land_cover (geom, category, imperviousness, "
                    "bdot_class) VALUES (ST_Multi(ST_GeomFromWKB(:geom, 2180)), "
                    ":category, :imperviousness, :bdot_class)"
                ),
                {
                    "geom": geometry.wkb,
                    "category": category,
                    "imperviousness": imperviousness,
                    "bdot_class": bdot_class,
                },
            )
        for group, geometry in soil_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m):
            connection.execute(
                text(
                    "INSERT INTO soil_hsg (geom, hsg_group, area_m2) VALUES "
                    "(ST_Multi(ST_GeomFromWKB(:geom, 2180)), :group, :area_m2)"
                ),
                {"geom": geometry.wkb, "group": group, "area_m2": geometry.area},
            )
        for rows in BDOT_RIVER_ROWS:
            line = _river_line(*rows)
            connection.execute(
                text(
                    "INSERT INTO bdot_streams (geom, layer_type, length_m) VALUES "
                    "(ST_GeomFromWKB(:geom, 2180), 'SWRS', :length_m)"
                ),
                {"geom": line.wkb, "length_m": line.length},
            )


def _bdot_geojson(data_dir: Path, work_dir: Path) -> None:
    """``bdot_lakes.geojson`` and ``bdot_streams.geojson`` as a bootstrap exports them.

    The pond of the land cover is the lake; the BDOT10k lines along the main river
    are rivers (OT_SWRS_L) and a ditch (OT_SWRM_L) lies east of it.
    """
    width_m, height_m = _grid_extent()
    pond = next(
        geometry
        for category, _, _, geometry in land_cover_layout(
            NETWORK_X0, NETWORK_Y1, width_m, height_m
        )
        if category == "woda"
    )
    gpkg = work_dir / "bdot10k_hydro.gpkg"
    gpd.GeoDataFrame({"geometry": [pond]}, crs="EPSG:2180").to_file(
        gpkg, layer="OT_PTWP_A", driver="GPKG"
    )
    gpd.GeoDataFrame(
        {"geometry": [_river_line(*rows) for rows in BDOT_RIVER_ROWS]}, crs="EPSG:2180"
    ).to_file(gpkg, layer="OT_SWRS_L", driver="GPKG")
    gpd.GeoDataFrame(
        {"geometry": [LineString([cell_xy(*end) for end in BDOT_DITCH])]},
        crs="EPSG:2180",
    ).to_file(gpkg, layer="OT_SWRM_L", driver="GPKG")
    export_bdot_geojson(gpkg, data_dir)


def _hsg_geojson(engine: Engine, data_dir: Path) -> None:
    """``soil_hsg.geojson`` by the query of a bootstrap's step 6."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT hsg_group, ST_AsGeoJSON(ST_Transform("
                "ST_SimplifyPreserveTopology(geom, :tolerance), 4326), 6) "
                "AS geojson, area_m2 FROM soil_hsg"
            ),
            {"tolerance": HSG_MAP_TOLERANCE_M},
        ).fetchall()
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row.geojson),
            "properties": {
                "hsg_group": row.hsg_group,
                "area_m2": round(row.area_m2, 1),
            },
        }
        for row in rows
    ]
    (data_dir / "soil_hsg.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _insert_sewer() -> None:
    """The Y of ``test_sewer_pipeline.py``: two inlets, a junction and an outlet."""
    roles = {"inlet_a": "inlet", "inlet_b": "inlet", "junction": "junction"}
    downstream = {"inlet_a": "junction", "inlet_b": "junction", "junction": "outlet"}
    names = list(SEWER_NODES)
    points = gpd.GeoDataFrame(
        {
            "id": names,
            "role": [roles.get(name, "outlet") for name in names],
            "downstream_id": [downstream.get(name) for name in names],
            "geometry": [Point(cell_xy(*SEWER_NODES[name])) for name in names],
        },
        crs="EPSG:2180",
    )
    topology = parse_sewer_topology(
        points,
        None,
        {"node_id": "id", "node_role": "role", "downstream_id": "downstream_id"},
        {"inlet": "inlet", "outlet": "outlet", "junction": "junction"},
    )
    graph = build_sewer_graph(topology)
    with database.get_db_session() as db:
        insert_sewer_data(graph, db, source_file="e2e")
        db.commit()


def _tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """West, south, east, north of a web-mercator tile in degrees."""
    n = 2**z

    def lat(row: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))

    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def _tile_of(z: int, lng: float, lat: float) -> tuple[int, int]:
    n = 2**z
    x = int((lng + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def result_bounds() -> tuple[float, float, float, float]:
    """The result's extent in degrees: west, south, east, north."""
    corners = [
        cell_lnglat(r, c)
        for r in (RESULT_ROWS[0] - 0.5, RESULT_ROWS[1] - 0.5)
        for c in (RESULT_COLS[0] - 0.5, RESULT_COLS[1] - 0.5)
    ]
    return (
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        max(c[0] for c in corners),
        max(c[1] for c in corners),
    )


def _result_pyramid(data_dir: Path) -> None:
    """The results manifest and its result: RESULT_COLOR over its extent, two levels."""
    west, south, east, north = result_bounds()
    folder = data_dir / "results" / RESULT_ID
    for z in RESULT_ZOOMS:
        x0, y0 = _tile_of(z, west, north)
        x1, y1 = _tile_of(z, east, south)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                tile_w, _, tile_e, _ = _tile_bounds(z, x, y)
                lngs = tile_w + (np.arange(256) + 0.5) / 256 * (tile_e - tile_w)
                rows = np.arange(256) + 0.5
                merc = math.pi * (1 - 2 * (y + rows / 256) / 2**z)
                lats = np.degrees(np.arctan(np.sinh(merc)))
                inside = ((lngs >= west) & (lngs <= east))[None, :] & (
                    (lats >= south) & (lats <= north)
                )[:, None]
                rgba = np.zeros((256, 256, 4), dtype=np.uint8)
                rgba[inside] = RESULT_COLOR
                path = folder / str(z) / str(x) / f"{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgba, mode="RGBA").save(path)
    manifest = {
        "schema": "hydrograf-results/1",
        "results": [
            {
                "id": RESULT_ID,
                "kind": "raster_tiles",
                "title": RESULT_TITLE,
                "tiles": f"/data/results/{RESULT_ID}/{{z}}/{{x}}/{{y}}.png",
                "bounds": [west, south, east, north],
                "min_zoom": RESULT_ZOOMS[0],
                "max_zoom": RESULT_ZOOMS[-1],
                "opacity": 0.8,
                "legend": {
                    "title": "Głębokość wody",
                    "unit": "m",
                    "classes": [{"label": "> 0", "color": "#3182bd"}],
                },
                "description": "Wynik testowy: jedna barwa nad dolnym biegiem cieku.",
                "source": "Testy przeglądarkowe Hydrografu",
            }
        ],
    }
    (data_dir / "results" / "index.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


@contextmanager
def _bound_database(url: str) -> Iterator[Engine]:
    """Bind ``core.database`` to the database ``url`` for the pipeline here."""
    bound = create_engine(url)
    previous_engine = database._engine
    previous_bind = database.SessionLocal.kw.get("bind")
    database._engine = bound
    database.SessionLocal.configure(bind=bound)
    try:
        yield bound
    finally:
        database._engine = previous_engine
        database.SessionLocal.configure(bind=previous_bind)
        bound.dispose()


def build_data(url: str, root: Path) -> dict[str, Any] | None:
    """Run the pipeline into the database ``url`` and the data root ``root``.

    Returns ``tiles_metadata.json`` of the streams' tiles, or None without tippecanoe.
    """
    nmt_dir = root / "nmt"
    data_dir = root / "frontend-data"
    tiles_dir = root / "frontend-tiles"
    for directory in (nmt_dir, data_dir, tiles_dir, root / "data", root / "state"):
        directory.mkdir(parents=True, exist_ok=True)
    dem = e2e_dem()
    dem_path = nmt_dir / "dem_mosaic.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=dem.shape[0],
        width=dem.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(NETWORK_X0, NETWORK_Y1, NETWORK_CELL_M, NETWORK_CELL_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem, 1)

    with _bound_database(url) as engine:
        _insert_layers(engine)
        process_dem(
            dem_path,
            save_intermediates=True,
            output_dir=nmt_dir,
            clear_existing=True,
            thresholds=list(THRESHOLDS_M2),
        )
        with database.get_db_session() as db:
            update_stream_real_flags_all(db, list(THRESHOLDS_M2))
        scan = compute_depressions(
            str(nmt_dir / "dem_mosaic_01_dem.tif"),
            str(nmt_dir / "dem_mosaic_02_filled.tif"),
        )
        with database.get_db_session() as db:
            insert_depressions(db, scan)
        generate_overlay(
            scan.overview,
            str(data_dir / "depressions.png"),
            str(data_dir / "depressions.json"),
        )
        _insert_sewer()
        _hsg_geojson(engine, data_dir)

    dem_overlay(
        input_path=str(dem_path),
        output_png=str(data_dir / "dem.png"),
        output_meta=str(data_dir / "dem.json"),
        source_crs="EPSG:2180",
    )
    if shutil.which("gdal2tiles.py"):
        dem_tiles(
            input_path=str(dem_path),
            output_dir=str(data_dir / "dem_tiles"),
            output_meta=str(data_dir / "dem_tiles.json"),
            source_crs="EPSG:2180",
            min_zoom=8,
            max_zoom=16,
            processes=1,
            work_dir=str(nmt_dir),
        )
    _bdot_geojson(data_dir, nmt_dir)
    _result_pyramid(data_dir)

    if not shutil.which("tippecanoe"):
        return None
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.generate_tiles",
            "--output-dir",
            str(tiles_dir),
        ],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )
    meta: dict[str, Any] = json.loads(
        (tiles_dir / "tiles_metadata.json").read_text(encoding="utf-8")
    )
    return meta


# --- the servers ---------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@contextmanager
def _api(url: str, root: Path) -> Iterator[str]:
    """Run the API under uvicorn on the database ``url`` and the data root."""
    port = _free_port()
    log_path = root / "uvicorn.log"
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "DEM_DIR": str(root / "nmt"),
        "FRONTEND_DATA_DIR": str(root / "frontend-data"),
        "HYDROGRAF_DATA_DIR": str(root / "data"),
        "HYDROGRAF_STATE_DIR": str(root / "state"),
        "ADMIN_API_KEY": ADMIN_KEY,
        "ADMIN_API_KEY_FILE": "",
        "HYDROGRAF_REQUEST_LIMIT": "1000000",
        "HYDROGRAF_GUI": "",
        "NOGAT_CONFIG": "",
        "PYTHONUNBUFFERED": "1",
    }
    base = f"http://127.0.0.1:{port}"
    with open(log_path, "wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=BACKEND,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_ready(base, process, log_path)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _wait_ready(base: str, process: subprocess.Popen[bytes], log_path: Path) -> None:
    """Wait for the API's health and its loaded catchment graph."""
    deadline = time.monotonic() + _READY_TIMEOUT_S

    def check_alive() -> None:
        if process.poll() is not None:
            raise RuntimeError(
                f"the API exited with {process.returncode}:\n"
                + log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            )
        if time.monotonic() > deadline:
            raise RuntimeError(
                "the API did not get ready:\n"
                + log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            )

    while True:
        check_alive()
        try:
            status, _ = _get(f"{base}/health")
        except OSError:
            status = 0
        if status == 200:
            break
        time.sleep(0.2)
    while True:
        check_alive()
        status, body = _get(f"{base}/api/admin/status", {"X-Admin-Key": ADMIN_KEY})
        if status == 200:
            checks = {c["name"]: c["status"] for c in json.loads(body)["checks"]}
            if checks.get("catchment_graph") == "ok":
                return
        time.sleep(0.3)


# nginx's mime.types for the files the site serves; anything else is its default_type
_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
}
_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "upgrade"}
_SERVER_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
)
_NO_STORE = ("Cache-Control", "no-store, no-cache, must-revalidate")


class _PagesServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, data_dir: Path, tiles_dir: Path, api: str, policies: Policies):
        super().__init__(("127.0.0.1", 0), _PagesHandler)
        self.data_dir = data_dir
        self.tiles_dir = tiles_dir
        api_address = urlsplit(api)
        self.api_host = api_address.hostname or "127.0.0.1"
        self.api_port = api_address.port or 80
        self.policies = policies


class _PagesHandler(BaseHTTPRequestHandler):
    """The locations of ``docker/nginx.conf``, in the order nginx picks them."""

    protocol_version = "HTTP/1.1"
    server: _PagesServer

    def log_message(self, format: str, *args: Any) -> None:
        """No log: the API writes its own."""

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route()

    def do_POST(self) -> None:
        self._route()

    def do_PUT(self) -> None:
        self._route()

    def do_PATCH(self) -> None:
        self._route()

    def do_DELETE(self) -> None:
        self._route()

    def _server_headers(self) -> list[tuple[str, str]]:
        return [
            *_SERVER_HEADERS,
            ("Content-Security-Policy", self.server.policies.page),
        ]

    def _route(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/") or path == "/health":
            status, headers, body = self._proxy(self.path)
            self._send(status, headers + self._server_headers(), body)
        elif path == "/admin":
            self._send(308, [("Location", "/admin/")], b"")
        elif re.fullmatch(r"/admin/.+\.(css|js)", path):
            self._file(
                FRONTEND / path[1:], [("Cache-Control", "no-store"), _SERVER_HEADERS[0]]
            )
        elif re.search(r"\.(css|js|ico|svg)$", path, re.IGNORECASE):
            self._file(FRONTEND / path[1:], [_SERVER_HEADERS[0]])
        elif path.lower().endswith(".html"):
            self._page(self.path)
        elif path.startswith("/data/"):
            self._file(
                self.server.data_dir / path[len("/data/") :],
                [_NO_STORE, _SERVER_HEADERS[0]],
            )
        elif path.startswith("/tiles/"):
            self._file(
                self.server.tiles_dir / path[len("/tiles/") :],
                [_NO_STORE, _SERVER_HEADERS[0]],
            )
        elif re.search(r"\.(pbf|geojson|mbtiles|pmtiles)$", path, re.IGNORECASE):
            self._file(FRONTEND / path[1:], [_NO_STORE, _SERVER_HEADERS[0]])
        else:
            # location /: try_files $uri $uri/ /index.html
            target = FRONTEND / path[1:]
            if path != "/" and target.is_file():
                self._file(target, self._server_headers())
            elif (target / "index.html").is_file():
                self._page(path.rstrip("/") + "/index.html")
            else:
                self._page("/index.html")

    def _page(self, path: str) -> None:
        """An HTML page: through the API, which names its file (X-Accel-Redirect)."""
        status, headers, body = self._proxy(path, method="GET")
        named = {k.lower(): v for k, v in headers}.get("x-accel-redirect")
        if named and named.startswith("/_site/"):
            relative = named[len("/_site/") :]
            if relative.startswith("admin/"):
                own = [
                    *_SERVER_HEADERS,
                    ("Content-Security-Policy", self.server.policies.admin),
                ]
            else:
                own = [*self._server_headers(), ("Cache-Control", "no-cache")]
            self._file(FRONTEND / relative, own)
            return
        self._send(status, headers + self._server_headers(), body)

    def _proxy(
        self, target: str, method: str | None = None
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP}
        headers["X-Real-IP"] = self.client_address[0]
        connection = http.client.HTTPConnection(
            self.server.api_host, self.server.api_port, timeout=120
        )
        try:
            connection.request(
                method or self.command, target, body=body, headers=headers
            )
            response = connection.getresponse()
            data = response.read()
            kept = [(k, v) for k, v in response.getheaders() if k.lower() not in _HOP]
            return response.status, kept, data
        except OSError:
            return 502, [("Content-Type", "text/plain")], b"502 Bad Gateway"
        finally:
            connection.close()

    def _file(self, path: Path, headers: list[tuple[str, str]]) -> None:
        resolved = path.resolve()
        roots = (FRONTEND, self.server.data_dir, self.server.tiles_dir)
        if not resolved.is_file() or not any(
            resolved.is_relative_to(root.resolve()) for root in roots
        ):
            self._send(404, [("Content-Type", "text/plain")], b"404 Not Found")
            return
        content_type = _TYPES.get(resolved.suffix.lower(), "application/octet-stream")
        self._send(
            200, [("Content-Type", content_type), *headers], resolved.read_bytes()
        )

    def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


@contextmanager
def _pages(
    data_dir: Path, tiles_dir: Path, api: str, policies: Policies
) -> Iterator[str]:
    """Serve the pages and the data as nginx does; yield the base address."""
    server = _PagesServer(data_dir, tiles_dir, api, policies)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@contextmanager
def serve_site(root: Path) -> Iterator[Site]:
    """Build the data into a private database and ``root``; serve the site."""
    with ExitStack() as stack:
        url = stack.enter_context(scratch_database())
        tiles_meta = build_data(url, root)
        api = stack.enter_context(_api(url, root))
        policies = nginx_policies()
        base = stack.enter_context(
            _pages(root / "frontend-data", root / "frontend-tiles", api, policies)
        )
        yield Site(
            base=base,
            api=api,
            root=root,
            data_dir=root / "frontend-data",
            tiles_dir=root / "frontend-tiles",
            tiles_meta=tiles_meta,
            policies=policies,
            database_url=url,
        )
