"""
Clean generated data for fresh bootstrap regeneration.

Removes processed rasters, frontend assets, MVT tiles, and optionally
database tables and download caches — preparing a clean slate for re-running
the bootstrap pipeline.

Usage:
    cd backend

    # Standard clean (processed data only, keeps caches)
    python -m scripts.clean

    # Full clean (including download caches)
    python -m scripts.clean --include-cache

    # Nuclear clean (everything + database reset)
    python -m scripts.clean --all

    # Clean specific components only
    python -m scripts.clean --only rasters tiles overlays

    # Dry run (show what would be removed)
    python -m scripts.clean --dry-run

    # Skip confirmation prompt
    python -m scripts.clean --yes
"""

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "cache"

# Components and what they remove
COMPONENTS = [
    "rasters",
    "hydro",
    "boundary",
    "overlays",
    "tiles",
    "geojson",
    "db",
    "cache",
]

# Tables truncated during DB cleanup. soil_hsg included because bootstrap
# re-imports from cache/soil_hsg (which is intentionally preserved).
DB_TABLES = [
    "stream_catchments",
    "stream_network",
    "depressions",
    "land_cover",
    "precipitation_data",
    "soil_hsg",
]


def dir_size(path: Path) -> int:
    """Total size of directory in bytes."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def fmt_size(size_bytes: int) -> str:
    """Format size in human-readable units."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def count_files(path: Path) -> int:
    """Count files in directory recursively."""
    if not path.exists():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())


def remove_dir(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """Remove directory contents, return (files_removed, bytes_freed)."""
    if not path.exists():
        return 0, 0
    n_files = count_files(path)
    size = dir_size(path)
    if not dry_run:
        shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    return n_files, size


def remove_files_by_glob(
    directory: Path, pattern: str, dry_run: bool = False,
) -> tuple[int, int]:
    """Remove files matching glob pattern, return (files_removed, bytes_freed)."""
    if not directory.exists():
        return 0, 0
    files = list(directory.glob(pattern))
    n_files = len(files)
    size = sum(f.stat().st_size for f in files if f.is_file())
    if not dry_run:
        for f in files:
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
    return n_files, size


def clean_rasters(data_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Remove processed DEM rasters (TIF files and VRT)."""
    nmt_dir = data_dir / "nmt"
    if not nmt_dir.exists():
        return 0, 0

    total_files = 0
    total_size = 0

    # Remove .tif intermediates
    n, s = remove_files_by_glob(nmt_dir, "*.tif", dry_run)
    total_files += n
    total_size += s

    # Remove VRT
    n, s = remove_files_by_glob(nmt_dir, "*.vrt", dry_run)
    total_files += n
    total_size += s

    return total_files, total_size


def clean_hydro(data_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Remove merged BDOT10k hydro data."""
    hydro_dir = data_dir / "hydro"
    return remove_dir(hydro_dir, dry_run)


def clean_boundary(data_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Remove uploaded boundary files."""
    boundary_dir = data_dir / "boundary"
    return remove_dir(boundary_dir, dry_run)


def clean_overlays(dry_run: bool) -> tuple[int, int]:
    """Remove frontend overlay PNGs, JSONs, and DEM tile pyramid."""
    data_dir = FRONTEND_DIR / "data"
    if not data_dir.exists():
        return 0, 0

    total_files = 0
    total_size = 0

    # PNG overlays
    for pattern in ["*.png", "*.json"]:
        n, s = remove_files_by_glob(data_dir, pattern, dry_run)
        total_files += n
        total_size += s

    # DEM tile pyramid
    dem_tiles = data_dir / "dem_tiles"
    if dem_tiles.exists():
        n, s = remove_dir(dem_tiles, dry_run)
        total_files += n
        total_size += s

    return total_files, total_size


def clean_geojson(dry_run: bool) -> tuple[int, int]:
    """Remove exported GeoJSON files from frontend/data."""
    data_dir = FRONTEND_DIR / "data"
    return remove_files_by_glob(data_dir, "*.geojson", dry_run)


def clean_tiles(dry_run: bool) -> tuple[int, int]:
    """Remove MVT vector tiles and mbtiles."""
    tiles_dir = FRONTEND_DIR / "tiles"
    return remove_dir(tiles_dir, dry_run)


def clean_cache(cache_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Remove download caches (NMT, BDOT10k). Keeps soil_hsg (small, Poland-wide)."""
    total_files = 0
    total_size = 0

    # NMT cache (biggest, ~300MB)
    nmt_cache = cache_dir / "nmt"
    if nmt_cache.exists():
        n, s = remove_dir(nmt_cache, dry_run)
        total_files += n
        total_size += s

    # BDOT10k cache (~1.1GB)
    bdot_cache = cache_dir / "bdot10k"
    if bdot_cache.exists():
        n, s = remove_dir(bdot_cache, dry_run)
        total_files += n
        total_size += s

    # soil_hsg intentionally NOT removed (~700KB, Poland-wide, reusable)
    hsg_cache = cache_dir / "soil_hsg"
    if hsg_cache.exists():
        logger.info("  (zachowano cache/soil_hsg — maly, ogolnopolski)")

    return total_files, total_size


def clean_db(dry_run: bool) -> int:
    """Truncate all pipeline data tables. Returns number of tables cleaned."""
    sys.path.insert(0, str(BACKEND_DIR))

    try:
        from core.database import get_engine
    except Exception as e:
        logger.warning(f"Brak polaczenia z baza danych: {e}")
        return 0

    try:
        from sqlalchemy import text

        engine = get_engine()
        cleaned = 0
        with engine.connect() as conn:
            for table in DB_TABLES:
                try:
                    result = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 — table names from hardcoded DB_TABLES, not user input
                    )
                    count = result.scalar()
                    if count == 0:
                        logger.info(f"  {table}: pusta, pomijam")
                        continue

                    if not dry_run:
                        conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))  # noqa: S608 — table names from hardcoded DB_TABLES, not user input
                    logger.info(f"  {table}: {count} rekordow {'usunietych' if not dry_run else '(dry run)'}")
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"  {table}: {e}")

            if not dry_run:
                conn.commit()

        return cleaned
    except Exception as e:
        logger.warning(f"Czyszczenie bazy nie powiodlo sie: {e}")
        return 0


def build_plan(
    components: list[str],
    data_dir: Path,
    cache_dir: Path,
) -> list[dict]:
    """Build a plan of what will be cleaned, with sizes."""
    plan = []

    if "rasters" in components:
        nmt_dir = data_dir / "nmt"
        plan.append({
            "name": "Rastry NMT",
            "component": "rasters",
            "path": str(nmt_dir),
            "files": count_files(nmt_dir) if nmt_dir.exists() else 0,
            "size": dir_size(nmt_dir),
        })

    if "hydro" in components:
        hydro_dir = data_dir / "hydro"
        plan.append({
            "name": "Dane hydro BDOT10k",
            "component": "hydro",
            "path": str(hydro_dir),
            "files": count_files(hydro_dir) if hydro_dir.exists() else 0,
            "size": dir_size(hydro_dir),
        })

    if "boundary" in components:
        boundary_dir = data_dir / "boundary"
        plan.append({
            "name": "Pliki boundary",
            "component": "boundary",
            "path": str(boundary_dir),
            "files": count_files(boundary_dir) if boundary_dir.exists() else 0,
            "size": dir_size(boundary_dir),
        })

    if "overlays" in components:
        overlay_dir = FRONTEND_DIR / "data"
        png_files = list(overlay_dir.glob("*.png")) if overlay_dir.exists() else []
        json_files = list(overlay_dir.glob("*.json")) if overlay_dir.exists() else []
        dem_tiles = overlay_dir / "dem_tiles" if overlay_dir.exists() else None
        size = sum(f.stat().st_size for f in png_files + json_files)
        n = len(png_files) + len(json_files)
        if dem_tiles and dem_tiles.exists():
            size += dir_size(dem_tiles)
            n += count_files(dem_tiles)
        plan.append({
            "name": "Overlay PNG/JSON + DEM tiles",
            "component": "overlays",
            "path": str(overlay_dir),
            "files": n,
            "size": size,
        })

    if "geojson" in components:
        data_dir_fe = FRONTEND_DIR / "data"
        geojson_files = list(data_dir_fe.glob("*.geojson")) if data_dir_fe.exists() else []
        plan.append({
            "name": "Eksporty GeoJSON",
            "component": "geojson",
            "path": str(data_dir_fe),
            "files": len(geojson_files),
            "size": sum(f.stat().st_size for f in geojson_files),
        })

    if "tiles" in components:
        tiles_dir = FRONTEND_DIR / "tiles"
        plan.append({
            "name": "Kafelki MVT",
            "component": "tiles",
            "path": str(tiles_dir),
            "files": count_files(tiles_dir) if tiles_dir.exists() else 0,
            "size": dir_size(tiles_dir),
        })

    if "db" in components:
        plan.append({
            "name": "Tabele bazy danych",
            "component": "db",
            "path": "PostgreSQL",
            "files": len(DB_TABLES),
            "size": 0,  # unknown without query
        })

    if "cache" in components:
        nmt_cache = cache_dir / "nmt"
        bdot_cache = cache_dir / "bdot10k"
        size = dir_size(nmt_cache) + dir_size(bdot_cache)
        n = count_files(nmt_cache) + count_files(bdot_cache)
        plan.append({
            "name": "Cache pobran (NMT + BDOT10k)",
            "component": "cache",
            "path": str(cache_dir),
            "files": n,
            "size": size,
        })

    return plan


def execute_clean(
    components: list[str],
    data_dir: Path,
    cache_dir: Path,
    dry_run: bool,
) -> dict:
    """Execute cleanup, return summary."""
    results = {}
    total_files = 0
    total_size = 0

    if "rasters" in components:
        n, s = clean_rasters(data_dir, dry_run)
        results["rasters"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"Rastry NMT: {n} plikow, {fmt_size(s)}")

    if "hydro" in components:
        n, s = clean_hydro(data_dir, dry_run)
        results["hydro"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"Dane hydro: {n} plikow, {fmt_size(s)}")

    if "boundary" in components:
        n, s = clean_boundary(data_dir, dry_run)
        results["boundary"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"Pliki boundary: {n} plikow, {fmt_size(s)}")

    if "overlays" in components:
        n, s = clean_overlays(dry_run)
        results["overlays"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"Overlays: {n} plikow, {fmt_size(s)}")

    if "geojson" in components:
        n, s = clean_geojson(dry_run)
        results["geojson"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"GeoJSON: {n} plikow, {fmt_size(s)}")

    if "tiles" in components:
        n, s = clean_tiles(dry_run)
        results["tiles"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"Kafelki MVT: {n} plikow, {fmt_size(s)}")

    if "db" in components:
        cleaned = clean_db(dry_run)
        results["db"] = (cleaned, 0)
        logger.info(f"Baza danych: {cleaned} tabel wyczyszczonych")

    if "cache" in components:
        n, s = clean_cache(cache_dir, dry_run)
        results["cache"] = (n, s)
        total_files += n
        total_size += s
        logger.info(f"Cache pobran: {n} plikow, {fmt_size(s)}")

    return {
        "results": results,
        "total_files": total_files,
        "total_size": total_size,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Czyszczenie wygenerowanych danych Hydrograf",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Scope presets
    scope_group = parser.add_argument_group("Zakres czyszczenia")
    scope_group.add_argument(
        "--all",
        action="store_true",
        help="Usun wszystko: dane, cache, tabele DB",
    )
    scope_group.add_argument(
        "--include-cache",
        action="store_true",
        help="Usun rowniez cache pobran (NMT, BDOT10k)",
    )
    scope_group.add_argument(
        "--include-db",
        action="store_true",
        help="Wyczysc tabele bazy danych (TRUNCATE)",
    )
    scope_group.add_argument(
        "--only",
        nargs="+",
        choices=COMPONENTS,
        metavar="COMPONENT",
        help=f"Czysc tylko wybrane komponenty: {', '.join(COMPONENTS)}",
    )

    # Options
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Katalog danych (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"Katalog cache (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tylko pokaz co zostanie usuniete",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Pomin potwierdzenie",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    data_dir = args.output or DEFAULT_DATA_DIR
    cache_dir = args.cache_dir or DEFAULT_CACHE_DIR

    # Determine components to clean
    if args.only:
        components = args.only
    elif args.all:
        components = list(COMPONENTS)
    else:
        # Default: processed data only (no cache, no db)
        components = ["rasters", "hydro", "boundary", "overlays", "geojson", "tiles"]
        if args.include_cache:
            components.append("cache")
        if args.include_db:
            components.append("db")

    # Build and display plan
    plan = build_plan(components, data_dir, cache_dir)
    total_size = sum(item["size"] for item in plan)
    total_files = sum(item["files"] for item in plan)

    mode = "DRY RUN" if args.dry_run else "CZYSZCZENIE"
    print(f"\n{'=' * 58}")
    print(f"  Hydrograf — {mode}")
    print(f"{'=' * 58}\n")

    if not plan or total_files == 0:
        print("  Brak danych do wyczyszczenia.\n")
        return

    for item in plan:
        if item["files"] > 0 or item["component"] == "db":
            marker = "*" if item["size"] > 100 * 1024 * 1024 else " "  # >100MB
            size_str = fmt_size(item["size"]) if item["size"] > 0 else "—"
            print(f"  {marker} {item['name']:<30} {item['files']:>6} plikow  {size_str:>10}")

    print(f"\n  RAZEM: {total_files} plikow, {fmt_size(total_size)}")

    if "cache" not in components:
        cache_size = dir_size(cache_dir)
        if cache_size > 0:
            print(f"  (cache zachowany: {fmt_size(cache_size)} — uzyj --include-cache aby usunac)")

    print()

    # Confirm
    if not args.dry_run and not args.yes:
        answer = input("  Kontynuowac? [t/N] ").strip().lower()
        if answer not in ("t", "tak", "y", "yes"):
            print("  Przerwano.\n")
            return

    # Execute
    t0 = time.time()
    summary = execute_clean(components, data_dir, cache_dir, args.dry_run)
    elapsed = time.time() - t0

    verb = "zostaloby usuniete" if args.dry_run else "usunieto"
    print(f"\n{'=' * 58}")
    print(f"  {verb.upper()}: {summary['total_files']} plikow, {fmt_size(summary['total_size'])}")
    print(f"  Czas: {elapsed:.1f}s")

    if not args.dry_run:
        print(f"\n  Gotowe do regeneracji:")
        print(f"    cd backend")
        print(f"    python -m scripts.bootstrap --bbox \"...\"")

    print(f"{'=' * 58}\n")


if __name__ == "__main__":
    main()
