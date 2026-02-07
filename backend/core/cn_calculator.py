"""
Kalkulator CN z wykorzystaniem danych z Kartografa.

Integruje:
- HSGCalculator (SoilGrids) - grupy hydrologiczne gleby
- LandCoverManager (BDOT10k/CORINE) - pokrycie terenu

Oblicza CN na podstawie kombinacji HSG i pokrycia terenu.
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kartograf import BBox

logger = logging.getLogger(__name__)


@dataclass
class CNCalculationResult:
    """
    Wynik obliczenia CN z Kartografa.

    Attributes
    ----------
    cn : int
        Obliczona wartosc CN (0-100)
    method : str
        Metoda obliczenia ('kartograf_hsg', 'fallback', etc.)
    dominant_hsg : str
        Dominujaca grupa HSG ('A', 'B', 'C', 'D')
    hsg_stats : Dict[str, float]
        Statystyki HSG {grupa: procent}
    land_cover_stats : Dict[str, float]
        Statystyki pokrycia {kategoria: procent}
    cn_details : List[Dict]
        Szczegoly obliczenia CN dla kazdej kategorii
    """

    cn: int
    method: str
    dominant_hsg: str
    hsg_stats: dict[str, float]
    land_cover_stats: dict[str, float]
    cn_details: list[dict]


def check_kartograf_available() -> bool:
    """
    Sprawdz czy Kartograf jest dostepny.

    Returns
    -------
    bool
        True jesli Kartograf jest zainstalowany
    """
    try:
        from kartograf import BBox  # noqa: F401
        from kartograf.hydrology import HSGCalculator  # noqa: F401

        return True
    except ImportError:
        return False


def convert_boundary_to_bbox(
    boundary_wgs84: list[list[float]],
    buffer_m: float = 100,
) -> "BBox":
    """
    Konwertuj granice zlewni WGS84 do BBox EPSG:2180.

    Parameters
    ----------
    boundary_wgs84 : List[List[float]]
        Granica jako lista [lon, lat]
    buffer_m : float, optional
        Bufor w metrach, domyslnie 100

    Returns
    -------
    BBox
        Obiekt BBox z Kartografa w EPSG:2180
    """
    from kartograf import BBox

    # Import lokalny aby uniknac circular imports
    from utils.geometry import transform_wgs84_to_pl1992

    lons = [p[0] for p in boundary_wgs84]
    lats = [p[1] for p in boundary_wgs84]

    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    sw = transform_wgs84_to_pl1992(min_lat, min_lon)
    ne = transform_wgs84_to_pl1992(max_lat, max_lon)

    return BBox(
        min_x=sw.x - buffer_m,
        min_y=sw.y - buffer_m,
        max_x=ne.x + buffer_m,
        max_y=ne.y + buffer_m,
        crs="EPSG:2180",
    )


def get_hsg_from_soilgrids(bbox: "BBox") -> tuple[str, dict[str, float]]:
    """
    Pobierz HSG z SoilGrids przez Kartograf HSGCalculator.

    Parameters
    ----------
    bbox : BBox
        Bounding box w EPSG:2180

    Returns
    -------
    Tuple[str, Dict[str, float]]
        (dominant_hsg, hsg_stats)
    """
    from kartograf.hydrology import HSGCalculator

    hsg_calc = HSGCalculator()

    with tempfile.TemporaryDirectory() as tmpdir:
        hsg_path = Path(tmpdir) / "hsg.tif"

        try:
            hsg_calc.calculate_hsg_by_bbox(bbox, hsg_path)
            hsg_stats = hsg_calc.get_hsg_statistics(hsg_path)
        except Exception as e:
            logger.warning(f"Blad pobierania HSG: {e}")
            return ("B", {"B": 100.0})

        if not hsg_stats:
            logger.warning("Brak danych HSG, przyjeto domyslnie: B")
            return ("B", {"B": 100.0})

        # Obsluga roznych formatow wyniku
        first_val = list(hsg_stats.values())[0]
        if isinstance(first_val, dict):
            # Nowy format: {'A': {'count': N, 'percent': X}, ...}
            dominant_hsg = max(
                hsg_stats.items(),
                key=lambda x: x[1].get("percent", x[1].get("count", 0)),
            )[0]
            # Normalizuj do prostego formatu
            hsg_stats = {k: v.get("percent", 0) for k, v in hsg_stats.items()}
        else:
            # Stary format: {'A': X, 'B': Y, ...}
            dominant_hsg = max(hsg_stats.items(), key=lambda x: x[1])[0]

        return (dominant_hsg, hsg_stats)


def get_land_cover_stats(
    bbox: "BBox",
    data_dir: Path,
    teryt: str | None = None,
) -> dict[str, float]:
    """
    Pobierz statystyki pokrycia terenu z BDOT10k/CORINE.

    Parameters
    ----------
    bbox : BBox
        Bounding box w EPSG:2180
    data_dir : Path
        Katalog na pobrane dane
    teryt : str, optional
        Kod TERYT powiatu (4 cyfry). Jeśli podany, używany zamiast
        automatycznego wykrywania (przydatne gdy punkt jest blisko
        granicy powiatu lub wykrywanie nie działa).

    Returns
    -------
    Dict[str, float]
        Statystyki pokrycia {kategoria: procent}
    """
    try:
        from kartograf import LandCoverManager

        lc_manager = LandCoverManager(output_dir=str(data_dir / "landcover"))

        if teryt:
            logger.info(f"Pobieranie BDOT10k dla TERYT: {teryt}")
            lc_path = lc_manager.download_by_teryt(teryt)
        else:
            lc_path = lc_manager.download_by_bbox(bbox)

        if lc_path:
            logger.info(f"Pobrano pokrycie terenu: {lc_path}")
            # TODO: Analiza pliku GeoPackage
            # Na razie zwracamy puste - fallback do domyslnych wartosci
            return {}

    except Exception as e:
        logger.warning(f"Blad pobierania pokrycia terenu: {e}")

    return {}


def get_default_land_cover_stats() -> dict[str, float]:
    """
    Zwroc domyslne statystyki pokrycia terenu.

    Bazowane na typowym pokryciu dla Polski centralnej.
    Uzywane gdy brak danych z Kartografa.

    Returns
    -------
    Dict[str, float]
        Domyslne statystyki {kategoria: procent}
    """
    return {
        "arable": 50.0,
        "meadow": 25.0,
        "forest": 15.0,
        "urban_residential": 10.0,
    }


def calculate_cn_from_kartograf(
    boundary_wgs84: list[list[float]],
    data_dir: Path,
    use_default_land_cover: bool = True,
    teryt: str | None = None,
) -> CNCalculationResult | None:
    """
    Oblicz CN na podstawie danych z Kartografa.

    Wykorzystuje HSGCalculator do pobrania grup hydrologicznych gleby
    z SoilGrids, oraz LandCoverManager do pobrania pokrycia terenu
    z BDOT10k/CORINE.

    Parameters
    ----------
    boundary_wgs84 : List[List[float]]
        Granica zlewni jako lista [lon, lat]
    data_dir : Path
        Katalog na pobrane dane
    use_default_land_cover : bool, optional
        Czy uzywac domyslnego pokrycia gdy brak danych, domyslnie True
    teryt : str, optional
        Kod TERYT powiatu (4 cyfry) do pobrania BDOT10k.
        Przydatny gdy automatyczne wykrywanie nie działa.

    Returns
    -------
    Optional[CNCalculationResult]
        Wynik obliczenia lub None jesli Kartograf niedostepny/blad

    Examples
    --------
    >>> boundary = [[17.31, 52.45], [17.32, 52.46], ...]
    >>> result = calculate_cn_from_kartograf(boundary, Path("./data"), teryt="3021")
    >>> if result:
    ...     print(f"CN = {result.cn}, HSG = {result.dominant_hsg}")
    """
    if not check_kartograf_available():
        logger.warning("Kartograf niedostepny")
        return None

    try:
        logger.info("-" * 40)
        logger.info("Obliczanie CN z Kartografa (HSG + Land Cover)")
        logger.info("-" * 40)

        # 1. Konwertuj granice do BBox
        bbox = convert_boundary_to_bbox(boundary_wgs84)
        logger.info(
            f"Bbox: ({bbox.min_x:.0f}, {bbox.min_y:.0f}) - "
            f"({bbox.max_x:.0f}, {bbox.max_y:.0f})"
        )

        # 2. Pobierz HSG
        logger.info("Pobieranie HSG z SoilGrids...")
        dominant_hsg, hsg_stats = get_hsg_from_soilgrids(bbox)
        logger.info(f"Dominujacy HSG: {dominant_hsg}")

        # 3. Pobierz pokrycie terenu
        logger.info("Pobieranie pokrycia terenu...")
        land_cover_stats = get_land_cover_stats(bbox, data_dir, teryt=teryt)

        if not land_cover_stats and use_default_land_cover:
            land_cover_stats = get_default_land_cover_stats()
            logger.warning("Uzyto szacunkowego pokrycia terenu")

        # 4. Oblicz wazony CN
        from core.cn_tables import (
            calculate_weighted_cn_from_stats,
            lookup_cn,
        )

        cn_details = []
        for land_cover, percentage in land_cover_stats.items():
            cn = lookup_cn(land_cover, dominant_hsg)
            cn_details.append(
                {
                    "land_cover": land_cover,
                    "percentage": percentage,
                    "hsg": dominant_hsg,
                    "cn": cn,
                }
            )

        final_cn = calculate_weighted_cn_from_stats(land_cover_stats, dominant_hsg)

        logger.info(f"Obliczone CN: {final_cn}")
        logger.info(f"Szczegoly: {cn_details}")

        return CNCalculationResult(
            cn=final_cn,
            method="kartograf_hsg",
            dominant_hsg=dominant_hsg,
            hsg_stats=hsg_stats,
            land_cover_stats=land_cover_stats,
            cn_details=cn_details,
        )

    except ImportError as e:
        logger.warning(f"Kartograf niedostepny: {e}")
        return None
    except Exception as e:
        logger.warning(f"Blad obliczania CN z Kartografa: {e}")
        import traceback

        traceback.print_exc()
        return None
