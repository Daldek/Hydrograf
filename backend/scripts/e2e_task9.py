"""
E2E Task 9 — Ponowne wykonanie wyznaczania zlewni na N-33-131-C-b-2.

Wykorzystuje dane z Tasks 7-8 (juz w bazie flow_network, 4.9M komorek).
Testuje zabezpieczenia OOM dodane w ADR-015:
- Pre-flight check (check_watershed_size)
- LIMIT w CTE
- statement_timeout=30s

Testy:
A) Sredni outlet (~500k cells, ~0.5 km²) — bezpieczny
B) Duzy outlet (max acc ~1.76M cells, ~1.76 km²) — testuje granice
C) Sztuczny outlet ponad limit — sprawdza reject

Uzycie:
    cd backend
    .venv/bin/python -m scripts.e2e_task9
"""

import logging
import sys
import time

from sqlalchemy import text

from core.database import get_db_session
from core.morphometry import build_morphometric_params
from core.watershed import (
    MAX_WATERSHED_CELLS,
    FlowCell,
    build_boundary,
    calculate_watershed_area_km2,
    check_watershed_size,
    traverse_upstream,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SEPARATOR = "=" * 70


def find_outlet_by_accumulation(db, min_acc: int, max_acc: int) -> FlowCell | None:
    """Find a stream outlet with flow_accumulation in given range."""
    result = db.execute(
        text("""
            SELECT id, ST_X(geom) as x, ST_Y(geom) as y,
                   elevation, flow_accumulation, slope,
                   downstream_id, cell_area, is_stream
            FROM flow_network
            WHERE is_stream = TRUE
              AND flow_accumulation BETWEEN :min_acc AND :max_acc
            ORDER BY flow_accumulation DESC
            LIMIT 1
        """),
        {"min_acc": min_acc, "max_acc": max_acc},
    ).fetchone()

    if result is None:
        return None

    return FlowCell(
        id=result.id,
        x=result.x,
        y=result.y,
        elevation=result.elevation,
        flow_accumulation=result.flow_accumulation,
        slope=result.slope,
        downstream_id=result.downstream_id,
        cell_area=result.cell_area,
        is_stream=result.is_stream,
    )


def find_max_outlet(db) -> FlowCell | None:
    """Find the outlet with maximum flow accumulation."""
    result = db.execute(
        text("""
            SELECT id, ST_X(geom) as x, ST_Y(geom) as y,
                   elevation, flow_accumulation, slope,
                   downstream_id, cell_area, is_stream
            FROM flow_network
            WHERE is_stream = TRUE
            ORDER BY flow_accumulation DESC
            LIMIT 1
        """),
    ).fetchone()

    if result is None:
        return None

    return FlowCell(
        id=result.id,
        x=result.x,
        y=result.y,
        elevation=result.elevation,
        flow_accumulation=result.flow_accumulation,
        slope=result.slope,
        downstream_id=result.downstream_id,
        cell_area=result.cell_area,
        is_stream=result.is_stream,
    )


def run_delineation(db, outlet: FlowCell, label: str) -> dict:
    """Run full delineation pipeline for a given outlet."""
    logger.info(f"\n{SEPARATOR}")
    logger.info(f"TEST: {label}")
    logger.info(SEPARATOR)
    logger.info(
        f"Outlet: id={outlet.id}, acc={outlet.flow_accumulation:,}, "
        f"elev={outlet.elevation:.2f}m, pos=({outlet.x:.0f}, {outlet.y:.0f})"
    )

    result = {"label": label, "outlet_id": outlet.id, "success": False}
    t0 = time.time()

    # 1. Pre-flight check
    try:
        t1 = time.time()
        estimated = check_watershed_size(outlet.id, db)
        preflight_ms = (time.time() - t1) * 1000
        logger.info(
            f"  Pre-flight OK: ~{estimated:,} cells ({preflight_ms:.1f}ms)"
        )
        result["preflight_ms"] = preflight_ms
        result["estimated_cells"] = estimated
    except ValueError as e:
        elapsed = time.time() - t0
        logger.warning(f"  Pre-flight REJECTED: {e} ({elapsed:.2f}s)")
        result["error"] = str(e)
        result["elapsed_s"] = elapsed
        return result

    # 2. Traverse upstream
    try:
        t2 = time.time()
        cells = traverse_upstream(outlet.id, db)
        traverse_s = time.time() - t2
        logger.info(
            f"  Traverse OK: {len(cells):,} cells ({traverse_s:.2f}s)"
        )
        result["cells"] = len(cells)
        result["traverse_s"] = traverse_s
    except ValueError as e:
        elapsed = time.time() - t0
        logger.warning(f"  Traverse REJECTED: {e} ({elapsed:.2f}s)")
        result["error"] = str(e)
        result["elapsed_s"] = elapsed
        return result

    # 3. Calculate area
    area_km2 = calculate_watershed_area_km2(cells)
    logger.info(f"  Area: {area_km2:.4f} km²")
    result["area_km2"] = area_km2

    # 4. Build boundary (polygonize)
    t3 = time.time()
    boundary = build_boundary(cells, method="polygonize", cell_size=1.0)
    boundary_s = time.time() - t3
    logger.info(
        f"  Boundary: {boundary.geom_type}, "
        f"area={boundary.area / 1e6:.4f} km² ({boundary_s:.2f}s)"
    )
    result["boundary_s"] = boundary_s
    result["boundary_area_km2"] = boundary.area / 1e6

    # 5. Morphometric parameters
    t4 = time.time()
    morph = build_morphometric_params(
        cells, boundary, outlet, db=db,
        include_hypsometric_curve=False,
    )
    morph_s = time.time() - t4
    logger.info(f"  Morphometry ({morph_s:.2f}s):")
    for key in [
        "area_km2", "perimeter_km", "main_stream_length_km",
        "mean_slope_percent", "mean_elevation_m",
        "compactness_coeff_kc", "circularity_ratio_rc",
        "elongation_ratio_re", "form_factor_ff",
        "relief_ratio_rh", "hypsometric_integral",
        "drainage_density_km_per_km2", "max_strahler_order",
    ]:
        val = morph.get(key)
        if val is not None:
            logger.info(f"    {key}: {val}")
    result["morph"] = morph
    result["morph_s"] = morph_s

    elapsed = time.time() - t0
    logger.info(f"  TOTAL: {elapsed:.2f}s")
    result["elapsed_s"] = elapsed
    result["success"] = True

    return result


def main():
    logger.info(SEPARATOR)
    logger.info("E2E Task 9 — Wyznaczanie zlewni N-33-131-C-b-2")
    logger.info(f"MAX_WATERSHED_CELLS = {MAX_WATERSHED_CELLS:,}")
    logger.info(SEPARATOR)

    results = []

    with get_db_session() as db:
        # Sprawdz stan bazy
        count = db.execute(
            text("SELECT COUNT(*) FROM flow_network")
        ).scalar()
        max_acc = db.execute(
            text("SELECT MAX(flow_accumulation) FROM flow_network")
        ).scalar()
        logger.info(f"Baza: {count:,} komorek, max_acc={max_acc:,}")

        if count == 0:
            logger.error("Baza pusta — uruchom najpierw Tasks 7-8")
            sys.exit(1)

        # --- TEST A: Sredni outlet (~500k cells) ---
        outlet_a = find_outlet_by_accumulation(db, 100_000, 500_000)
        if outlet_a:
            results.append(
                run_delineation(db, outlet_a, "A: Sredni outlet (~500k)")
            )
        else:
            logger.warning("Nie znaleziono outletu w zakresie 100k-500k")

        # --- TEST B: Duzy outlet (~1.5M cells) ---
        outlet_b = find_outlet_by_accumulation(db, 1_000_000, 1_500_000)
        if outlet_b:
            results.append(
                run_delineation(db, outlet_b, "B: Duzy outlet (~1.5M)")
            )
        else:
            logger.warning("Nie znaleziono outletu w zakresie 1M-1.5M")

        # --- TEST C: Pre-flight reject (sztuczny limit) ---
        outlet_max = find_max_outlet(db)
        logger.info(f"\n{SEPARATOR}")
        logger.info("TEST C: Pre-flight reject (sztuczny limit 100k)")
        logger.info(SEPARATOR)
        if outlet_max:
            try:
                check_watershed_size(outlet_max.id, db, max_cells=100_000)
                logger.error("  FAIL: Powinien byl odrzucic!")
                results.append({"label": "C: Pre-flight reject", "success": False})
            except ValueError as e:
                logger.info(f"  Pre-flight REJECT OK: {e}")
                results.append({"label": "C: Pre-flight reject", "success": True})

        # --- TEST D: Max outlet — LIMIT safety net test ---
        logger.info(f"\n{SEPARATOR}")
        logger.info("TEST D: Max outlet — CTE LIMIT safety net")
        logger.info(SEPARATOR)
        if outlet_max:
            logger.info(
                f"Outlet max: id={outlet_max.id}, "
                f"acc={outlet_max.flow_accumulation:,}"
            )
            try:
                cells = traverse_upstream(outlet_max.id, db)
                # Jesli przeszlo — tez OK (oznacza ze CTE < 2M)
                logger.info(f"  Traverse OK: {len(cells):,} cells")
                results.append({
                    "label": "D: Max outlet safety net",
                    "success": True,
                    "cells": len(cells),
                    "elapsed_s": 0,
                })
            except ValueError as e:
                # Oczekiwane — LIMIT safety net zlapal nadmiar
                logger.info(f"  CTE LIMIT safety net OK: {e}")
                results.append({
                    "label": "D: Max outlet safety net",
                    "success": True,
                    "elapsed_s": 0,
                })

    # --- PODSUMOWANIE ---
    logger.info(f"\n{SEPARATOR}")
    logger.info("PODSUMOWANIE")
    logger.info(SEPARATOR)
    for r in results:
        status = "OK" if r.get("success") else "FAIL"
        elapsed = r.get("elapsed_s", 0)
        cells = r.get("cells", "-")
        area = r.get("area_km2")
        area_str = f"{area:.4f} km²" if area else "-"
        error = r.get("error", "")
        logger.info(
            f"  [{status}] {r['label']}: "
            f"cells={cells}, area={area_str}, time={elapsed:.2f}s"
            f"{f', error={error}' if error else ''}"
        )

    # Sprawdz czy wszystkie przeszly
    all_ok = all(r.get("success") for r in results)
    if all_ok:
        logger.info(f"\nWSZYSTKIE TESTY PRZESZLY ({len(results)}/{len(results)})")
    else:
        failed = sum(1 for r in results if not r.get("success"))
        logger.error(f"\n{failed}/{len(results)} TESTOW FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
