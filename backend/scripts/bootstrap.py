"""
One-command bootstrap for the Hydrograf hydrological hub.

Downloads NMT, processes DEM, imports land cover, fetches precipitation data,
generates overlays, and starts the full stack — all from a single command.

Usage:
    cd backend

    # By bounding box (WGS84)
    python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"

    # By sheet codes
    python -m scripts.bootstrap --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2

    # Dry run (show plan without executing)
    python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" --dry-run

    # Skip optional steps
    python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" \
        --skip-precipitation --skip-tiles
"""

import argparse
import asyncio
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "cache"

# Status symbols
SYM_DONE = "\u2713"  # checkmark
SYM_ACTIVE = "\u25cf"  # bullet
SYM_FAIL = "\u2717"  # cross
SYM_SKIP = "\u2013"  # en-dash

# Pipeline step names
STEP_NAMES = [
    "Infrastruktura",  # 1
    "Pobieranie NMT",  # 2
    "Przetwarzanie NMT",  # 3
    "Pokrycie terenu",  # 4
    "Dane glebowe HSG",  # 5
    "Opady IMGW",  # 6
    "Depresje",  # 7
    "Kafelki MVT",  # 8
    "Overlay PNG",  # 9
    "Uruchom serwer",  # 10
]

TOTAL_STEPS = len(STEP_NAMES)


class StepTracker:
    """Track pipeline step statuses and timings."""

    def __init__(self, total: int, skipped: set[int]):
        self.total = total
        self.statuses: list[str | None] = [None] * total  # None=pending
        self.details: list[str] = [""] * total
        self.timings: list[float] = [0.0] * total
        self.errors: list[str] = []
        for s in skipped:
            self.statuses[s - 1] = "skip"

    def start(self, step: int) -> float:
        self.statuses[step - 1] = "active"
        self._print_status()
        return time.time()

    def done(self, step: int, t0: float, detail: str = ""):
        self.timings[step - 1] = time.time() - t0
        self.statuses[step - 1] = "done"
        self.details[step - 1] = detail
        self._print_status()

    def fail(self, step: int, t0: float, error: str):
        self.timings[step - 1] = time.time() - t0
        self.statuses[step - 1] = "fail"
        self.details[step - 1] = error
        self.errors.append(f"[{step}/{self.total}] {STEP_NAMES[step - 1]}: {error}")
        self._print_status()

    def is_skipped(self, step: int) -> bool:
        return self.statuses[step - 1] == "skip"

    def _print_status(self):
        lines = []
        for i in range(self.total):
            num = f"[{i + 1}/{self.total}]"
            name = STEP_NAMES[i]
            status = self.statuses[i]
            detail = self.details[i]
            elapsed = self.timings[i]

            if status == "done":
                sym = SYM_DONE
                suffix = f"{detail:<40s} {elapsed:>6.1f}s"
            elif status == "active":
                sym = SYM_ACTIVE
                suffix = "..."
            elif status == "fail":
                sym = SYM_FAIL
                suffix = detail
            elif status == "skip":
                sym = SYM_SKIP
                suffix = "pominiety"
            else:
                sym = " "
                suffix = ""

            lines.append(f"{num} {sym} {name:<22s} {suffix}")

        print("\n".join(lines), flush=True)
        print()


def parse_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Parse 'min_lon,min_lat,max_lon,max_lat' string."""
    parts = [float(x.strip()) for x in bbox_str.split(",")]
    if len(parts) != 4:
        raise ValueError(
            "bbox wymaga 4 wartosci "
            f"(min_lon,min_lat,max_lon,max_lat), "
            f"otrzymano {len(parts)}"
        )
    return tuple(parts)  # type: ignore[return-value]


def sheets_to_bbox(sheets: list[str]) -> tuple[float, float, float, float]:
    """Compute bounding box (WGS84) from list of sheet codes via Kartograf."""
    from kartograf import SheetParser
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)

    all_bboxes = [SheetParser(s).get_bbox() for s in sheets]
    min_x = min(b.min_x for b in all_bboxes)
    min_y = min(b.min_y for b in all_bboxes)
    max_x = max(b.max_x for b in all_bboxes)
    max_y = max(b.max_y for b in all_bboxes)

    lon_min, lat_min = t.transform(min_x, min_y)
    lon_max, lat_max = t.transform(max_x, max_y)
    return (lon_min, lat_min, lon_max, lat_max)


def sheets_to_bbox_2180(
    sheets: list[str],
) -> tuple[float, float, float, float]:
    """Compute bounding box (EPSG:2180) from list of sheet codes."""
    from kartograf import SheetParser

    all_bboxes = [SheetParser(s).get_bbox(crs="EPSG:2180") for s in sheets]
    return (
        min(b.min_x for b in all_bboxes),
        min(b.min_y for b in all_bboxes),
        max(b.max_x for b in all_bboxes),
        max(b.max_y for b in all_bboxes),
    )


def resolve_sheets(
    bbox: tuple[float, float, float, float] | None,
    sheets: list[str] | None,
    scale: str,
) -> tuple[list[str], tuple[float, float, float, float]]:
    """Resolve sheets and bbox from CLI arguments."""
    sys.path.insert(0, str(BACKEND_DIR))
    from utils.sheet_finder import get_sheets_for_bbox

    if sheets:
        resolved_bbox = sheets_to_bbox(sheets)
        return sheets, resolved_bbox

    assert bbox is not None
    min_lon, min_lat, max_lon, max_lat = bbox
    resolved_sheets = get_sheets_for_bbox(min_lat, min_lon, max_lat, max_lon, scale)
    return resolved_sheets, bbox


def print_header(
    bbox: tuple[float, float, float, float],
    sheets: list[str],
    port: int,
):
    """Print bootstrap header with configuration summary."""
    min_lon, min_lat, max_lon, max_lat = bbox
    sep = "=" * 58
    area = (
        f"{min_lon:.3f}\u00b0E\u2013{max_lon:.3f}\u00b0E, "
        f"{min_lat:.3f}\u00b0N\u2013{max_lat:.3f}\u00b0N"
    )
    header = (
        f"{sep}\n"
        f"  Hydrograf Bootstrap\n"
        f"  Obszar: {area}\n"
        f"  Arkusze: {len(sheets)}\n"
        f"  Port: {port}\n"
        f"{sep}\n"
    )
    print(header)


def update_env_file(key: str, value: str):
    """Add or update a key in the root .env file."""
    env_path = PROJECT_ROOT / ".env"
    lines: list[str] = []
    found = False

    if env_path.exists():
        lines = env_path.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


def wait_for_health(url: str, timeout: int = 30, interval: float = 2.0) -> bool:
    """Poll a health endpoint until it responds 200."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            if resp.status == 200:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def step_infra() -> str:
    """Step 1: Infrastructure — .venv, Docker DB, Alembic."""
    details = []

    # 1a. Check/create .venv
    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    venv_pip = BACKEND_DIR / ".venv" / "bin" / "pip"

    if not venv_python.exists():
        logger.info("Tworzenie .venv...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(BACKEND_DIR / ".venv")],
            check=True,
        )
        subprocess.run(
            [str(venv_pip), "install", "-r", str(BACKEND_DIR / "requirements.txt")],
            check=True,
        )
        subprocess.run(
            [str(venv_pip), "install", "-e", f"{BACKEND_DIR}[dev]"],
            check=True,
        )
        details.append(".venv utworzony")
    else:
        details.append(".venv OK")

    # 1b. Docker DB
    result = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    running = result.stdout.strip()
    running_containers = running.split("\n") if running else []

    if "hydro_db" not in running_containers:
        logger.info("Uruchamianie bazy danych...")
        subprocess.run(
            ["docker", "compose", "up", "-d", "db"],
            check=True,
            cwd=str(PROJECT_ROOT),
        )
        # Wait for PostgreSQL to accept connections
        logger.info("Czekanie na gotowość PostgreSQL...")
        deadline = time.time() + 60
        while time.time() < deadline:
            ready = subprocess.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "db",
                    "pg_isready",
                    "-U",
                    "hydro_user",
                ],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError("Baza danych nie uruchomila sie w 60s")
        details.append("DB uruchomiona")
    else:
        details.append("DB OK")

    # 1c. Alembic migrations
    logger.info("Uruchamianie migracji Alembic...")
    subprocess.run(
        [str(venv_python), "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=str(BACKEND_DIR),
    )
    details.append("migracje OK")

    # 1d. CDN integrity hashes
    cdn_script = PROJECT_ROOT / "scripts" / "verify_cdn_hashes.sh"
    if cdn_script.exists():
        logger.info("Weryfikacja hashów SRI zasobów CDN...")
        result = subprocess.run(
            ["bash", str(cdn_script)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            logger.warning(
                "Niezgodność hashów CDN! Napraw: ./scripts/verify_cdn_hashes.sh --fix"
            )
            details.append("CDN HASH MISMATCH")
        else:
            details.append("CDN OK")

    return ", ".join(details)


def step_download_nmt(
    sheets: list[str],
    cache_dir: Path,
    resolution: str = "5m",
) -> tuple[list[Path], str]:
    """Step 2: Download NMT sheets via Kartograf."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_dem import download_sheets

    nmt_dir = cache_dir / "nmt"
    nmt_dir.mkdir(parents=True, exist_ok=True)

    downloaded = download_sheets(sheets, nmt_dir, skip_existing=True, resolution=resolution)

    # Count how many were already cached
    n_total = len(downloaded)
    detail = f"{n_total}/{len(sheets)} arkuszy"

    return downloaded, detail


def step_process_dem(
    downloaded_files: list[Path],
    output_dir: Path,
    cache_dir: Path,
    sheets: list[str],
    waterbody_mode: str = "auto",
    waterbody_min_area_m2: float | None = None,
) -> tuple[dict, str, list[str], dict[str, Path]]:
    """Step 3: Process DEM — mosaic VRT + stream burning + hydrological analysis."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_landcover import (
        discover_teryts_for_bbox,
        download_landcover,
        merge_hydro_gpkgs,
    )
    from scripts.process_dem import process_dem
    from utils.raster_utils import create_vrt_mosaic, discover_asc_files, normalize_crs

    cache_nmt_dir = cache_dir / "nmt"
    nmt_dir = output_dir / "nmt"
    nmt_dir.mkdir(parents=True, exist_ok=True)

    # Compute bbox once — reused for ASC discovery and hydro/landcover
    bbox_2180 = sheets_to_bbox_2180(sheets)

    # Discover ALL ASC files in cache nmt dir (new downloads + cached from previous runs)
    all_asc = discover_asc_files(cache_nmt_dir, bbox_2180)

    # Reproject PUWG 2000 files to EPSG:2180 before mosaicking
    normalized_files = normalize_crs(all_asc, nmt_dir / "reprojected")

    mosaic_path = create_vrt_mosaic(
        input_files=normalized_files,
        output_vrt=nmt_dir / "dem_mosaic.vrt",
        target_crs="EPSG:2180",
    )

    # Download & merge hydro BDOT10k for stream burning
    burn_path = None
    teryts: list[str] = []
    bdot_paths: dict[str, Path] = {}
    try:
        teryts = discover_teryts_for_bbox(bbox_2180)

        if teryts:
            bdot_cache_dir = cache_dir / "bdot10k"
            bdot_cache_dir.mkdir(parents=True, exist_ok=True)
            hydro_out_dir = output_dir / "hydro"
            hydro_out_dir.mkdir(parents=True, exist_ok=True)

            hydro_paths: list[Path] = []
            for teryt in teryts:
                gpkg = download_landcover(
                    output_dir=bdot_cache_dir,
                    provider="bdot10k",
                    teryt=teryt,
                    skip_existing=True,
                )
                if gpkg:
                    bdot_paths[teryt] = gpkg
                    hydro_paths.append(gpkg)

            if hydro_paths:
                burn_path = merge_hydro_gpkgs(
                    hydro_paths, hydro_out_dir / "hydro_merged.gpkg"
                )
    except Exception as e:
        logger.warning(f"Hydro download/merge failed, proceeding without burning: {e}")
        burn_path = None

    # Export BDOT10k to GeoJSON for frontend
    if burn_path:
        try:
            frontend_data = FRONTEND_DIR / "data"
            frontend_data.mkdir(parents=True, exist_ok=True)
            bdot_result = export_bdot_geojson(burn_path, frontend_data)
            logger.info(f"BDOT10k GeoJSON exported: {bdot_result}")
        except Exception as e:
            logger.warning(f"BDOT10k GeoJSON export failed: {e}")

    stats = process_dem(
        input_path=mosaic_path,
        stream_threshold=1000,
        clear_existing=True,
        save_intermediates=True,
        output_dir=nmt_dir,
        thresholds=[1000, 10000, 100000],
        burn_streams_path=burn_path,
        # hydro_resolution_m not needed when NMT downloaded at 5m resolution
        waterbody_mode=waterbody_mode,
        waterbody_min_area_m2=waterbody_min_area_m2,
    )

    cells = stats.get("valid_cells", 0)
    streams = stats.get("stream_segments", 0)
    burn_info = f", burn={burn_path.name}" if burn_path else ""
    detail = f"{cells:,} cells, {streams} segments{burn_info}"

    return stats, detail, teryts, bdot_paths


def step_landcover(
    sheets: list[str],
    output_dir: Path,
    cache_dir: Path,
    teryts: list[str] | None = None,
    bdot_paths: dict[str, Path] | None = None,
) -> str:
    """Step 4: Download and import land cover data (per-TERYT)."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_landcover import discover_teryts_for_bbox, download_landcover
    from scripts.import_landcover import import_landcover

    bdot_cache_dir = cache_dir / "bdot10k"
    bdot_cache_dir.mkdir(parents=True, exist_ok=True)

    if teryts is None:
        bbox_2180 = sheets_to_bbox_2180(sheets)
        teryts = discover_teryts_for_bbox(bbox_2180)

    if bdot_paths is None:
        bdot_paths = {}

    if not teryts:
        logger.warning("Nie znaleziono TERYT-ów dla podanego obszaru")
        return "0 obiektów, 0 powiatów"

    total_features = 0
    for teryt in teryts:
        try:
            # Reuse cached GPKG if available, otherwise download to cache
            gpkg = bdot_paths.get(teryt)
            if gpkg is None or not gpkg.exists():
                gpkg = download_landcover(
                    output_dir=bdot_cache_dir,
                    provider="bdot10k",
                    teryt=teryt,
                    skip_existing=True,
                )
            if gpkg and gpkg.exists():
                lc_stats = import_landcover(
                    input_path=gpkg,
                    clear_existing=False,
                )
                total_features += lc_stats.get("records_inserted", 0)
        except Exception as e:
            logger.warning(f"Land cover dla TERYT {teryt}: {e}")

    return f"{total_features} obiektów, {len(teryts)} powiatów"


def step_soil_hsg(sheets: list[str], output_dir: Path, cache_dir: Path) -> str:
    """Step 5: Download HSG data from SoilGrids and import to DB."""
    try:
        from kartograf import HSGCalculator
    except ImportError:
        return "pominięto (brak kartograf HSGCalculator)"

    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import MultiPolygon, shape

    sys.path.insert(0, str(BACKEND_DIR))
    from core.database import get_engine

    hsg_dir = cache_dir / "soil_hsg"
    hsg_dir.mkdir(parents=True, exist_ok=True)

    from kartograf import BBox

    bbox_tuple = sheets_to_bbox_2180(sheets)
    bbox_2180 = BBox(
        min_x=bbox_tuple[0],
        min_y=bbox_tuple[1],
        max_x=bbox_tuple[2],
        max_y=bbox_tuple[3],
        crs="EPSG:2180",
    )

    # Download HSG raster
    hsg_tif = hsg_dir / "hsg.tif"
    try:
        hsg_calc = HSGCalculator()
        hsg_calc.calculate_hsg_by_bbox(
            bbox=bbox_2180,
            output_path=hsg_tif,
            timeout=300,
        )
    except Exception as e:
        return f"pominięto (SoilGrids: {e})"

    if not hsg_tif.exists():
        return "pominięto (brak rastra HSG)"

    # Polygonize HSG raster and reproject to EPSG:2180
    import pyproj
    from shapely.ops import transform as shp_transform

    hsg_map = {1: "A", 2: "B", 3: "C", 4: "D"}
    records = []

    with rasterio.open(hsg_tif) as src:
        data = src.read(1)

        # Nearest-neighbor fill: replace invalid pixels (not in 1-4)
        import numpy as np

        valid_mask = np.isin(data, [1, 2, 3, 4])
        if not valid_mask.all():
            from scipy.ndimage import distance_transform_edt

            _, nearest_idx = distance_transform_edt(
                ~valid_mask,
                return_indices=True,
            )
            data = np.where(
                valid_mask,
                data,
                data[nearest_idx[0], nearest_idx[1]],
            )
            logger.info(
                f"HSG: filled {(~valid_mask).sum()}/{data.size} missing pixels"
                " with nearest-neighbor"
            )

        src_transform = src.transform
        src_crs = src.crs

        # Prepare reprojection if needed (SoilGrids delivers EPSG:4326)
        project = None
        if src_crs and src_crs.to_epsg() != 2180:
            project = pyproj.Transformer.from_crs(
                src_crs, "EPSG:2180", always_xy=True
            ).transform

        for geom_dict, value in shapes(data, transform=src_transform):
            value = int(value)
            if value not in hsg_map:
                continue
            geom = shape(geom_dict)
            if geom.is_empty:
                continue
            if project:
                geom = shp_transform(project, geom)
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

    # Bulk INSERT
    engine = get_engine()
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM soil_hsg"))
        conn.execute(
            text("""
                INSERT INTO soil_hsg (geom, hsg_group, area_m2)
                VALUES (ST_SetSRID(ST_GeomFromText(:geom), 2180), :hsg_group, :area_m2)
            """),
            records,
        )
        conn.commit()

    # Export GeoJSON for frontend map layer
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


def step_precipitation(bbox: tuple[float, float, float, float]) -> str:
    """Step 6: Download IMGW precipitation data."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.preprocess_precipitation import process_grid

    total, success, records = asyncio.run(
        process_grid(bbox, spacing_km=2.0, delay_s=0.5)
    )

    return f"{success}/{total} punktow, {records} rekordow"


def step_depressions(output_dir: Path) -> str:
    """Step 7: Generate depressions (blue spots)."""
    sys.path.insert(0, str(BACKEND_DIR))
    from core.database import get_db_session
    from scripts.generate_depressions import (
        compute_depressions,
        generate_overlay,
        insert_depressions,
    )

    nmt_dir = output_dir / "nmt"
    dem_path = nmt_dir / "dem_mosaic_01_dem.tif"
    filled_path = nmt_dir / "dem_mosaic_02_filled.tif"

    # Fallback: try VRT for DEM
    if not dem_path.exists():
        dem_path = nmt_dir / "dem_mosaic.vrt"
    if not filled_path.exists():
        raise FileNotFoundError(
            f"Brak filled DEM: {filled_path}. "
            "Upewnij sie ze krok 3 ukonczyl sie z save_intermediates=True"
        )

    depressions, depth, meta = compute_depressions(str(dem_path), str(filled_path))

    n_inserted = 0
    if depressions:
        with get_db_session() as db:
            n_inserted = insert_depressions(db, depressions)

    # Generate overlay PNG
    data_dir = FRONTEND_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    generate_overlay(
        depth,
        meta,
        str(data_dir / "depressions.png"),
        str(data_dir / "depressions.json"),
    )

    return f"{n_inserted} depresji"


def step_tiles() -> str:
    """Step 8: Generate MVT tiles (requires tippecanoe)."""
    venv_tippecanoe = BACKEND_DIR / ".venv" / "bin" / "tippecanoe"
    if not venv_tippecanoe.exists() and not shutil.which("tippecanoe"):
        logger.warning(
            "tippecanoe nie znalezione — pomijam kafelki MVT. "
            "Zainstaluj: pip install tippecanoe"
        )
        return "brak tippecanoe"

    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    tiles_dir = FRONTEND_DIR / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            str(venv_python),
            "-m",
            "scripts.generate_tiles",
            "--output-dir",
            str(tiles_dir),
        ],
        check=True,
        cwd=str(BACKEND_DIR),
    )

    return "OK"


def step_overlays(output_dir: Path) -> str:
    """Step 9: Generate DEM and streams overlay PNG."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.generate_dem_overlay import generate_overlay as dem_overlay
    from scripts.generate_streams_overlay import generate_overlay as streams_overlay

    nmt_dir = output_dir / "nmt"
    data_dir = FRONTEND_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    generated = []

    # DEM overlay
    vrt_path = nmt_dir / "dem_mosaic.vrt"
    if vrt_path.exists():
        dem_overlay(
            input_path=str(vrt_path),
            output_png=str(data_dir / "dem.png"),
            output_meta=str(data_dir / "dem.json"),
            source_crs="EPSG:2180",
        )
        generated.append("DEM")

    # DEM tile pyramid (for high-zoom display)
    dem_tiles_dir = data_dir / "dem_tiles"
    dem_tiles_meta = data_dir / "dem_tiles.json"
    tiles_missing = not dem_tiles_dir.exists() or not dem_tiles_meta.exists()
    if vrt_path.exists() and tiles_missing:
        logger.info("Generating DEM tile pyramid...")
        from scripts.generate_dem_tiles import generate_tiles as gen_dem_tiles

        gen_dem_tiles(
            input_path=str(vrt_path),
            output_dir=str(dem_tiles_dir),
            output_meta=str(dem_tiles_meta),
            source_crs="EPSG:2180",
            min_zoom=8,
            max_zoom=16,
            processes=4,
        )
        generated.append("DEM tiles")
    elif dem_tiles_dir.exists() and dem_tiles_meta.exists():
        logger.info("DEM tiles already exist, skipping")
        generated.append("DEM tiles (cached)")

    # Streams overlay
    stream_order_path = nmt_dir / "dem_mosaic_07_stream_order.tif"
    if stream_order_path.exists():
        streams_overlay(
            input_path=str(stream_order_path),
            output_png=str(data_dir / "streams.png"),
            output_meta=str(data_dir / "streams.json"),
            source_crs="EPSG:2180",
        )
        generated.append("streams")

    return ", ".join(generated) if generated else "brak danych"


def export_bdot_geojson(hydro_gpkg: Path, output_dir: Path) -> str:
    """Export BDOT10k hydro layers from GPKG to GeoJSON for frontend map."""
    import fiona
    import geopandas as gpd
    import pandas as pd

    layers = fiona.listlayers(str(hydro_gpkg))

    # Lakes (polygons) — OT_PTWP_A
    lakes_count = 0
    if "OT_PTWP_A" in layers:
        gdf = gpd.read_file(hydro_gpkg, layer="OT_PTWP_A")
        if not gdf.empty:
            gdf["source_layer"] = "OT_PTWP_A"
            gdf = gdf.to_crs("EPSG:4326")
            gdf.to_file(output_dir / "bdot_lakes.geojson", driver="GeoJSON")
            lakes_count = len(gdf)

    # Streams (lines) — OT_SWRS_L + OT_SWKN_L + OT_SWRM_L
    stream_layers = ["OT_SWRS_L", "OT_SWKN_L", "OT_SWRM_L"]
    stream_gdfs = []
    for layer_name in stream_layers:
        if layer_name in layers:
            gdf = gpd.read_file(hydro_gpkg, layer=layer_name)
            if not gdf.empty:
                gdf["source_layer"] = layer_name
                stream_gdfs.append(gdf)

    streams_count = 0
    if stream_gdfs:
        merged = gpd.GeoDataFrame(pd.concat(stream_gdfs, ignore_index=True))
        merged = merged.to_crs("EPSG:4326")
        merged.to_file(output_dir / "bdot_streams.geojson", driver="GeoJSON")
        streams_count = len(merged)

    return f"{lakes_count} zbiorników, {streams_count} cieków"


def step_serve(port: int) -> str:
    """Step 10: Start full Docker Compose stack."""
    if port != 8080:
        update_env_file("HYDROGRAF_PORT", str(port))

    subprocess.run(
        ["docker", "compose", "up", "-d"],
        check=True,
        cwd=str(PROJECT_ROOT),
    )

    url = f"http://localhost:{port}/health"
    if wait_for_health(url, timeout=30):
        return f"http://localhost:{port}"
    else:
        logger.warning(f"Health check nie odpowiedzial na {url}")
        return f"http://localhost:{port} (brak health)"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    sheets: list[str],
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    cache_dir: Path,
    port: int,
    skips: set[int],
    waterbody_mode: str = "auto",
    waterbody_min_area_m2: float | None = None,
):
    """Run the full 10-step bootstrap pipeline."""
    tracker = StepTracker(TOTAL_STEPS, skips)
    downloaded_files: list[Path] = []
    teryts: list[str] = []
    bdot_paths: dict[str, Path] = {}

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Infrastructure (CRITICAL)
    if not tracker.is_skipped(1):
        t0 = tracker.start(1)
        try:
            detail = step_infra()
            tracker.done(1, t0, detail)
        except Exception as e:
            tracker.fail(1, t0, str(e))
            logger.error(f"Krok 1 (infrastruktura) nie powiodl sie: {e}")
            return tracker

    # Step 2: Download NMT (CRITICAL)
    if not tracker.is_skipped(2):
        t0 = tracker.start(2)
        try:
            downloaded_files, detail = step_download_nmt(sheets, cache_dir)
            tracker.done(2, t0, detail)
        except Exception as e:
            tracker.fail(2, t0, str(e))
            logger.error(f"Krok 2 (pobieranie NMT) nie powiodl sie: {e}")
            return tracker
    else:
        # Try to find existing files for later steps
        nmt_dir = cache_dir / "nmt"
        if nmt_dir.exists():
            downloaded_files = sorted(nmt_dir.glob("*.asc"))

    if not downloaded_files:
        logger.error("Brak plikow NMT — nie mozna kontynuowac")
        return tracker

    # Step 3: Process DEM (CRITICAL)
    if not tracker.is_skipped(3):
        t0 = tracker.start(3)
        try:
            _, detail, teryts, bdot_paths = step_process_dem(
                downloaded_files, output_dir, cache_dir, sheets,
                waterbody_mode=waterbody_mode,
                waterbody_min_area_m2=waterbody_min_area_m2,
            )
            tracker.done(3, t0, detail)
        except Exception as e:
            tracker.fail(3, t0, str(e))
            logger.error(f"Krok 3 (przetwarzanie NMT) nie powiodl sie: {e}")
            return tracker

    # Step 4: Land cover (OPTIONAL)
    if not tracker.is_skipped(4):
        t0 = tracker.start(4)
        try:
            detail = step_landcover(
                sheets, output_dir, cache_dir,
                teryts=teryts, bdot_paths=bdot_paths,
            )
            tracker.done(4, t0, detail)
        except Exception as e:
            tracker.fail(4, t0, str(e))
            logger.warning(f"Krok 4 (pokrycie terenu): {e}")

    # Step 5: HSG (OPTIONAL)
    if not tracker.is_skipped(5):
        t0 = tracker.start(5)
        try:
            detail = step_soil_hsg(sheets, output_dir, cache_dir)
            tracker.done(5, t0, detail)
        except Exception as e:
            tracker.fail(5, t0, str(e))
            logger.warning(f"Krok 5 (HSG): {e}")

    # Step 6: Precipitation (OPTIONAL)
    if not tracker.is_skipped(6):
        t0 = tracker.start(6)
        try:
            detail = step_precipitation(bbox)
            tracker.done(6, t0, detail)
        except Exception as e:
            tracker.fail(6, t0, str(e))
            logger.warning(f"Krok 6 (opady IMGW): {e}")

    # Step 7: Depressions (OPTIONAL)
    if not tracker.is_skipped(7):
        t0 = tracker.start(7)
        try:
            detail = step_depressions(output_dir)
            tracker.done(7, t0, detail)
        except Exception as e:
            tracker.fail(7, t0, str(e))
            logger.warning(f"Krok 7 (depresje): {e}")

    # Step 8: MVT tiles (OPTIONAL)
    if not tracker.is_skipped(8):
        t0 = tracker.start(8)
        try:
            detail = step_tiles()
            tracker.done(8, t0, detail)
        except Exception as e:
            tracker.fail(8, t0, str(e))
            logger.warning(f"Krok 8 (kafelki MVT): {e}")

    # Step 9: Overlay PNG (OPTIONAL)
    if not tracker.is_skipped(9):
        t0 = tracker.start(9)
        try:
            detail = step_overlays(output_dir)
            tracker.done(9, t0, detail)
        except Exception as e:
            tracker.fail(9, t0, str(e))
            logger.warning(f"Krok 9 (overlay PNG): {e}")

    # Step 10: Start server (OPTIONAL)
    if not tracker.is_skipped(10):
        t0 = tracker.start(10)
        try:
            detail = step_serve(port)
            tracker.done(10, t0, detail)
        except Exception as e:
            tracker.fail(10, t0, str(e))
            logger.warning(f"Krok 10 (serwer): {e}")

    return tracker


def dry_run(
    sheets: list[str],
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    cache_dir: Path,
    port: int,
    skips: set[int],
):
    """Show what would be done without executing."""
    min_lon, min_lat, max_lon, max_lat = bbox
    print("\nDRY RUN — plan wykonania:\n")
    print(f"  Output dir: {output_dir}")
    print(f"  Cache dir:  {cache_dir}\n")

    tippecanoe_status = "(dostepne)" if shutil.which("tippecanoe") else "(NIEDOSTEPNE)"
    steps = [
        "Infrastruktura: .venv, docker compose up -d db, alembic upgrade head",
        f"Pobieranie NMT: {len(sheets)} arkuszy do {cache_dir / 'nmt'}",
        "Przetwarzanie NMT: mozaika VRT, "
        "stream_network, stream_catchments (ZAWSZE od zera)",
        f"Pokrycie terenu: BDOT10k per-TERYT (auto-discovery z {len(sheets)} arkuszy)",
        "Dane glebowe HSG: SoilGrids przez Kartograf HSGCalculator",
        f"Opady IMGW: grid 2km w bbox "
        f"{min_lon:.3f},{min_lat:.3f},"
        f"{max_lon:.3f},{max_lat:.3f}",
        "Depresje: blue spots z filled DEM",
        f"Kafelki MVT: tippecanoe {tippecanoe_status}",
        f"Overlay PNG: DEM + streams do {FRONTEND_DIR / 'data'}",
        f"Uruchom serwer: docker compose up -d, port {port}",
    ]

    for i, desc in enumerate(steps, 1):
        skip = SYM_SKIP if i in skips else " "
        print(f"  [{i}/{TOTAL_STEPS}] {skip} {desc}")

    print()


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Jednokomendowy setup srodowiska Hydrograf",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required (mutually exclusive)
    area_group = parser.add_mutually_exclusive_group(required=True)
    area_group.add_argument(
        "--bbox",
        type=str,
        help='Bounding box WGS84: "min_lon,min_lat,max_lon,max_lat"',
    )
    area_group.add_argument(
        "--sheets",
        nargs="+",
        metavar="SHEET",
        help="Godla arkuszy: N-34-131-C-c-2-1 N-34-131-C-c-2-2",
    )

    # Optional
    parser.add_argument(
        "--scale",
        type=str,
        default="1:10000",
        choices=["1:10000", "1:25000", "1:50000", "1:100000"],
        help="Skala mapy (default: 1:10000)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=f"Katalog wyjsciowy (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"Directory for cached raw downloads (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port HTTP (default: 8080)",
    )

    # Skip flags
    skip_group = parser.add_argument_group("Pomijanie krokow")
    skip_group.add_argument(
        "--skip-infra",
        action="store_true",
        help="Pomin .venv/Docker/Alembic",
    )
    skip_group.add_argument(
        "--skip-landcover",
        action="store_true",
        help="Pomin pokrycie terenu",
    )
    skip_group.add_argument(
        "--skip-hsg",
        action="store_true",
        help="Pomin dane glebowe HSG",
    )
    skip_group.add_argument(
        "--skip-precipitation",
        action="store_true",
        help="Pomin opady IMGW",
    )
    skip_group.add_argument(
        "--skip-depressions",
        action="store_true",
        help="Pomin depresje",
    )
    skip_group.add_argument(
        "--skip-tiles",
        action="store_true",
        help="Pomin kafelki MVT",
    )
    skip_group.add_argument(
        "--skip-overlays",
        action="store_true",
        help="Pomin overlay PNG",
    )
    skip_group.add_argument(
        "--skip-serve",
        action="store_true",
        help="Pomin uruchomienie serwera",
    )

    # Waterbody options
    wb_group = parser.add_argument_group("Zbiorniki wodne")
    wb_group.add_argument(
        "--waterbody-mode",
        type=str,
        default="auto",
        help='Tryb obslugi zbiornikow: "auto" (BDOT10k klasyfikacja), '
             '"none" (pomin), lub sciezka do pliku .gpkg/.shp '
             "(wszystkie traktowane jako endoreiczne). Default: auto",
    )
    wb_group.add_argument(
        "--waterbody-min-area",
        type=float,
        default=None,
        help="Min. powierzchnia zbiornika (m²). Zbiorniki mniejsze sa ignorowane.",
    )

    # Configuration file
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Sciezka do pliku konfiguracyjnego YAML (default: config.yaml)",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tylko pokaz co zostanie zrobione",
    )

    return parser


def main():
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Load YAML pipeline configuration (merged with defaults)
    sys.path.insert(0, str(BACKEND_DIR))
    from core.config import load_config

    config = load_config(args.config)
    logger.info(f"Konfiguracja zaladowana z: {args.config}")

    # Resolve output directory
    output_dir = Path(args.output) if args.output else DEFAULT_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve cache directory
    cache_dir = args.cache_dir or Path(
        config.get("paths", {}).get("cache_dir", str(DEFAULT_CACHE_DIR))
    )
    cache_dir = cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Parse bbox or resolve sheets
    bbox_parsed = parse_bbox(args.bbox) if args.bbox else None
    sheets, bbox = resolve_sheets(bbox_parsed, args.sheets, args.scale)

    if not sheets:
        logger.error("Nie znaleziono arkuszy dla podanego obszaru")
        sys.exit(1)

    # Collect skip flags → step numbers
    skips: set[int] = set()
    if args.skip_infra:
        skips.add(1)
    if args.skip_landcover:
        skips.add(4)
    if args.skip_hsg:
        skips.add(5)
    if args.skip_precipitation:
        skips.add(6)
    if args.skip_depressions:
        skips.add(7)
    if args.skip_tiles:
        skips.add(8)
    if args.skip_overlays:
        skips.add(9)
    if args.skip_serve:
        skips.add(10)

    # Print header
    print_header(bbox, sheets, args.port)

    if args.dry_run:
        dry_run(sheets, bbox, output_dir, cache_dir, args.port, skips)
        return

    # Run pipeline
    total_start = time.time()
    tracker = run_pipeline(
        sheets, bbox, output_dir, cache_dir, args.port, skips,
        waterbody_mode=args.waterbody_mode,
        waterbody_min_area_m2=args.waterbody_min_area,
    )
    total_elapsed = time.time() - total_start

    # Final summary
    print(f"{'=' * 58}")
    print(f"  Czas calkowity: {total_elapsed:.1f}s")
    if tracker.errors:
        print(f"\n  Bledy ({len(tracker.errors)}):")
        for err in tracker.errors:
            print(f"    {SYM_FAIL} {err}")
    print(f"{'=' * 58}")

    # Exit with error if critical steps failed
    critical_failed = any(
        tracker.statuses[i] == "fail"
        for i in range(3)  # steps 1-3
    )
    if critical_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
