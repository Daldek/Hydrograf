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

# Status symbols
SYM_DONE = "\u2713"  # checkmark
SYM_ACTIVE = "\u25cf"  # bullet
SYM_FAIL = "\u2717"  # cross
SYM_SKIP = "\u2013"  # en-dash

# Pipeline step names
STEP_NAMES = [
    "Infrastruktura",
    "Pobieranie NMT",
    "Przetwarzanie NMT",
    "Pokrycie terenu",
    "Opady IMGW",
    "Depresje",
    "Kafelki MVT",
    "Overlay PNG",
    "Uruchom serwer",
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

    return ", ".join(details)


def step_download_nmt(
    sheets: list[str],
    output_dir: Path,
) -> tuple[list[Path], str]:
    """Step 2: Download NMT sheets via Kartograf."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_dem import download_sheets

    nmt_dir = output_dir / "nmt"
    nmt_dir.mkdir(parents=True, exist_ok=True)

    downloaded = download_sheets(sheets, nmt_dir, skip_existing=True)

    # Count how many were already cached
    n_total = len(downloaded)
    detail = f"{n_total}/{len(sheets)} arkuszy"

    return downloaded, detail


def step_process_dem(
    downloaded_files: list[Path],
    output_dir: Path,
    sheets: list[str],
) -> tuple[dict, str]:
    """Step 3: Process DEM — mosaic VRT + stream burning + hydrological analysis."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_landcover import (
        discover_teryts_for_bbox,
        download_landcover,
        merge_hydro_gpkgs,
    )
    from scripts.process_dem import process_dem
    from utils.raster_utils import create_vrt_mosaic

    nmt_dir = output_dir / "nmt"
    mosaic_path = create_vrt_mosaic(
        input_files=downloaded_files,
        output_vrt=nmt_dir / "dem_mosaic.vrt",
    )

    # Download & merge hydro BDOT10k for stream burning
    burn_path = None
    try:
        bbox_2180 = sheets_to_bbox_2180(sheets)
        teryts = discover_teryts_for_bbox(bbox_2180)

        if teryts:
            hydro_dir = output_dir / "hydro"
            hydro_dir.mkdir(parents=True, exist_ok=True)

            hydro_paths: list[Path] = []
            for teryt in teryts:
                gpkg = download_landcover(
                    output_dir=hydro_dir,
                    provider="bdot10k",
                    category="hydro",
                    teryt=teryt,
                    skip_existing=True,
                )
                if gpkg:
                    hydro_paths.append(gpkg)

            if hydro_paths:
                burn_path = merge_hydro_gpkgs(
                    hydro_paths, hydro_dir / "hydro_merged.gpkg"
                )
    except Exception as e:
        logger.warning(f"Hydro download/merge failed, proceeding without burning: {e}")
        burn_path = None

    stats = process_dem(
        input_path=mosaic_path,
        stream_threshold=100,
        clear_existing=True,
        save_intermediates=True,
        output_dir=nmt_dir,
        thresholds=[100, 1000, 10000, 100000],
        burn_streams_path=burn_path,
    )

    cells = stats.get("valid_cells", 0)
    streams = stats.get("stream_segments", 0)
    burn_info = f", burn={burn_path.name}" if burn_path else ""
    detail = f"{cells:,} cells, {streams} segments{burn_info}"

    return stats, detail


def step_landcover(sheets: list[str], output_dir: Path) -> str:
    """Step 4: Download and import land cover data (per-TERYT)."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_landcover import discover_teryts_for_bbox, download_landcover
    from scripts.import_landcover import import_landcover

    lc_dir = output_dir / "landcover"
    lc_dir.mkdir(parents=True, exist_ok=True)

    bbox_2180 = sheets_to_bbox_2180(sheets)
    teryts = discover_teryts_for_bbox(bbox_2180)

    if not teryts:
        logger.warning("Nie znaleziono TERYT-ów dla podanego obszaru")
        return "0 obiektów, 0 powiatów"

    total_features = 0
    for teryt in teryts:
        try:
            gpkg = download_landcover(
                output_dir=lc_dir,
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


def step_precipitation(bbox: tuple[float, float, float, float]) -> str:
    """Step 5: Download IMGW precipitation data."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.preprocess_precipitation import process_grid

    total, success, records = asyncio.run(
        process_grid(bbox, spacing_km=2.0, delay_s=0.5)
    )

    return f"{success}/{total} punktow, {records} rekordow"


def step_depressions(output_dir: Path) -> str:
    """Step 6: Generate depressions (blue spots)."""
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
    """Step 7: Generate MVT tiles (requires tippecanoe)."""
    if not shutil.which("tippecanoe"):
        logger.warning(
            "tippecanoe nie znalezione — pomijam kafelki MVT. "
            "Zainstaluj: https://github.com/felt/tippecanoe"
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
    """Step 8: Generate DEM and streams overlay PNG."""
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


def step_serve(port: int) -> str:
    """Step 9: Start full Docker Compose stack."""
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
    port: int,
    skips: set[int],
):
    """Run the full 9-step bootstrap pipeline."""
    tracker = StepTracker(TOTAL_STEPS, skips)
    downloaded_files: list[Path] = []

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
            downloaded_files, detail = step_download_nmt(sheets, output_dir)
            tracker.done(2, t0, detail)
        except Exception as e:
            tracker.fail(2, t0, str(e))
            logger.error(f"Krok 2 (pobieranie NMT) nie powiodl sie: {e}")
            return tracker
    else:
        # Try to find existing files for later steps
        nmt_dir = output_dir / "nmt"
        if nmt_dir.exists():
            downloaded_files = sorted(nmt_dir.glob("*.asc"))

    if not downloaded_files:
        logger.error("Brak plikow NMT — nie mozna kontynuowac")
        return tracker

    # Step 3: Process DEM (CRITICAL)
    if not tracker.is_skipped(3):
        t0 = tracker.start(3)
        try:
            _, detail = step_process_dem(downloaded_files, output_dir, sheets)
            tracker.done(3, t0, detail)
        except Exception as e:
            tracker.fail(3, t0, str(e))
            logger.error(f"Krok 3 (przetwarzanie NMT) nie powiodl sie: {e}")
            return tracker

    # Step 4: Land cover (OPTIONAL)
    if not tracker.is_skipped(4):
        t0 = tracker.start(4)
        try:
            detail = step_landcover(sheets, output_dir)
            tracker.done(4, t0, detail)
        except Exception as e:
            tracker.fail(4, t0, str(e))
            logger.warning(f"Krok 4 (pokrycie terenu): {e}")

    # Step 5: Precipitation (OPTIONAL)
    if not tracker.is_skipped(5):
        t0 = tracker.start(5)
        try:
            detail = step_precipitation(bbox)
            tracker.done(5, t0, detail)
        except Exception as e:
            tracker.fail(5, t0, str(e))
            logger.warning(f"Krok 5 (opady IMGW): {e}")

    # Step 6: Depressions (OPTIONAL)
    if not tracker.is_skipped(6):
        t0 = tracker.start(6)
        try:
            detail = step_depressions(output_dir)
            tracker.done(6, t0, detail)
        except Exception as e:
            tracker.fail(6, t0, str(e))
            logger.warning(f"Krok 6 (depresje): {e}")

    # Step 7: MVT tiles (OPTIONAL)
    if not tracker.is_skipped(7):
        t0 = tracker.start(7)
        try:
            detail = step_tiles()
            tracker.done(7, t0, detail)
        except Exception as e:
            tracker.fail(7, t0, str(e))
            logger.warning(f"Krok 7 (kafelki MVT): {e}")

    # Step 8: Overlay PNG (OPTIONAL)
    if not tracker.is_skipped(8):
        t0 = tracker.start(8)
        try:
            detail = step_overlays(output_dir)
            tracker.done(8, t0, detail)
        except Exception as e:
            tracker.fail(8, t0, str(e))
            logger.warning(f"Krok 8 (overlay PNG): {e}")

    # Step 9: Start server (OPTIONAL)
    if not tracker.is_skipped(9):
        t0 = tracker.start(9)
        try:
            detail = step_serve(port)
            tracker.done(9, t0, detail)
        except Exception as e:
            tracker.fail(9, t0, str(e))
            logger.warning(f"Krok 9 (serwer): {e}")

    return tracker


def dry_run(
    sheets: list[str],
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    port: int,
    skips: set[int],
):
    """Show what would be done without executing."""
    min_lon, min_lat, max_lon, max_lat = bbox
    print("\nDRY RUN — plan wykonania:\n")

    tippecanoe_status = "(dostepne)" if shutil.which("tippecanoe") else "(NIEDOSTEPNE)"
    steps = [
        "Infrastruktura: .venv, docker compose up -d db, alembic upgrade head",
        f"Pobieranie NMT: {len(sheets)} arkuszy do {output_dir / 'nmt'}",
        "Przetwarzanie NMT: mozaika VRT, "
        "stream_network, stream_catchments (ZAWSZE od zera)",
        f"Pokrycie terenu: BDOT10k per-TERYT (auto-discovery z {len(sheets)} arkuszy)",
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

    # Resolve output directory
    output_dir = Path(args.output) if args.output else DEFAULT_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

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
    if args.skip_precipitation:
        skips.add(5)
    if args.skip_depressions:
        skips.add(6)
    if args.skip_tiles:
        skips.add(7)
    if args.skip_overlays:
        skips.add(8)
    if args.skip_serve:
        skips.add(9)

    # Print header
    print_header(bbox, sheets, args.port)

    if args.dry_run:
        dry_run(sheets, bbox, output_dir, args.port, skips)
        return

    # Run pipeline
    total_start = time.time()
    tracker = run_pipeline(sheets, bbox, output_dir, args.port, skips)
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
