"""
Kalkulator CN z wykorzystaniem danych z Kartografa.

Integruje:
- HSGCalculator (SoilGrids) - grupy hydrologiczne gleby
- LandCoverManager (BDOT10k/CORINE) - pokrycie terenu

Oblicza CN na podstawie kombinacji HSG i pokrycia terenu.
"""

import logging
import re
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


# Mapowanie kodow BDOT10k na kategorie pokrycia terenu.
# Zgodne z BDOT10K_MAPPING w scripts/import_landcover.py,
# ale z kluczami uzywanymi w CN_LOOKUP_TABLE (nazwy angielskie).
BDOT10K_CATEGORY_MAP: dict[str, str] = {
    "PTLZ": "forest",
    "PTTR": "arable",
    "PTUT": "arable",
    "PTWP": "water",
    "PTWZ": "meadow",
    "PTRK": "meadow",
    "PTZB": "urban_residential",
    "PTKM": "road",
    "PTPL": "road",
    "PTGN": "other",
    "PTNZ": "other",
    "PTSO": "other",
}


def _extract_bdot_code(layer_name: str) -> str | None:
    """
    Wyciagnij kod BDOT10k (PT*) z nazwy warstwy GeoPackage.

    Obsługuje formaty:
    - "OT_PTLZ_A" -> "PTLZ"
    - "PTLZ" -> "PTLZ"
    - "OT_PTTR_L" -> "PTTR"
    - "some_other_layer" -> None

    Parameters
    ----------
    layer_name : str
        Nazwa warstwy z GeoPackage

    Returns
    -------
    str | None
        Kod BDOT10k (np. "PTLZ") lub None jesli nie znaleziono
    """
    match = re.search(r"(?:^|_)(PT[A-Z]{2})(?:_|$)", layer_name.upper())
    if match:
        return match.group(1)
    return None


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
            return _analyze_land_cover_gpkg(lc_path, bbox)

    except Exception as e:
        logger.warning(f"Blad pobierania pokrycia terenu: {e}")

    return {}


def _analyze_land_cover_gpkg(
    gpkg_path: Path,
    bbox: "BBox",
) -> dict[str, float]:
    """
    Analizuj plik GeoPackage z pokryciem terenu BDOT10k.

    Czyta warstwy PT* z pliku, intersektuje z bbox i oblicza
    procentowy udzial kazdej kategorii pokrycia terenu.

    Parameters
    ----------
    gpkg_path : Path
        Sciezka do pliku GeoPackage
    bbox : BBox
        Bounding box w EPSG:2180

    Returns
    -------
    Dict[str, float]
        Statystyki pokrycia {kategoria: procent}
    """
    try:
        import fiona
        import geopandas as gpd
        from shapely.geometry import box

        available_layers = fiona.listlayers(str(gpkg_path))
        logger.info(f"Warstwy w GeoPackage: {available_layers}")

        bbox_geom = box(bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y)

        # Zbierz powierzchnie per kategoria
        category_areas: dict[str, float] = {}

        for layer_name in available_layers:
            bdot_code = _extract_bdot_code(layer_name)
            if bdot_code is None:
                continue

            category = BDOT10K_CATEGORY_MAP.get(bdot_code)
            if category is None:
                logger.debug(f"Pominieto nieznany kod BDOT10k: {bdot_code}")
                continue

            try:
                gdf = gpd.read_file(str(gpkg_path), layer=layer_name)
            except Exception as e:
                logger.warning(f"Blad odczytu warstwy {layer_name}: {e}")
                continue

            if gdf.empty:
                continue

            # Transformuj do EPSG:2180 jesli trzeba
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:2180")
            elif gdf.crs.to_epsg() != 2180:
                gdf = gdf.to_crs("EPSG:2180")

            # Clip do bbox
            clipped = gpd.clip(gdf, bbox_geom)
            if clipped.empty:
                continue

            # Sumuj powierzchnie
            layer_area = clipped.geometry.area.sum()
            if layer_area > 0:
                category_areas[category] = (
                    category_areas.get(category, 0.0) + layer_area
                )

        if not category_areas:
            logger.warning("Brak danych pokrycia terenu w bbox")
            return {}

        # Przelicz na procenty
        total_area = sum(category_areas.values())
        stats: dict[str, float] = {}
        for category, area in category_areas.items():
            pct = round((area / total_area) * 100, 1)
            if pct > 0:
                stats[category] = pct

        logger.info(f"Statystyki pokrycia terenu: {stats}")
        return stats

    except Exception as e:
        logger.warning(f"Blad analizy GeoPackage: {e}")
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
        logger.error("Blad obliczania CN z Kartografa: %s", e, exc_info=True)
        return None
