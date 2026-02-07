#!/usr/bin/env python3
"""
Kompleksowy skrypt do analizy hydrologicznej zlewni.

Workflow:
1. Pobieranie NMT z GUGiK (Kartograf)
2. Tworzenie mozaiki i przetwarzanie (pyflwdir)
3. Import do PostgreSQL
4. Wyznaczanie zlewni
5. Obliczanie parametrów morfometrycznych
6. Pobieranie danych opadowych z IMGW (IMGWTools)
7. Generowanie hydrogramu (Hydrolog)
8. Wizualizacje i eksport wyników

Użycie:
    cd backend
    python -m scripts.analyze_watershed --help
    python -m scripts.analyze_watershed --lat 52.45 --lon 17.31 --buffer 3

Przykłady:
    # Analiza dla punktu z domyślnymi parametrami
    python -m scripts.analyze_watershed --lat 52.454937 --lon 17.312501

    # Z niestandardowym CN i prawdopodobieństwem
    python -m scripts.analyze_watershed --lat 52.45 --lon 17.31 --cn 80 --probability 1

    # Pełny pipeline z pobieraniem danych
    python -m scripts.analyze_watershed --lat 52.45 --lon 17.31 --download --process
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# KONFIGURACJA - ZMIEŃ PARAMETRY TUTAJ
# =============================================================================


@dataclass
class AnalysisConfig:
    """Konfiguracja analizy hydrologicznej."""

    # Lokalizacja punktu zamknięcia (WGS84)
    latitude: float = 52.454937
    longitude: float = 17.312501

    # Parametry pobierania danych
    buffer_km: float = 3.0  # Bufor wokół punktu dla pobierania NMT
    scale: str = "1:10000"  # Skala mapy (1:10000, 1:25000, 1:50000)
    tiles: list[str] | None = None  # Lista godeł kafli NMT (zamiast buffer)

    # Parametry hydrologiczne
    cn: int | None = None  # CN (None = oblicz z land_cover lub użyj 75)
    default_cn: int = 75  # Domyślny CN gdy brak danych
    teryt: str | None = None  # Kod TERYT powiatu dla BDOT10k (4 cyfry)

    # Parametry opadu (IMGW PMAXTP)
    probability: float = 1.0  # Prawdopodobieństwo [%]: 1, 2, 5, 10, 20, 50
    duration_min: int = 60  # Czas trwania opadu [min]: 5, 10, 15, 30, 45, 60, ...

    # Scenariusze opadowe do analizy (jeśli None, użyj IMGW)
    precipitation_scenarios_mm: list[float] | None = None

    # Metoda czasu koncentracji
    tc_method: str = "kirpich"  # kirpich, scs, giandotti

    # Parametry przetwarzania
    stream_threshold: int = 100  # Próg akumulacji dla cieków
    max_cells: int = 10_000_000  # Maksymalna liczba komórek zlewni
    timestep_min: float = 5.0  # Krok czasowy hydrogramu [min]
    max_stream_distance_m: float = 500.0  # Maks. odległość szukania cieku [m]
    dem_resolution_m: float = 1.0  # Rozdzielczość DEM [m] (1.0 = oryginalna)

    # Ścieżki
    data_dir: Path = Path("../data")
    output_dir: Path = Path("../data/results")

    # Flagi
    download_dem: bool = False  # Pobierz NMT z GUGiK
    process_dem: bool = False  # Przetwórz NMT i zaimportuj do DB
    generate_plots: bool = True  # Generuj wizualizacje
    save_json: bool = True  # Zapisz wyniki do JSON
    use_kartograf_cn: bool = True  # Używaj Kartografa do obliczania CN
    save_qgis_layers: bool = False  # Zapisz warstwy pośrednie dla QGIS
    use_cached: bool = (
        False  # Użyj cache'owanych wyników (pomiń delineację i morfometrię)
    )

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)


# =============================================================================
# GŁÓWNE FUNKCJE
# =============================================================================


def download_nmt_data(config: AnalysisConfig) -> list[Path]:
    """Pobierz dane NMT z GUGiK."""
    logger.info("=" * 60)
    logger.info("KROK 1: Pobieranie NMT z GUGiK")
    logger.info("=" * 60)

    nmt_dir = config.data_dir / "nmt"
    nmt_dir.mkdir(parents=True, exist_ok=True)

    # Jeśli podano konkretne kafle, użyj ich
    if config.tiles:
        from scripts.download_dem import download_sheets

        logger.info(f"Pobieranie {len(config.tiles)} kafli: {config.tiles}")
        downloaded = download_sheets(config.tiles, nmt_dir)
    else:
        # Użyj bufora wokół punktu
        from scripts.download_dem import download_for_point

        downloaded = download_for_point(
            lat=config.latitude,
            lon=config.longitude,
            buffer_km=config.buffer_km,
            output_dir=nmt_dir,
            scale=config.scale,
        )

    logger.info(f"Pobrano {len(downloaded)} arkuszy NMT")
    return downloaded


def process_nmt_data(config: AnalysisConfig, input_files: list[Path]) -> dict:
    """Przetwórz NMT i zaimportuj do bazy danych."""
    logger.info("=" * 60)
    logger.info("KROK 2: Przetwarzanie NMT")
    logger.info("=" * 60)

    from scripts.process_dem import process_dem
    from utils.raster_utils import create_vrt_mosaic, resample_raster

    # Utwórz mozaikę
    mosaic_path = config.data_dir / "nmt" / "mosaic.tif"
    mosaic_path = create_vrt_mosaic(input_files, mosaic_path)
    logger.info(f"Utworzono mozaikę: {mosaic_path}")

    # Resample do zadanej rozdzielczości jeśli różna od 1m
    if config.dem_resolution_m > 1.0:
        resampled_path = (
            config.data_dir / "nmt" / f"mosaic_{int(config.dem_resolution_m)}m.tif"
        )
        mosaic_path = resample_raster(
            mosaic_path, resampled_path, config.dem_resolution_m, method="bilinear"
        )
        logger.info(f"Resamplowano do {config.dem_resolution_m}m: {mosaic_path}")

    # Katalog na rastery pośrednie (QGIS)
    qgis_dir = config.output_dir / "qgis" if config.save_qgis_layers else None
    if qgis_dir:
        qgis_dir.mkdir(parents=True, exist_ok=True)

    # Przetwórz i zaimportuj
    stats = process_dem(
        input_path=mosaic_path,
        stream_threshold=config.stream_threshold,
        clear_existing=True,
        save_intermediates=config.save_qgis_layers,
        output_dir=qgis_dir,
    )

    logger.info(f"Zaimportowano {stats.get('records_inserted', 0):,} rekordów")
    return stats


def delineate_watershed(config: AnalysisConfig, db) -> dict:
    """Wyznacz zlewnię dla punktu."""
    logger.info("=" * 60)
    logger.info("KROK 3: Wyznaczanie zlewni")
    logger.info("=" * 60)

    from core.watershed import (
        build_boundary,
        calculate_watershed_area_km2,
        find_nearest_stream,
        traverse_upstream,
    )
    from utils.geometry import transform_pl1992_to_wgs84, transform_wgs84_to_pl1992

    # Transformacja współrzędnych
    point = transform_wgs84_to_pl1992(config.latitude, config.longitude)
    logger.info(f"Punkt: ({config.latitude}, {config.longitude}) WGS84")
    logger.info(f"Punkt: ({point.x:.1f}, {point.y:.1f}) EPSG:2180")

    # Znajdź najbliższą komórkę cieku
    start = time.time()
    outlet = find_nearest_stream(point, db, max_distance_m=config.max_stream_distance_m)

    if not outlet:
        raise ValueError("Nie znaleziono cieku w pobliżu punktu!")

    logger.info(f"Znaleziono outlet: ID={outlet.id}, acc={outlet.flow_accumulation:,}")

    # Wyznacz zlewnię (upstream traversal)
    cells = traverse_upstream(outlet.id, db, max_cells=config.max_cells)
    logger.info(f"Komórek w zlewni: {len(cells):,}")

    # Zbuduj granicę (polygonize = dokładna granica śledząca komórki)
    # Oblicz rzeczywisty cell_size z cell_area (sqrt), nie z konfiguracji
    # (resampling może dać nieokrągłą wartość, np. 5.0015 zamiast 5.0)
    actual_cell_size = (cells[0].cell_area ** 0.5) if cells else config.dem_resolution_m
    boundary = build_boundary(cells, method="polygonize", cell_size=actual_cell_size)
    area_km2 = calculate_watershed_area_km2(cells)

    elapsed = time.time() - start
    logger.info(f"Powierzchnia: {area_km2:.2f} km²")
    logger.info(f"Czas delineacji: {elapsed:.1f}s")

    # Konwersja granicy do WGS84
    boundary_wgs84 = []
    for x, y in boundary.exterior.coords:
        lat, lon = transform_pl1992_to_wgs84(x, y)
        boundary_wgs84.append([lon, lat])

    return {
        "outlet": outlet,
        "cells": cells,
        "boundary": boundary,
        "boundary_wgs84": boundary_wgs84,
        "area_km2": area_km2,
        "cell_count": len(cells),
        "elapsed_s": elapsed,
    }


def calculate_morphometry(config: AnalysisConfig, watershed: dict, db) -> dict:
    """Oblicz parametry morfometryczne zlewni."""
    logger.info("=" * 60)
    logger.info("KROK 4: Obliczanie morfometrii")
    logger.info("=" * 60)

    from core.land_cover import determine_cn
    from core.morphometry import build_morphometric_params

    # Okresl CN - zunifikowana logika w determine_cn()
    cn, cn_source, cn_details = determine_cn(
        boundary=watershed["boundary"],
        db=db,
        config_cn=config.cn,
        default_cn=config.default_cn,
        use_kartograf=config.use_kartograf_cn,
        boundary_wgs84=watershed["boundary_wgs84"],
        data_dir=config.data_dir,
        teryt=config.teryt,
    )

    start = time.time()
    morph = build_morphometric_params(
        cells=watershed["cells"],
        boundary=watershed["boundary"],
        outlet=watershed["outlet"],
        cn=cn,
        include_stream_coords=config.save_qgis_layers,
    )
    elapsed = time.time() - start

    logger.info(f"Dlugosc cieku: {morph['channel_length_km']:.2f} km")
    logger.info(f"Spadek cieku: {morph['channel_slope_m_per_m'] * 100:.2f}%")
    logger.info(f"Wysokosc srednia: {morph['elevation_mean_m']:.1f} m")
    logger.info(f"CN: {cn} (zrodlo: {cn_source})")
    logger.info(f"Czas obliczen: {elapsed:.1f}s")

    morph["cn"] = cn
    morph["cn_source"] = cn_source
    if cn_details:
        morph["cn_details"] = cn_details
    morph["elapsed_s"] = elapsed

    return morph


def fetch_precipitation_imgw(config: AnalysisConfig) -> dict:
    """
    Pobierz dane opadowe z IMGW PMAXTP.

    Struktura danych PMAXTP:
    - result.data.ks - rozkład Krajowy Standard (KS)
    - result.data.sg - rozkład SQRT-ET max (SG)
    - result.data.rb - rozkład Bogdanowicza-Stachý (RB)

    Dostępne czasy trwania [min]: 5, 10, 15, 30, 45, 60, 90, 120, 180, 360, 720,
                                   1080, 1440, 2160, 2880, 4320
    Dostępne prawdopodobieństwa [%]: 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5,
                                      1, 2, 3, 5, 10, 20, 30, 40, 50, 60, 70, 80,
                                      90, 95, 98, 98.5, 99, 99.5, 99.9
    """
    logger.info("=" * 60)
    logger.info("KROK 5: Pobieranie danych opadowych (IMGW)")
    logger.info("=" * 60)

    try:
        from imgwtools import fetch_pmaxtp

        logger.info(f"Punkt: ({config.latitude}, {config.longitude})")
        logger.info(f"Prawdopodobieństwo: {config.probability}%")
        logger.info(f"Czas trwania: {config.duration_min} min")

        # Pobierz dane PMAXTP
        result = fetch_pmaxtp(
            latitude=config.latitude,
            longitude=config.longitude,
        )

        # Dostępne czasy trwania w PMAXTP
        valid_durations = [
            5,
            10,
            15,
            30,
            45,
            60,
            90,
            120,
            180,
            360,
            720,
            1080,
            1440,
            2160,
            2880,
            4320,
        ]

        # Znajdź najbliższy dostępny czas trwania
        duration_key = str(
            min(valid_durations, key=lambda x: abs(x - config.duration_min))
        )
        if int(duration_key) != config.duration_min:
            logger.warning(
                f"Czas {config.duration_min}min niedostępny, użyto {duration_key}min"
            )

        # Formatuj klucz prawdopodobieństwa
        prob = config.probability
        if prob == int(prob):
            prob_key = str(int(prob))
        else:
            prob_key = str(prob)

        # Pobierz wartości dla wszystkich trzech rozkładów
        try:
            P_ks = result.data.ks[duration_key][prob_key]
            P_sg = result.data.sg[duration_key][prob_key]
            P_rb = result.data.rb.get(duration_key, {}).get(prob_key)
        except KeyError as e:
            logger.warning(f"Brak danych dla klucza {e}, sprawdzam dostępne...")
            # Wyświetl dostępne prawdopodobieństwa
            available_probs = list(result.data.ks.get(duration_key, {}).keys())
            logger.info(f"Dostępne prawdopodobieństwa: {available_probs[:10]}...")

            # Znajdź najbliższe prawdopodobieństwo
            prob_values = [float(p) for p in available_probs]
            closest_prob = min(prob_values, key=lambda x: abs(x - prob))
            prob_key = (
                str(int(closest_prob))
                if closest_prob == int(closest_prob)
                else str(closest_prob)
            )
            logger.warning(f"Użyto najbliższego: {prob_key}%")

            P_ks = result.data.ks[duration_key][prob_key]
            P_sg = result.data.sg[duration_key][prob_key]
            P_rb = result.data.rb.get(duration_key, {}).get(prob_key)

        # ks = kwantyle (quantiles) - właściwa wartość opadu
        # sg = górna granica przedziału ufności (upper confidence bounds)
        # rb = błędy estymacji (estimation errors)
        logger.info(f"Opad (kwantyl KS): {P_ks:.1f} mm")
        logger.info(f"Opad (górna granica SG): {P_sg:.1f} mm")
        if P_rb:
            logger.info(f"Błąd estymacji (RB): {P_rb:.1f} mm")

        return {
            "source": "IMGW PMAXTP",
            "probability_percent": float(prob_key),
            "duration_min": int(duration_key),
            "precipitation_ks_mm": P_ks,
            "precipitation_sg_mm": P_sg,
            "precipitation_rb_mm": P_rb,
            "precipitation_mm": P_ks,  # KS (kwantyl) jako wartość projektowa
            "all_distributions": {
                "ks": P_ks,  # kwantyl
                "sg": P_sg,  # górna granica przedziału ufności
                "rb": P_rb,  # błąd estymacji
            },
        }

    except ImportError:
        logger.warning("IMGWTools nie zainstalowane, użyto wartości domyślnych")
        return None
    except Exception as e:
        logger.warning(f"Błąd pobierania z IMGW: {e}")
        import traceback

        traceback.print_exc()
        return None


def generate_hydrograph(
    config: AnalysisConfig,
    morph: dict,
    precipitation: dict | None,
) -> dict:
    """Generuj hydrogram odpływu z konwolucją hietogramu.

    Dla krótkich opadów (duration <= tc) używa uproszczonego podejścia.
    Dla długich opadów (duration > tc) używa konwolucji z hietogramem Beta.
    """
    logger.info("=" * 60)
    logger.info("KROK 6: Generowanie hydrogramu")
    logger.info("=" * 60)

    from hydrolog.morphometry import WatershedParameters
    from hydrolog.precipitation import BetaHietogram
    from hydrolog.runoff import SCSCN, HydrographGenerator, SCSUnitHydrograph

    # Parametry zlewni - filtruj niestandardowe klucze
    excluded_keys = {
        "cn",
        "cn_source",
        "cn_details",
        "elapsed_s",
        "source",
        "crs",
        "main_stream_coords",  # Tylko dla QGIS, nie dla WatershedParameters
    }
    ws = WatershedParameters(
        **{k: v for k, v in morph.items() if k not in excluded_keys}
    )

    # Czas koncentracji
    tc_min = ws.calculate_tc(config.tc_method)
    logger.info(f"Tc ({config.tc_method}): {tc_min:.1f} min")

    # Model SCS-CN
    cn = morph["cn"]
    area_km2 = morph["area_km2"]
    timestep = config.timestep_min

    # Określ czas trwania opadu
    if precipitation:
        duration_min = precipitation.get("duration_min", config.duration_min)
        P_design = precipitation["precipitation_mm"]
    else:
        duration_min = config.duration_min
        P_design = 50.0

    logger.info(f"Czas trwania opadu: {duration_min} min")
    logger.info(f"Opad projektowy: {P_design:.1f} mm")

    # Dla długich opadów używamy konwolucji z hietogramem
    use_convolution = duration_min > tc_min
    if use_convolution:
        logger.info("Metoda: Konwolucja z hietogramem Beta (alpha=2, beta=5)")
    else:
        logger.info("Metoda: Opad chwilowy (duration <= tc)")

    # Unit hydrograph (do wyświetlania parametrów)
    uh = SCSUnitHydrograph(area_km2=area_km2, tc_min=tc_min)
    t_peak = uh.time_to_peak(timestep)
    q_peak_unit = uh.peak_discharge(timestep)

    logger.info(f"Czas do szczytu UH: {t_peak:.1f} min")
    logger.info(f"Przepływ jednostkowy UH: {q_peak_unit:.3f} m³/s/mm")

    # Określ scenariusze opadowe
    if config.precipitation_scenarios_mm:
        P_values = config.precipitation_scenarios_mm
    elif precipitation:
        P_values = [
            P_design * 0.6,
            P_design * 0.8,
            P_design,
            P_design * 1.2,
            P_design * 1.5,
        ]
    else:
        P_values = [30, 40, 50, 60, 80, 100]

    # Inicjalizuj generator hydrogramu (z konwolucją)
    generator = HydrographGenerator(
        area_km2=area_km2,
        cn=cn,
        tc_min=tc_min,
        uh_model="scs",
    )

    # Hietogram Beta (asymetryczny - alpha=2, beta=5) z maksimum na początku
    hietogram = BetaHietogram(alpha=2.0, beta=5.0)

    # Oblicz scenariusze
    scenarios = []
    for P_mm in P_values:
        if use_convolution:
            # Generuj hietogram i hydrogram z konwolucją
            precip_series = hietogram.generate(
                total_mm=P_mm,
                duration_min=duration_min,
                timestep_min=timestep,
            )
            result = generator.generate(precip_series)
            Qmax = result.peak_discharge_m3s
            Q_mm = result.total_effective_mm  # Całkowity odpływ efektywny [mm]
        else:
            # Uproszczona metoda dla krótkich opadów
            scs = SCSCN(cn=cn)
            eff_result = scs.effective_precipitation(P_mm)
            Q_mm = eff_result.effective_mm
            Qmax = q_peak_unit * Q_mm

        scenarios.append(
            {
                "P_mm": round(P_mm, 1),
                "Q_mm": round(Q_mm, 2),
                "Qmax_m3s": round(Qmax, 2),
            }
        )
        logger.info(f"  P={P_mm:.0f}mm -> Q={Q_mm:.1f}mm, Qmax={Qmax:.2f}m³/s")

    # Generuj pełny hydrogram dla opadu projektowego
    if use_convolution:
        precip_design = hietogram.generate(
            total_mm=P_design,
            duration_min=duration_min,
            timestep_min=timestep,
        )
        hydro_result = generator.generate(precip_design)
        # Wyniki z zagnieżdżonego obiektu hydrograph
        hydrograph_times = hydro_result.hydrograph.times_min.tolist()
        hydrograph_q = hydro_result.hydrograph.discharge_m3s.tolist()
        Q_design = hydro_result.total_effective_mm
        Qmax_design = hydro_result.peak_discharge_m3s
        time_to_peak_hydro = hydro_result.time_to_peak_min
    else:
        # Uproszczona metoda
        uh_result = uh.generate(timestep_min=timestep)
        scs = SCSCN(cn=cn)
        runoff_result = scs.effective_precipitation(P_design)
        Q_design = runoff_result.effective_mm
        hydrograph_times = uh_result.times_min.tolist()
        hydrograph_q = (uh_result.ordinates_m3s * Q_design).tolist()
        Qmax_design = max(hydrograph_q)
        time_to_peak_hydro = t_peak

    logger.info(
        f"Hydrogram: Qmax={Qmax_design:.2f} m³/s, czas do szczytu={time_to_peak_hydro:.1f} min"
    )

    return {
        "tc_method": config.tc_method,
        "tc_min": round(tc_min, 2),
        "time_to_peak_min": round(time_to_peak_hydro, 2),
        "unit_peak_m3s_mm": round(q_peak_unit, 4),
        "timestep_min": timestep,
        "cn": cn,
        "duration_min": duration_min,
        "method": "convolution" if use_convolution else "instantaneous",
        "hietogram": "Beta(2,2)" if use_convolution else None,
        "scenarios": scenarios,
        "design_storm": {
            "P_mm": round(P_design, 1),
            "Q_mm": round(Q_design, 2),
            "Qmax_m3s": round(Qmax_design, 2),
            "time_min": [round(t, 1) for t in hydrograph_times],
            "Q_m3s": [round(q, 3) for q in hydrograph_q],
        },
        "precipitation_source": precipitation["source"] if precipitation else "manual",
    }


def save_qgis_layers(
    config: AnalysisConfig,
    watershed: dict,
    morph: dict,
) -> dict[str, Path]:
    """
    Zapisz warstwy pośrednie w formatach GeoPackage/GeoTIFF dla QGIS.

    Parameters
    ----------
    config : AnalysisConfig
        Konfiguracja analizy
    watershed : Dict
        Wyniki delineacji zlewni
    morph : Dict
        Parametry morfometryczne

    Returns
    -------
    Dict[str, Path]
        Słownik ścieżek do zapisanych plików
    """
    logger.info("=" * 60)
    logger.info("Zapisywanie warstw QGIS")
    logger.info("=" * 60)

    import geopandas as gpd
    from shapely.geometry import LineString, Point

    qgis_dir = config.output_dir / "qgis"
    qgis_dir.mkdir(parents=True, exist_ok=True)

    output_files = {}
    crs = "EPSG:2180"

    # 1. Granica zlewni (polygon)
    boundary_gdf = gpd.GeoDataFrame(
        {"area_km2": [watershed["area_km2"]], "cell_count": [watershed["cell_count"]]},
        geometry=[watershed["boundary"]],
        crs=crs,
    )
    path = qgis_dir / "watershed_boundary.gpkg"
    boundary_gdf.to_file(path, driver="GPKG")
    output_files["boundary"] = path
    logger.info(f"  ✅ {path.name}")

    # 2. Komórki zlewni (punkty)
    cells_data = [
        {
            "id": c.id,
            "elevation": c.elevation,
            "flow_acc": c.flow_accumulation,
            "slope": c.slope,
            "is_stream": c.is_stream,
            "geometry": Point(c.x, c.y),
        }
        for c in watershed["cells"]
    ]
    cells_gdf = gpd.GeoDataFrame(cells_data, crs=crs)
    path = qgis_dir / "watershed_cells.gpkg"
    cells_gdf.to_file(path, driver="GPKG")
    output_files["cells"] = path
    logger.info(f"  ✅ {path.name}")

    # 3. Outlet (punkt)
    outlet = watershed["outlet"]
    outlet_gdf = gpd.GeoDataFrame(
        {
            "id": [outlet.id],
            "elevation": [outlet.elevation],
            "flow_acc": [outlet.flow_accumulation],
        },
        geometry=[Point(outlet.x, outlet.y)],
        crs=crs,
    )
    path = qgis_dir / "outlet.gpkg"
    outlet_gdf.to_file(path, driver="GPKG")
    output_files["outlet"] = path
    logger.info(f"  ✅ {path.name}")

    # 4. Ciek główny (linia) - jeśli mamy współrzędne
    if "main_stream_coords" in morph and morph["main_stream_coords"]:
        coords = morph["main_stream_coords"]
        if len(coords) >= 2:
            stream_gdf = gpd.GeoDataFrame(
                {
                    "length_km": [morph["channel_length_km"]],
                    "slope_m_per_m": [morph["channel_slope_m_per_m"]],
                },
                geometry=[LineString(coords)],
                crs=crs,
            )
            path = qgis_dir / "main_stream.gpkg"
            stream_gdf.to_file(path, driver="GPKG")
            output_files["main_stream"] = path
            logger.info(f"  ✅ {path.name}")

    # 5. Sieć cieków (linie) - wszystkie cieki z bazy danych
    try:
        stream_lines = extract_stream_network(qgis_dir, crs)
        if stream_lines:
            output_files["stream_network"] = stream_lines
            logger.info(f"  ✅ {stream_lines.name}")
    except Exception as e:
        logger.warning(f"Nie udało się wyeksportować sieci cieków: {e}")

    logger.info(f"Zapisano {len(output_files)} warstw do {qgis_dir}")
    return output_files


def extract_stream_network(output_dir: Path, crs: str = "EPSG:2180") -> Path | None:
    """
    Wyeksportuj całą sieć cieków jako warstwę wektorową.

    Tworzy linie przez śledzenie połączeń downstream dla wszystkich
    komórek ciekowych (is_stream=True).

    Parameters
    ----------
    output_dir : Path
        Katalog wyjściowy
    crs : str
        Układ współrzędnych

    Returns
    -------
    Path or None
        Ścieżka do pliku GeoPackage lub None jeśli brak cieków
    """
    import geopandas as gpd
    from shapely.geometry import LineString
    from sqlalchemy import text

    from core.database import get_db_session

    with get_db_session() as db:
        # Pobierz wszystkie komórki ciekowe z połączeniami downstream
        query = text("""
            SELECT
                s.id,
                ST_X(s.geom) as x,
                ST_Y(s.geom) as y,
                s.flow_accumulation,
                s.downstream_id,
                ST_X(d.geom) as downstream_x,
                ST_Y(d.geom) as downstream_y
            FROM flow_network s
            LEFT JOIN flow_network d ON s.downstream_id = d.id
            WHERE s.is_stream = TRUE
            ORDER BY s.flow_accumulation DESC
        """)

        results = db.execute(query).fetchall()

    if not results:
        logger.warning("Brak komórek ciekowych w bazie")
        return None

    # Twórz segmenty linii (każda komórka -> jej downstream)
    segments = []
    for row in results:
        if row.downstream_x is not None and row.downstream_y is not None:
            segments.append(
                {
                    "id": row.id,
                    "flow_acc": row.flow_accumulation,
                    "geometry": LineString(
                        [(row.x, row.y), (row.downstream_x, row.downstream_y)]
                    ),
                }
            )

    if not segments:
        logger.warning("Brak segmentów cieków do eksportu")
        return None

    logger.info(f"Created {len(segments):,} records")

    gdf = gpd.GeoDataFrame(segments, crs=crs)
    path = output_dir / "stream_network.gpkg"
    gdf.to_file(path, driver="GPKG")

    return path


def generate_visualizations(
    config: AnalysisConfig,
    watershed: dict,
    morph: dict,
    hydrograph: dict,
) -> list[Path]:
    """Generuj wizualizacje."""
    logger.info("=" * 60)
    logger.info("KROK 7: Generowanie wizualizacji")
    logger.info("=" * 60)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_files = []
    design = hydrograph["design_storm"]
    cn = hydrograph["cn"]
    area = morph["area_km2"]

    # 1. Hydrogram
    fig1, ax1 = plt.subplots(figsize=(12, 6))
    times = design["time_min"]
    Q = design["Q_m3s"]

    ax1.fill_between(times, Q, alpha=0.3, color="blue")
    ax1.plot(times, Q, "b-", lw=2, label=f"P={design['P_mm']}mm")
    ax1.axvline(
        hydrograph["time_to_peak_min"],
        color="red",
        ls="--",
        alpha=0.7,
        label=f"Tp={hydrograph['time_to_peak_min']:.0f}min",
    )
    ax1.axhline(
        design["Qmax_m3s"],
        color="green",
        ls=":",
        alpha=0.7,
        label=f"Qmax={design['Qmax_m3s']:.2f}m³/s",
    )

    ax1.set_xlabel("Czas [min]", fontsize=11)
    ax1.set_ylabel("Przepływ Q [m³/s]", fontsize=11)
    ax1.set_title(
        f"Hydrogram SCS | A={area:.2f}km², CN={cn}, P={design['P_mm']}mm", fontsize=12
    )
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, max(times))

    path1 = config.output_dir / "hydrograph.png"
    fig1.savefig(path1, dpi=150, bbox_inches="tight")
    output_files.append(path1)
    logger.info(f"  ✅ {path1.name}")

    # 2. Qmax vs P
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    scenarios = hydrograph["scenarios"]
    P_vals = [s["P_mm"] for s in scenarios]
    Q_vals = [s["Qmax_m3s"] for s in scenarios]

    ax2.bar(
        P_vals, Q_vals, width=max(P_vals) * 0.08, color="steelblue", edgecolor="navy"
    )
    for p, q in zip(P_vals, Q_vals):
        ax2.text(p, q + max(Q_vals) * 0.02, f"{q:.1f}", ha="center", fontsize=10)

    ax2.set_xlabel("Opad P [mm]", fontsize=11)
    ax2.set_ylabel("Qmax [m³/s]", fontsize=11)
    ax2.set_title(f"Qmax vs Opad | A={area:.2f}km², CN={cn}", fontsize=12)
    ax2.grid(True, alpha=0.3, axis="y")

    path2 = config.output_dir / "qmax_scenarios.png"
    fig2.savefig(path2, dpi=150, bbox_inches="tight")
    output_files.append(path2)
    logger.info(f"  ✅ {path2.name}")

    # 3. Profil + parametry
    fig3, (ax3a, ax3b) = plt.subplots(1, 2, figsize=(14, 5))

    elevations = np.array([c.elevation for c in watershed["cells"]])
    ax3a.hist(elevations, bins=50, color="saddlebrown", edgecolor="black", alpha=0.7)
    ax3a.axvline(
        morph["elevation_mean_m"],
        color="red",
        ls="--",
        lw=2,
        label=f"Średnia: {morph['elevation_mean_m']:.1f}m",
    )
    ax3a.set_xlabel("Wysokość [m n.p.m.]", fontsize=11)
    ax3a.set_ylabel("Liczba komórek", fontsize=11)
    ax3a.set_title("Rozkład wysokości", fontsize=12)
    ax3a.legend()

    ax3b.axis("off")
    txt = f"""PARAMETRY ZLEWNI
{"─" * 32}
Powierzchnia:     {morph["area_km2"]:.2f} km²
Obwód:            {morph["perimeter_km"]:.2f} km
Długość:          {morph["length_km"]:.2f} km

Ciek główny:      {morph["channel_length_km"]:.2f} km
Spadek cieku:     {morph["channel_slope_m_per_m"] * 100:.2f} %

Wys. min:         {morph["elevation_min_m"]:.1f} m
Wys. max:         {morph["elevation_max_m"]:.1f} m
Wys. średnia:     {morph["elevation_mean_m"]:.1f} m

Średni spadek:    {morph["mean_slope_m_per_m"] * 100:.1f} %
CN:               {cn}
Tc ({hydrograph["tc_method"]}):   {hydrograph["tc_min"]:.1f} min"""

    ax3b.text(
        0.1,
        0.5,
        txt,
        transform=ax3b.transAxes,
        fontsize=12,
        va="center",
        family="monospace",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )

    path3 = config.output_dir / "watershed_profile.png"
    fig3.savefig(path3, dpi=150, bbox_inches="tight")
    output_files.append(path3)
    logger.info(f"  ✅ {path3.name}")

    # 4. Granica zlewni
    fig4, ax4 = plt.subplots(figsize=(10, 10))
    boundary = watershed["boundary"]
    x_coords = [c[0] for c in boundary.exterior.coords]
    y_coords = [c[1] for c in boundary.exterior.coords]

    ax4.fill(x_coords, y_coords, alpha=0.3, color="blue", edgecolor="navy", lw=2)

    from utils.geometry import transform_wgs84_to_pl1992

    point = transform_wgs84_to_pl1992(config.latitude, config.longitude)
    ax4.plot(point.x, point.y, "ro", ms=12, label="Outlet", zorder=5)

    ax4.set_xlabel("X [m] EPSG:2180", fontsize=11)
    ax4.set_ylabel("Y [m] EPSG:2180", fontsize=11)
    ax4.set_title(f"Granica zlewni: {area:.2f} km²", fontsize=12)
    ax4.legend()
    ax4.set_aspect("equal")
    ax4.grid(True, alpha=0.3)

    path4 = config.output_dir / "watershed_boundary.png"
    fig4.savefig(path4, dpi=150, bbox_inches="tight")
    output_files.append(path4)
    logger.info(f"  ✅ {path4.name}")

    plt.close("all")

    return output_files


def save_results(
    config: AnalysisConfig,
    watershed: dict,
    morph: dict,
    precipitation: dict | None,
    hydrograph: dict,
) -> Path:
    """Zapisz wyniki do JSON."""
    logger.info("=" * 60)
    logger.info("KROK 8: Zapisywanie wyników")
    logger.info("=" * 60)

    results = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "version": "0.3.0",
            "input_point": {
                "latitude": config.latitude,
                "longitude": config.longitude,
            },
            "config": {
                "tc_method": config.tc_method,
                "stream_threshold": config.stream_threshold,
                "timestep_min": config.timestep_min,
            },
        },
        "watershed": {
            "area_km2": round(watershed["area_km2"], 4),
            "cell_count": watershed["cell_count"],
            "boundary_geojson": {
                "type": "Feature",
                "properties": {"area_km2": round(watershed["area_km2"], 2)},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [watershed["boundary_wgs84"]],
                },
            },
        },
        "morphometry": {
            k: round(v, 4) if isinstance(v, float) else v
            for k, v in morph.items()
            if k not in ["elapsed_s"]
        },
        "precipitation": precipitation,
        "hydrograph": hydrograph,
    }

    json_path = config.output_dir / "analysis_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"Zapisano: {json_path}")
    return json_path


def load_cached_results(config: AnalysisConfig) -> tuple[dict, dict]:
    """
    Załaduj cache'owane wyniki zlewni i morfometrii z poprzedniej analizy.

    Returns
    -------
    tuple[Dict, Dict]
        (watershed, morphometry) - dane potrzebne do ponownych obliczeń hydrologicznych
    """
    json_path = config.output_dir / "analysis_results.json"

    if not json_path.exists():
        raise FileNotFoundError(
            f"Brak pliku cache: {json_path}. "
            "Uruchom najpierw pełną analizę bez --use-cached."
        )

    logger.info(f"Ładowanie cache z: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # Walidacja - sprawdź czy punkt się zgadza
    cached_point = data.get("metadata", {}).get("input_point", {})
    cached_lat = cached_point.get("latitude")
    cached_lon = cached_point.get("longitude")

    if cached_lat != config.latitude or cached_lon != config.longitude:
        raise ValueError(
            f"Punkt w cache ({cached_lat}, {cached_lon}) nie zgadza się "
            f"z żądanym ({config.latitude}, {config.longitude}). "
            "Uruchom pełną analizę bez --use-cached."
        )

    watershed = data.get("watershed", {})
    morphometry = data.get("morphometry", {})

    if not watershed or not morphometry:
        raise ValueError("Cache nie zawiera danych watershed lub morphometry.")

    # Odtwórz boundary_wgs84 z GeoJSON (potrzebne do save_results)
    boundary_geojson = watershed.get("boundary_geojson", {})
    if boundary_geojson:
        geometry = boundary_geojson.get("geometry", {})
        coords = geometry.get("coordinates", [[]])
        watershed["boundary_wgs84"] = coords[0] if coords else []

    logger.info(f"  Powierzchnia: {watershed.get('area_km2', 'N/A'):.2f} km²")
    logger.info(f"  CN: {morphometry.get('cn', 'N/A')}")
    logger.info(
        f"  Długość cieku: {morphometry.get('channel_length_km', 'N/A'):.2f} km"
    )

    return watershed, morphometry


# =============================================================================
# GŁÓWNA FUNKCJA
# =============================================================================


def analyze_watershed(config: AnalysisConfig) -> dict:
    """
    Wykonaj pełną analizę hydrologiczną zlewni.

    Parameters
    ----------
    config : AnalysisConfig
        Konfiguracja analizy

    Returns
    -------
    dict
        Słownik z wynikami analizy
    """
    logger.info("=" * 60)
    logger.info("ANALIZA HYDROLOGICZNA ZLEWNI")
    logger.info("=" * 60)
    logger.info(f"Punkt: ({config.latitude}, {config.longitude})")
    logger.info(f"Prawdopodobieństwo: {config.probability}%")
    logger.info(f"Czas trwania opadu: {config.duration_min} min")
    logger.info("=" * 60)

    start_total = time.time()

    # Opcjonalnie: pobierz dane NMT
    downloaded_files = []
    if config.download_dem:
        downloaded_files = download_nmt_data(config)

    # Przetwórz NMT (jeśli --process)
    if config.process_dem:
        # Znajdź pliki NMT jeśli nie pobrano nowych
        if not downloaded_files:
            nmt_dir = config.data_dir / "nmt"
            downloaded_files = list(nmt_dir.glob("**/*.asc"))
            if not downloaded_files:
                downloaded_files = list(nmt_dir.glob("**/*.tif"))
            logger.info(f"Znaleziono {len(downloaded_files)} istniejących plików NMT")

        if downloaded_files:
            process_nmt_data(config, downloaded_files)
        else:
            logger.warning("Brak plików NMT do przetworzenia!")

    # Użyj cache lub oblicz od nowa
    if config.use_cached:
        # Załaduj dane z poprzedniej analizy
        logger.info("=" * 60)
        logger.info("UŻYCIE CACHE (pominięcie delineacji i morfometrii)")
        logger.info("=" * 60)
        watershed, morph = load_cached_results(config)
        db = None  # Nie potrzebujemy bazy danych
    else:
        # Połącz z bazą danych
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.database import get_db

        db = next(get_db())

    try:
        if not config.use_cached:
            # 1. Wyznacz zlewnię
            watershed = delineate_watershed(config, db)

            # 2. Oblicz morfometrię
            morph = calculate_morphometry(config, watershed, db)

        # 3. Pobierz dane opadowe z IMGW
        precipitation = fetch_precipitation_imgw(config)

        # 4. Generuj hydrogram
        hydrograph = generate_hydrograph(config, morph, precipitation)

        # 5. Zapisz warstwy QGIS (tylko przy pełnej analizie, nie z cache)
        if config.save_qgis_layers and not config.use_cached:
            save_qgis_layers(config, watershed, morph)
        elif config.save_qgis_layers and config.use_cached:
            logger.info("Pominięto zapis warstw QGIS (użyto cache, pliki już istnieją)")

        # 6. Generuj wizualizacje (tylko przy pełnej analizie)
        if config.generate_plots and not config.use_cached:
            generate_visualizations(config, watershed, morph, hydrograph)
        elif config.generate_plots and config.use_cached:
            logger.info("Pominięto wizualizacje (użyto cache)")

        # 7. Zapisz wyniki
        if config.save_json:
            save_results(config, watershed, morph, precipitation, hydrograph)

        elapsed_total = time.time() - start_total

        # Podsumowanie
        logger.info("=" * 60)
        logger.info("PODSUMOWANIE")
        logger.info("=" * 60)
        logger.info(f"Powierzchnia zlewni: {watershed['area_km2']:.2f} km²")
        logger.info(f"Długość cieku: {morph['channel_length_km']:.2f} km")
        logger.info(f"CN: {morph['cn']}")
        logger.info(f"Tc: {hydrograph['tc_min']:.1f} min")

        if precipitation:
            logger.info(f"Opad (IMGW): {precipitation['precipitation_mm']:.1f} mm")

        logger.info(f"Qmax: {hydrograph['design_storm']['Qmax_m3s']:.2f} m³/s")
        logger.info(f"Całkowity czas: {elapsed_total:.1f}s")
        logger.info("=" * 60)
        logger.info(f"Wyniki zapisane w: {config.output_dir}")

        return {
            "watershed": watershed,
            "morphometry": morph,
            "precipitation": precipitation,
            "hydrograph": hydrograph,
            "elapsed_s": elapsed_total,
        }

    finally:
        if db is not None:
            db.close()


# =============================================================================
# CLI
# =============================================================================


def main():
    """Główna funkcja CLI."""
    parser = argparse.ArgumentParser(
        description="Analiza hydrologiczna zlewni",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Lokalizacja
    loc = parser.add_argument_group("Lokalizacja")
    loc.add_argument(
        "--lat", type=float, required=True, help="Szerokość geograficzna (WGS84)"
    )
    loc.add_argument(
        "--lon", type=float, required=True, help="Długość geograficzna (WGS84)"
    )
    loc.add_argument(
        "--buffer", type=float, default=3.0, help="Bufor dla NMT [km] (default: 3)"
    )
    loc.add_argument(
        "--tiles", type=str, nargs="+", help="Lista godeł kafli NMT (zamiast --buffer)"
    )
    loc.add_argument(
        "--max-stream-distance",
        type=float,
        default=500.0,
        help="Maks. odległość szukania cieku [m] (default: 500)",
    )

    # Parametry hydrologiczne
    hydro = parser.add_argument_group("Parametry hydrologiczne")
    hydro.add_argument(
        "--cn", type=int, help="Wartość CN (default: z land_cover lub 75)"
    )
    hydro.add_argument(
        "--teryt", type=str, help="Kod TERYT powiatu dla BDOT10k (4 cyfry, np. 3021)"
    )
    hydro.add_argument(
        "--probability",
        "-p",
        type=float,
        default=1.0,
        help="Prawdopodobieństwo opadu [%%] (default: 1)",
    )
    hydro.add_argument(
        "--duration",
        "-d",
        type=int,
        default=60,
        help="Czas trwania opadu [min] (default: 60)",
    )
    hydro.add_argument(
        "--tc-method",
        choices=["kirpich", "scs", "giandotti"],
        default="kirpich",
        help="Metoda czasu koncentracji",
    )
    hydro.add_argument(
        "--timestep",
        type=float,
        default=5.0,
        help="Krok czasowy hydrogramu [min] (default: 5)",
    )

    # Przetwarzanie
    proc = parser.add_argument_group("Przetwarzanie danych")
    proc.add_argument(
        "--download", action="store_true", help="Pobierz dane NMT z GUGiK"
    )
    proc.add_argument(
        "--process", action="store_true", help="Przetwórz NMT i zaimportuj do DB"
    )
    proc.add_argument(
        "--stream-threshold",
        type=int,
        default=100,
        help="Próg akumulacji dla cieków (default: 100)",
    )
    proc.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="Rozdzielczość DEM [m] (default: 1.0 = oryginalna)",
    )

    # Wyjście
    out = parser.add_argument_group("Wyjście")
    out.add_argument(
        "--output",
        "-o",
        type=str,
        default="../data/results",
        help="Katalog wyjściowy (default: ../data/results)",
    )
    out.add_argument("--no-plots", action="store_true", help="Nie generuj wykresów")
    out.add_argument("--no-json", action="store_true", help="Nie zapisuj JSON")
    out.add_argument(
        "--no-kartograf-cn",
        action="store_true",
        help="Nie używaj Kartografa do obliczania CN (HSG)",
    )
    out.add_argument(
        "--save-qgis",
        action="store_true",
        help="Zapisz warstwy pośrednie do QGIS (GeoPackage/GeoTIFF)",
    )

    # Cache
    cache = parser.add_argument_group("Cache")
    cache.add_argument(
        "--use-cached",
        action="store_true",
        help="Użyj cache'owanych wyników zlewni i morfometrii (pomiń delineację)",
    )

    args = parser.parse_args()

    # Utwórz konfigurację
    config = AnalysisConfig(
        latitude=args.lat,
        longitude=args.lon,
        buffer_km=args.buffer,
        tiles=args.tiles,
        max_stream_distance_m=args.max_stream_distance,
        cn=args.cn,
        teryt=args.teryt,
        probability=args.probability,
        duration_min=args.duration,
        tc_method=args.tc_method,
        timestep_min=args.timestep,
        stream_threshold=args.stream_threshold,
        dem_resolution_m=args.resolution,
        download_dem=args.download,
        process_dem=args.process,
        output_dir=Path(args.output),
        generate_plots=not args.no_plots,
        save_json=not args.no_json,
        use_kartograf_cn=not args.no_kartograf_cn,
        save_qgis_layers=args.save_qgis,
        use_cached=args.use_cached,
    )

    # Uruchom analizę
    try:
        analyze_watershed(config)
    except Exception as e:
        logger.error(f"Błąd analizy: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
