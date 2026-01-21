#!/usr/bin/env python3
"""
Kompleksowy skrypt do analizy hydrologicznej zlewni.

Workflow:
1. Pobieranie NMT z GUGiK (Kartograf)
2. Tworzenie mozaiki i przetwarzanie (pysheds)
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
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

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

    # Parametry hydrologiczne
    cn: Optional[int] = None  # CN (None = oblicz z land_cover lub użyj 75)
    default_cn: int = 75  # Domyślny CN gdy brak danych

    # Parametry opadu (IMGW PMAXTP)
    probability: float = 1.0  # Prawdopodobieństwo [%]: 1, 2, 5, 10, 20, 50
    duration_min: int = 60  # Czas trwania opadu [min]: 5, 10, 15, 30, 45, 60, ...

    # Scenariusze opadowe do analizy (jeśli None, użyj IMGW)
    precipitation_scenarios_mm: Optional[List[float]] = None

    # Metoda czasu koncentracji
    tc_method: str = "kirpich"  # kirpich, scs, giandotti

    # Parametry przetwarzania
    stream_threshold: int = 100  # Próg akumulacji dla cieków
    max_cells: int = 5_000_000  # Maksymalna liczba komórek zlewni
    timestep_min: float = 5.0  # Krok czasowy hydrogramu [min]

    # Ścieżki
    data_dir: Path = Path("../data")
    output_dir: Path = Path("../data/results")

    # Flagi
    download_dem: bool = False  # Pobierz NMT z GUGiK
    process_dem: bool = False  # Przetwórz NMT i zaimportuj do DB
    generate_plots: bool = True  # Generuj wizualizacje
    save_json: bool = True  # Zapisz wyniki do JSON
    use_kartograf_cn: bool = True  # Używaj Kartografa do obliczania CN

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)


# =============================================================================
# GŁÓWNE FUNKCJE
# =============================================================================

def download_nmt_data(config: AnalysisConfig) -> List[Path]:
    """Pobierz dane NMT z GUGiK."""
    logger.info("=" * 60)
    logger.info("KROK 1: Pobieranie NMT z GUGiK")
    logger.info("=" * 60)

    from scripts.download_dem import download_for_point

    nmt_dir = config.data_dir / "nmt"
    nmt_dir.mkdir(parents=True, exist_ok=True)

    downloaded = download_for_point(
        lat=config.latitude,
        lon=config.longitude,
        buffer_km=config.buffer_km,
        output_dir=nmt_dir,
        scale=config.scale,
    )

    logger.info(f"Pobrano {len(downloaded)} arkuszy NMT")
    return downloaded


def process_nmt_data(config: AnalysisConfig, input_files: List[Path]) -> Dict:
    """Przetwórz NMT i zaimportuj do bazy danych."""
    logger.info("=" * 60)
    logger.info("KROK 2: Przetwarzanie NMT")
    logger.info("=" * 60)

    from utils.raster_utils import create_vrt_mosaic
    from scripts.process_dem import process_dem

    # Utwórz mozaikę
    mosaic_path = config.data_dir / "nmt" / "mosaic.tif"
    mosaic_path = create_vrt_mosaic(input_files, mosaic_path)
    logger.info(f"Utworzono mozaikę: {mosaic_path}")

    # Przetwórz i zaimportuj
    stats = process_dem(
        input_path=mosaic_path,
        stream_threshold=config.stream_threshold,
        clear_existing=True,
    )

    logger.info(f"Zaimportowano {stats.get('records_inserted', 0):,} rekordów")
    return stats


# =============================================================================
# TABELE CN DLA RÓŻNYCH POKRYĆ TERENU I GRUP HSG
# =============================================================================

# Standard SCS CN lookup table: land_cover -> {HSG: CN}
CN_LOOKUP_TABLE = {
    # Lasy i tereny leśne
    "forest": {"A": 30, "B": 55, "C": 70, "D": 77},
    "las": {"A": 30, "B": 55, "C": 70, "D": 77},
    "PTLZ": {"A": 30, "B": 55, "C": 70, "D": 77},  # BDOT10k: lasy i zagajniki
    # Łąki i pastwiska
    "meadow": {"A": 30, "B": 58, "C": 71, "D": 78},
    "łąka": {"A": 30, "B": 58, "C": 71, "D": 78},
    "PTZB": {"A": 30, "B": 58, "C": 71, "D": 78},  # BDOT10k: zakrzewienia
    # Grunty orne
    "arable": {"A": 72, "B": 81, "C": 88, "D": 91},
    "grunt_orny": {"A": 72, "B": 81, "C": 88, "D": 91},
    "PTUT": {"A": 72, "B": 81, "C": 88, "D": 91},  # BDOT10k: uprawy trwałe
    "PTRK": {"A": 72, "B": 81, "C": 88, "D": 91},  # BDOT10k: roślinność krzewiasta
    # Zabudowa mieszkaniowa
    "urban_residential": {"A": 77, "B": 85, "C": 90, "D": 92},
    "zabudowa_mieszkaniowa": {"A": 77, "B": 85, "C": 90, "D": 92},
    "BUBD": {"A": 77, "B": 85, "C": 90, "D": 92},  # BDOT10k: budynki
    # Zabudowa przemysłowa/komercyjna
    "urban_commercial": {"A": 89, "B": 92, "C": 94, "D": 95},
    "zabudowa_przemysłowa": {"A": 89, "B": 92, "C": 94, "D": 95},
    "BUIN": {"A": 89, "B": 92, "C": 94, "D": 95},  # BDOT10k: budynki przemysłowe
    # Drogi i utwardzone powierzchnie
    "road": {"A": 98, "B": 98, "C": 98, "D": 98},
    "droga": {"A": 98, "B": 98, "C": 98, "D": 98},
    "SKDR": {"A": 98, "B": 98, "C": 98, "D": 98},  # BDOT10k: drogi
    "SKJZ": {"A": 98, "B": 98, "C": 98, "D": 98},  # BDOT10k: jezdnie
    # Wody
    "water": {"A": 100, "B": 100, "C": 100, "D": 100},
    "woda": {"A": 100, "B": 100, "C": 100, "D": 100},
    "PTWP": {"A": 100, "B": 100, "C": 100, "D": 100},  # BDOT10k: wody
    "SWRS": {"A": 100, "B": 100, "C": 100, "D": 100},  # BDOT10k: rzeki
    # CORINE klasy (2-digit codes)
    "11": {"A": 89, "B": 92, "C": 94, "D": 95},  # Urban fabric
    "12": {"A": 89, "B": 92, "C": 94, "D": 95},  # Industrial
    "13": {"A": 98, "B": 98, "C": 98, "D": 98},  # Mines/dumps
    "14": {"A": 49, "B": 69, "C": 79, "D": 84},  # Artificial green
    "21": {"A": 72, "B": 81, "C": 88, "D": 91},  # Arable land
    "22": {"A": 72, "B": 81, "C": 88, "D": 91},  # Permanent crops
    "23": {"A": 39, "B": 61, "C": 74, "D": 80},  # Pastures
    "24": {"A": 62, "B": 71, "C": 78, "D": 81},  # Heterogeneous agri
    "31": {"A": 30, "B": 55, "C": 70, "D": 77},  # Forests
    "32": {"A": 30, "B": 58, "C": 71, "D": 78},  # Shrub/herbaceous
    "33": {"A": 77, "B": 86, "C": 91, "D": 94},  # Open spaces
    "41": {"A": 100, "B": 100, "C": 100, "D": 100},  # Inland wetlands
    "42": {"A": 100, "B": 100, "C": 100, "D": 100},  # Coastal wetlands
    "51": {"A": 100, "B": 100, "C": 100, "D": 100},  # Inland waters
    "52": {"A": 100, "B": 100, "C": 100, "D": 100},  # Marine waters
    # Domyślne
    "other": {"A": 60, "B": 70, "C": 80, "D": 85},
    "inny": {"A": 60, "B": 70, "C": 80, "D": 85},
    "unknown": {"A": 60, "B": 70, "C": 80, "D": 85},
}


def calculate_cn_from_kartograf(
    config: AnalysisConfig,
    boundary_wgs84: List[List[float]],
) -> Optional[Dict]:
    """
    Oblicz CN na podstawie danych z Kartografa (HSG + pokrycie terenu).

    Wykorzystuje:
    - HSGCalculator do pobrania grup hydrologicznych gleby z SoilGrids
    - LandCoverManager do pobrania pokrycia terenu z BDOT10k/CORINE

    Parameters
    ----------
    config : AnalysisConfig
        Konfiguracja analizy
    boundary_wgs84 : List[List[float]]
        Granica zlewni jako lista [lon, lat]

    Returns
    -------
    Optional[Dict]
        Słownik z CN i statystykami lub None jeśli błąd
    """
    logger.info("-" * 40)
    logger.info("Obliczanie CN z Kartografa (HSG + Land Cover)")
    logger.info("-" * 40)

    try:
        from kartograf import BBox, LandCoverManager
        from kartograf.hydrology import HSGCalculator
        import tempfile

        # Oblicz bbox z granicy zlewni
        lons = [p[0] for p in boundary_wgs84]
        lats = [p[1] for p in boundary_wgs84]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        # Konwersja do EPSG:2180
        from utils.geometry import transform_wgs84_to_pl1992
        sw = transform_wgs84_to_pl1992(min_lat, min_lon)
        ne = transform_wgs84_to_pl1992(max_lat, max_lon)

        # Dodaj mały bufor
        buffer_m = 100
        bbox = BBox(
            min_x=sw.x - buffer_m,
            min_y=sw.y - buffer_m,
            max_x=ne.x + buffer_m,
            max_y=ne.y + buffer_m,
            crs="EPSG:2180",
        )
        logger.info(f"Bbox: ({bbox.min_x:.0f}, {bbox.min_y:.0f}) - "
                    f"({bbox.max_x:.0f}, {bbox.max_y:.0f})")

        # 1. Oblicz HSG z SoilGrids
        logger.info("Pobieranie HSG z SoilGrids...")
        hsg_calc = HSGCalculator()

        with tempfile.TemporaryDirectory() as tmpdir:
            hsg_path = Path(tmpdir) / "hsg.tif"

            try:
                hsg_calc.calculate_hsg_by_bbox(bbox, hsg_path)
                hsg_stats = hsg_calc.get_hsg_statistics(hsg_path)
                logger.info(f"HSG rozkład: {hsg_stats}")

                # Dominujący HSG - obsłuż różne formaty wyniku
                if hsg_stats:
                    # Nowy format: {'A': {'count': N, 'percent': X}, ...}
                    # Stary format: {'A': X, 'B': Y, ...}
                    first_val = list(hsg_stats.values())[0]
                    if isinstance(first_val, dict):
                        # Nowy format - użyj 'percent' lub 'count'
                        dominant_hsg = max(
                            hsg_stats.items(),
                            key=lambda x: x[1].get('percent', x[1].get('count', 0))
                        )[0]
                    else:
                        # Stary format - wartość to procent
                        dominant_hsg = max(hsg_stats.items(), key=lambda x: x[1])[0]
                else:
                    dominant_hsg = "B"  # Domyślny
                    logger.warning("Brak danych HSG, przyjęto domyślnie: B")

            except Exception as e:
                logger.warning(f"Błąd pobierania HSG: {e}")
                dominant_hsg = "B"
                hsg_stats = {"B": 100.0}

        logger.info(f"Dominujący HSG: {dominant_hsg}")

        # 2. Pobierz pokrycie terenu (BDOT10k lub CORINE)
        logger.info("Pobieranie pokrycia terenu...")

        # Spróbuj BDOT10k najpierw
        land_cover_stats = {}
        try:
            lc_manager = LandCoverManager(
                output_dir=str(config.data_dir / "landcover"),
            )
            # Pobierz przez bbox
            lc_path = lc_manager.download_by_bbox(bbox)
            if lc_path:
                logger.info(f"Pobrano pokrycie terenu: {lc_path}")
                # TODO: Analiza pokrycia terenu z pliku
                # Na razie użyj uproszczonego podejścia
        except Exception as e:
            logger.warning(f"Błąd pobierania pokrycia terenu: {e}")

        # 3. Oblicz CN
        # Jeśli brak szczegółowych danych, użyj uproszczonej metody
        if not land_cover_stats:
            # Przyjmij typowe pokrycie dla Polski centralnej
            # (można rozszerzyć o analizę CORINE)
            land_cover_stats = {
                "arable": 50.0,  # Grunty orne
                "meadow": 25.0,  # Łąki
                "forest": 15.0,  # Lasy
                "urban_residential": 10.0,  # Zabudowa
            }
            logger.warning("Użyto szacunkowego pokrycia terenu")

        # Oblicz ważone CN
        weighted_cn = 0.0
        cn_details = []

        for land_cover, percentage in land_cover_stats.items():
            cn_values = CN_LOOKUP_TABLE.get(land_cover, CN_LOOKUP_TABLE["other"])
            cn = cn_values.get(dominant_hsg, cn_values.get("B", 75))
            weighted_cn += cn * (percentage / 100)

            cn_details.append({
                "land_cover": land_cover,
                "percentage": percentage,
                "hsg": dominant_hsg,
                "cn": cn,
            })

        final_cn = round(weighted_cn)
        final_cn = max(0, min(100, final_cn))  # Clamp to 0-100

        logger.info(f"Obliczone CN: {final_cn}")
        logger.info(f"Szczegóły: {cn_details}")

        return {
            "cn": final_cn,
            "method": "kartograf_hsg",
            "dominant_hsg": dominant_hsg,
            "hsg_stats": hsg_stats,
            "land_cover_stats": land_cover_stats,
            "cn_details": cn_details,
        }

    except ImportError as e:
        logger.warning(f"Kartograf niedostępny: {e}")
        return None
    except Exception as e:
        logger.warning(f"Błąd obliczania CN z Kartografa: {e}")
        import traceback
        traceback.print_exc()
        return None


def delineate_watershed(config: AnalysisConfig, db) -> Dict:
    """Wyznacz zlewnię dla punktu."""
    logger.info("=" * 60)
    logger.info("KROK 3: Wyznaczanie zlewni")
    logger.info("=" * 60)

    from shapely.geometry import Point
    from core.watershed import (
        find_nearest_stream,
        traverse_upstream,
        build_boundary,
        calculate_watershed_area_km2,
    )
    from utils.geometry import transform_wgs84_to_pl1992, transform_pl1992_to_wgs84

    # Transformacja współrzędnych
    point = transform_wgs84_to_pl1992(config.latitude, config.longitude)
    logger.info(f"Punkt: ({config.latitude}, {config.longitude}) WGS84")
    logger.info(f"Punkt: ({point.x:.1f}, {point.y:.1f}) EPSG:2180")

    # Znajdź najbliższą komórkę cieku
    start = time.time()
    outlet = find_nearest_stream(point, db, max_distance_m=500)

    if not outlet:
        raise ValueError("Nie znaleziono cieku w pobliżu punktu!")

    logger.info(f"Znaleziono outlet: ID={outlet.id}, acc={outlet.flow_accumulation:,}")

    # Wyznacz zlewnię (upstream traversal)
    cells = traverse_upstream(outlet.id, db, max_cells=config.max_cells)
    logger.info(f"Komórek w zlewni: {len(cells):,}")

    # Zbuduj granicę
    boundary = build_boundary(cells, method="convex")
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


def calculate_morphometry(
    config: AnalysisConfig,
    watershed: Dict,
    db
) -> Dict:
    """Oblicz parametry morfometryczne zlewni."""
    logger.info("=" * 60)
    logger.info("KROK 4: Obliczanie morfometrii")
    logger.info("=" * 60)

    from core.morphometry import build_morphometric_params

    # Określ CN - hierarchia źródeł:
    # 1. Jawnie podane w konfiguracji
    # 2. Z tabeli land_cover w bazie danych
    # 3. Z Kartografa (HSG + land cover)
    # 4. Wartość domyślna
    cn = config.cn
    cn_source = "config" if cn else None
    cn_details = None

    if cn is None:
        # Próba 1: Spróbuj obliczyć z land_cover w bazie danych
        try:
            from core.land_cover import calculate_weighted_cn, DEFAULT_CN
            cn_result = calculate_weighted_cn(watershed["boundary"], db)
            if isinstance(cn_result, tuple):
                cn_value, land_cover_stats = cn_result
            else:
                cn_value = cn_result
                land_cover_stats = {}

            # Sprawdź czy to prawdziwe dane czy domyślna wartość
            # (calculate_weighted_cn zwraca DEFAULT_CN gdy brak danych)
            if cn_value and land_cover_stats:
                cn = cn_value
                cn_source = "database_land_cover"
                logger.info(f"CN z bazy danych (land_cover): {cn}")
            else:
                logger.debug(f"Brak rzeczywistych danych land_cover (CN={cn_value})")
                cn = None
        except Exception as e:
            logger.debug(f"Błąd pobierania land_cover z bazy: {e}")
            cn = None

    if cn is None and config.use_kartograf_cn:
        # Próba 2: Oblicz z Kartografa (HSG + land cover)
        kartograf_result = calculate_cn_from_kartograf(
            config,
            watershed["boundary_wgs84"],
        )
        if kartograf_result and kartograf_result.get("cn"):
            cn = kartograf_result["cn"]
            cn_source = "kartograf_hsg"
            cn_details = kartograf_result
            logger.info(f"CN z Kartografa (HSG={kartograf_result.get('dominant_hsg')}): {cn}")

    if cn is None:
        # Próba 3: Użyj wartości domyślnej
        cn = config.default_cn
        cn_source = "default"
        logger.warning(f"Brak danych CN, użyto wartości domyślnej: {cn}")

    start = time.time()
    morph = build_morphometric_params(
        cells=watershed["cells"],
        boundary=watershed["boundary"],
        outlet=watershed["outlet"],
        cn=cn,
    )
    elapsed = time.time() - start

    logger.info(f"Długość cieku: {morph['channel_length_km']:.2f} km")
    logger.info(f"Spadek cieku: {morph['channel_slope_m_per_m']*100:.2f}%")
    logger.info(f"Wysokość średnia: {morph['elevation_mean_m']:.1f} m")
    logger.info(f"CN: {cn} (źródło: {cn_source})")
    logger.info(f"Czas obliczeń: {elapsed:.1f}s")

    morph["cn"] = cn
    morph["cn_source"] = cn_source
    if cn_details:
        morph["cn_details"] = cn_details
    morph["elapsed_s"] = elapsed

    return morph


def fetch_precipitation_imgw(config: AnalysisConfig) -> Dict:
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
        valid_durations = [5, 10, 15, 30, 45, 60, 90, 120, 180, 360, 720,
                          1080, 1440, 2160, 2880, 4320]

        # Znajdź najbliższy dostępny czas trwania
        duration_key = str(min(valid_durations,
                               key=lambda x: abs(x - config.duration_min)))
        if int(duration_key) != config.duration_min:
            logger.warning(
                f"Czas {config.duration_min}min niedostępny, "
                f"użyto {duration_key}min"
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
            prob_key = str(int(closest_prob)) if closest_prob == int(closest_prob) \
                       else str(closest_prob)
            logger.warning(f"Użyto najbliższego: {prob_key}%")

            P_ks = result.data.ks[duration_key][prob_key]
            P_sg = result.data.sg[duration_key][prob_key]
            P_rb = result.data.rb.get(duration_key, {}).get(prob_key)

        logger.info(f"Opad (metoda KS): {P_ks:.1f} mm")
        logger.info(f"Opad (metoda SG): {P_sg:.1f} mm")
        if P_rb:
            logger.info(f"Opad (metoda RB): {P_rb:.1f} mm")

        return {
            "source": "IMGW PMAXTP",
            "probability_percent": float(prob_key),
            "duration_min": int(duration_key),
            "precipitation_ks_mm": P_ks,
            "precipitation_sg_mm": P_sg,
            "precipitation_rb_mm": P_rb,
            "precipitation_mm": P_sg,  # SG jako domyślny
            "all_distributions": {
                "ks": P_ks,
                "sg": P_sg,
                "rb": P_rb,
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
    morph: Dict,
    precipitation: Optional[Dict],
) -> Dict:
    """Generuj hydrogram odpływu."""
    logger.info("=" * 60)
    logger.info("KROK 6: Generowanie hydrogramu")
    logger.info("=" * 60)

    from hydrolog.morphometry import WatershedParameters
    from hydrolog.runoff import SCSCN, SCSUnitHydrograph

    # Parametry zlewni - filtruj niestandardowe klucze
    excluded_keys = {'cn', 'cn_source', 'cn_details', 'elapsed_s', 'source', 'crs'}
    ws = WatershedParameters(**{k: v for k, v in morph.items()
                                if k not in excluded_keys})

    # Czas koncentracji
    tc_min = ws.calculate_tc(config.tc_method)
    logger.info(f"Tc ({config.tc_method}): {tc_min:.1f} min")

    # Model SCS-CN
    cn = morph["cn"]
    scs = SCSCN(cn=cn)

    # Unit hydrograph
    uh = SCSUnitHydrograph(
        area_km2=morph["area_km2"],
        tc_min=tc_min,
    )

    timestep = config.timestep_min
    t_peak = uh.time_to_peak(timestep)
    q_peak_unit = uh.peak_discharge(timestep)

    logger.info(f"Czas do szczytu: {t_peak:.1f} min")
    logger.info(f"Przepływ jednostkowy: {q_peak_unit:.3f} m³/s/mm")

    # Określ scenariusze opadowe
    if config.precipitation_scenarios_mm:
        P_values = config.precipitation_scenarios_mm
    elif precipitation:
        P_design = precipitation["precipitation_mm"]
        P_values = [P_design * 0.6, P_design * 0.8, P_design, P_design * 1.2, P_design * 1.5]
    else:
        P_values = [30, 40, 50, 60, 80, 100]

    # Oblicz scenariusze
    scenarios = []
    for P_mm in P_values:
        result = scs.effective_precipitation(P_mm)
        Q_mm = result.effective_mm
        Qmax = q_peak_unit * Q_mm

        scenarios.append({
            "P_mm": round(P_mm, 1),
            "Q_mm": round(Q_mm, 2),
            "Ia_mm": round(result.initial_abstraction_mm, 2),
            "Qmax_m3s": round(Qmax, 2),
        })
        logger.info(f"  P={P_mm:.0f}mm -> Q={Q_mm:.1f}mm, Qmax={Qmax:.2f}m³/s")

    # Generuj hydrogram dla opadu projektowego
    if precipitation:
        P_design = precipitation["precipitation_mm"]
    else:
        P_design = 50.0

    uh_result = uh.generate(timestep_min=timestep)
    runoff_result = scs.effective_precipitation(P_design)
    Q_design = runoff_result.effective_mm

    hydrograph_times = uh_result.times_min.tolist()
    hydrograph_q = (uh_result.ordinates_m3s * Q_design).tolist()

    return {
        "tc_method": config.tc_method,
        "tc_min": round(tc_min, 2),
        "time_to_peak_min": round(t_peak, 2),
        "unit_peak_m3s_mm": round(q_peak_unit, 4),
        "timestep_min": timestep,
        "cn": cn,
        "scenarios": scenarios,
        "design_storm": {
            "P_mm": round(P_design, 1),
            "Q_mm": round(Q_design, 2),
            "Qmax_m3s": round(max(hydrograph_q), 2),
            "time_min": [round(t, 1) for t in hydrograph_times],
            "Q_m3s": [round(q, 3) for q in hydrograph_q],
        },
        "precipitation_source": precipitation["source"] if precipitation else "manual",
    }


def generate_visualizations(
    config: AnalysisConfig,
    watershed: Dict,
    morph: Dict,
    hydrograph: Dict,
) -> List[Path]:
    """Generuj wizualizacje."""
    logger.info("=" * 60)
    logger.info("KROK 7: Generowanie wizualizacji")
    logger.info("=" * 60)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    output_files = []
    design = hydrograph["design_storm"]
    cn = hydrograph["cn"]
    area = morph["area_km2"]

    # 1. Hydrogram
    fig1, ax1 = plt.subplots(figsize=(12, 6))
    times = design["time_min"]
    Q = design["Q_m3s"]

    ax1.fill_between(times, Q, alpha=0.3, color='blue')
    ax1.plot(times, Q, 'b-', lw=2, label=f'P={design["P_mm"]}mm')
    ax1.axvline(hydrograph["time_to_peak_min"], color='red', ls='--',
                alpha=0.7, label=f'Tp={hydrograph["time_to_peak_min"]:.0f}min')
    ax1.axhline(design["Qmax_m3s"], color='green', ls=':',
                alpha=0.7, label=f'Qmax={design["Qmax_m3s"]:.2f}m³/s')

    ax1.set_xlabel('Czas [min]', fontsize=11)
    ax1.set_ylabel('Przepływ Q [m³/s]', fontsize=11)
    ax1.set_title(f'Hydrogram SCS | A={area:.2f}km², CN={cn}, P={design["P_mm"]}mm',
                  fontsize=12)
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, max(times))

    path1 = config.output_dir / "hydrograph.png"
    fig1.savefig(path1, dpi=150, bbox_inches='tight')
    output_files.append(path1)
    logger.info(f"  ✅ {path1.name}")

    # 2. Qmax vs P
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    scenarios = hydrograph["scenarios"]
    P_vals = [s['P_mm'] for s in scenarios]
    Q_vals = [s['Qmax_m3s'] for s in scenarios]

    ax2.bar(P_vals, Q_vals, width=max(P_vals)*0.08, color='steelblue', edgecolor='navy')
    for p, q in zip(P_vals, Q_vals):
        ax2.text(p, q + max(Q_vals)*0.02, f'{q:.1f}', ha='center', fontsize=10)

    ax2.set_xlabel('Opad P [mm]', fontsize=11)
    ax2.set_ylabel('Qmax [m³/s]', fontsize=11)
    ax2.set_title(f'Qmax vs Opad | A={area:.2f}km², CN={cn}', fontsize=12)
    ax2.grid(True, alpha=0.3, axis='y')

    path2 = config.output_dir / "qmax_scenarios.png"
    fig2.savefig(path2, dpi=150, bbox_inches='tight')
    output_files.append(path2)
    logger.info(f"  ✅ {path2.name}")

    # 3. Profil + parametry
    fig3, (ax3a, ax3b) = plt.subplots(1, 2, figsize=(14, 5))

    elevations = np.array([c.elevation for c in watershed["cells"]])
    ax3a.hist(elevations, bins=50, color='saddlebrown', edgecolor='black', alpha=0.7)
    ax3a.axvline(morph['elevation_mean_m'], color='red', ls='--', lw=2,
                 label=f'Średnia: {morph["elevation_mean_m"]:.1f}m')
    ax3a.set_xlabel('Wysokość [m n.p.m.]', fontsize=11)
    ax3a.set_ylabel('Liczba komórek', fontsize=11)
    ax3a.set_title('Rozkład wysokości', fontsize=12)
    ax3a.legend()

    ax3b.axis('off')
    txt = f"""PARAMETRY ZLEWNI
{'─'*32}
Powierzchnia:     {morph['area_km2']:.2f} km²
Obwód:            {morph['perimeter_km']:.2f} km
Długość:          {morph['length_km']:.2f} km

Ciek główny:      {morph['channel_length_km']:.2f} km
Spadek cieku:     {morph['channel_slope_m_per_m']*100:.2f} %

Wys. min:         {morph['elevation_min_m']:.1f} m
Wys. max:         {morph['elevation_max_m']:.1f} m
Wys. średnia:     {morph['elevation_mean_m']:.1f} m

Średni spadek:    {morph['mean_slope_m_per_m']*100:.1f} %
CN:               {cn}
Tc ({hydrograph['tc_method']}):   {hydrograph['tc_min']:.1f} min"""

    ax3b.text(0.1, 0.5, txt, transform=ax3b.transAxes, fontsize=12,
              va='center', family='monospace',
              bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    path3 = config.output_dir / "watershed_profile.png"
    fig3.savefig(path3, dpi=150, bbox_inches='tight')
    output_files.append(path3)
    logger.info(f"  ✅ {path3.name}")

    # 4. Granica zlewni
    fig4, ax4 = plt.subplots(figsize=(10, 10))
    boundary = watershed["boundary"]
    x_coords = [c[0] for c in boundary.exterior.coords]
    y_coords = [c[1] for c in boundary.exterior.coords]

    ax4.fill(x_coords, y_coords, alpha=0.3, color='blue', edgecolor='navy', lw=2)

    from utils.geometry import transform_wgs84_to_pl1992
    point = transform_wgs84_to_pl1992(config.latitude, config.longitude)
    ax4.plot(point.x, point.y, 'ro', ms=12, label='Outlet', zorder=5)

    ax4.set_xlabel('X [m] EPSG:2180', fontsize=11)
    ax4.set_ylabel('Y [m] EPSG:2180', fontsize=11)
    ax4.set_title(f'Granica zlewni: {area:.2f} km²', fontsize=12)
    ax4.legend()
    ax4.set_aspect('equal')
    ax4.grid(True, alpha=0.3)

    path4 = config.output_dir / "watershed_boundary.png"
    fig4.savefig(path4, dpi=150, bbox_inches='tight')
    output_files.append(path4)
    logger.info(f"  ✅ {path4.name}")

    plt.close('all')

    return output_files


def save_results(
    config: AnalysisConfig,
    watershed: Dict,
    morph: Dict,
    precipitation: Optional[Dict],
    hydrograph: Dict,
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
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"Zapisano: {json_path}")
    return json_path


# =============================================================================
# GŁÓWNA FUNKCJA
# =============================================================================

def analyze_watershed(config: AnalysisConfig) -> Dict:
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
    if config.download_dem:
        downloaded_files = download_nmt_data(config)

        if config.process_dem and downloaded_files:
            process_nmt_data(config, downloaded_files)

    # Połącz z bazą danych
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.database import get_db
    db = next(get_db())

    try:
        # 1. Wyznacz zlewnię
        watershed = delineate_watershed(config, db)

        # 2. Oblicz morfometrię
        morph = calculate_morphometry(config, watershed, db)

        # 3. Pobierz dane opadowe z IMGW
        precipitation = fetch_precipitation_imgw(config)

        # 4. Generuj hydrogram
        hydrograph = generate_hydrograph(config, morph, precipitation)

        # 5. Generuj wizualizacje
        if config.generate_plots:
            plot_files = generate_visualizations(config, watershed, morph, hydrograph)

        # 6. Zapisz wyniki
        if config.save_json:
            json_path = save_results(config, watershed, morph, precipitation, hydrograph)

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
    loc.add_argument("--lat", type=float, required=True, help="Szerokość geograficzna (WGS84)")
    loc.add_argument("--lon", type=float, required=True, help="Długość geograficzna (WGS84)")
    loc.add_argument("--buffer", type=float, default=3.0, help="Bufor dla NMT [km] (default: 3)")

    # Parametry hydrologiczne
    hydro = parser.add_argument_group("Parametry hydrologiczne")
    hydro.add_argument("--cn", type=int, help="Wartość CN (default: z land_cover lub 75)")
    hydro.add_argument("--probability", "-p", type=float, default=1.0,
                       help="Prawdopodobieństwo opadu [%%] (default: 1)")
    hydro.add_argument("--duration", "-d", type=int, default=60,
                       help="Czas trwania opadu [min] (default: 60)")
    hydro.add_argument("--tc-method", choices=["kirpich", "scs", "giandotti"],
                       default="kirpich", help="Metoda czasu koncentracji")
    hydro.add_argument("--timestep", type=float, default=5.0,
                       help="Krok czasowy hydrogramu [min] (default: 5)")

    # Przetwarzanie
    proc = parser.add_argument_group("Przetwarzanie danych")
    proc.add_argument("--download", action="store_true", help="Pobierz dane NMT z GUGiK")
    proc.add_argument("--process", action="store_true", help="Przetwórz NMT i zaimportuj do DB")
    proc.add_argument("--stream-threshold", type=int, default=100,
                      help="Próg akumulacji dla cieków (default: 100)")

    # Wyjście
    out = parser.add_argument_group("Wyjście")
    out.add_argument("--output", "-o", type=str, default="../data/results",
                     help="Katalog wyjściowy (default: ../data/results)")
    out.add_argument("--no-plots", action="store_true", help="Nie generuj wykresów")
    out.add_argument("--no-json", action="store_true", help="Nie zapisuj JSON")
    out.add_argument("--no-kartograf-cn", action="store_true",
                     help="Nie używaj Kartografa do obliczania CN (HSG)")

    args = parser.parse_args()

    # Utwórz konfigurację
    config = AnalysisConfig(
        latitude=args.lat,
        longitude=args.lon,
        buffer_km=args.buffer,
        cn=args.cn,
        probability=args.probability,
        duration_min=args.duration,
        tc_method=args.tc_method,
        timestep_min=args.timestep,
        stream_threshold=args.stream_threshold,
        download_dem=args.download,
        process_dem=args.process,
        output_dir=Path(args.output),
        generate_plots=not args.no_plots,
        save_json=not args.no_json,
        use_kartograf_cn=not args.no_kartograf_cn,
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
