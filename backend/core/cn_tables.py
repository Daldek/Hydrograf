"""
Tabele CN (Curve Number) dla metody SCS-CN.

Zawiera:
- CN_LOOKUP_TABLE: mapowanie pokrycie terenu -> {HSG: CN}
- Funkcje lookup dla pojedynczych kategorii
- Mapowania pomiedzy roznymi klasyfikacjami (BDOT10k, CORINE, nazwy ogolne)

Zrodlo wartosci: SCS TR-55 (1986), dostosowane do warunkow polskich.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# ===========================================================================
# STALE
# ===========================================================================

# Domyslna wartosc CN gdy brak danych (srednie warunki)
DEFAULT_CN = 75

# Prawidlowe grupy hydrologiczne gleby (HSG)
VALID_HSG = frozenset(["A", "B", "C", "D"])

# ===========================================================================
# TABELA CN
# ===========================================================================

# Standard SCS CN lookup table: land_cover -> {HSG: CN}
# Klucze: BDOT10k (PTLZ, PTZB, ...), CORINE (11, 12, ...), nazwy ogolne
CN_LOOKUP_TABLE: Dict[str, Dict[str, int]] = {
    # === Lasy i tereny lesne ===
    "forest": {"A": 30, "B": 55, "C": 70, "D": 77},
    "las": {"A": 30, "B": 55, "C": 70, "D": 77},
    "PTLZ": {"A": 30, "B": 55, "C": 70, "D": 77},  # BDOT10k: lasy i zagajniki
    # === Laki i pastwiska ===
    "meadow": {"A": 30, "B": 58, "C": 71, "D": 78},
    "łąka": {"A": 30, "B": 58, "C": 71, "D": 78},
    "PTZB": {"A": 30, "B": 58, "C": 71, "D": 78},  # BDOT10k: zakrzewienia
    # === Grunty orne ===
    "arable": {"A": 72, "B": 81, "C": 88, "D": 91},
    "grunt_orny": {"A": 72, "B": 81, "C": 88, "D": 91},
    "PTUT": {"A": 72, "B": 81, "C": 88, "D": 91},  # BDOT10k: uprawy trwale
    "PTRK": {"A": 72, "B": 81, "C": 88, "D": 91},  # BDOT10k: roslinnosc krzewiasta
    # === Zabudowa mieszkaniowa ===
    "urban_residential": {"A": 77, "B": 85, "C": 90, "D": 92},
    "zabudowa_mieszkaniowa": {"A": 77, "B": 85, "C": 90, "D": 92},
    "BUBD": {"A": 77, "B": 85, "C": 90, "D": 92},  # BDOT10k: budynki
    # === Zabudowa przemyslowa ===
    "urban_commercial": {"A": 89, "B": 92, "C": 94, "D": 95},
    "zabudowa_przemysłowa": {"A": 89, "B": 92, "C": 94, "D": 95},
    "BUIN": {"A": 89, "B": 92, "C": 94, "D": 95},  # BDOT10k: budynki przemyslowe
    # === Drogi ===
    "road": {"A": 98, "B": 98, "C": 98, "D": 98},
    "droga": {"A": 98, "B": 98, "C": 98, "D": 98},
    "SKDR": {"A": 98, "B": 98, "C": 98, "D": 98},  # BDOT10k: drogi
    "SKJZ": {"A": 98, "B": 98, "C": 98, "D": 98},  # BDOT10k: jezdnie
    # === Wody ===
    "water": {"A": 100, "B": 100, "C": 100, "D": 100},
    "woda": {"A": 100, "B": 100, "C": 100, "D": 100},
    "PTWP": {"A": 100, "B": 100, "C": 100, "D": 100},  # BDOT10k: wody
    "SWRS": {"A": 100, "B": 100, "C": 100, "D": 100},  # BDOT10k: rzeki
    # === CORINE klasy (2-cyfrowe) ===
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
    # === Domyslne ===
    "other": {"A": 60, "B": 70, "C": 80, "D": 85},
    "inny": {"A": 60, "B": 70, "C": 80, "D": 85},
    "unknown": {"A": 60, "B": 70, "C": 80, "D": 85},
}


# ===========================================================================
# FUNKCJE
# ===========================================================================


def lookup_cn(
    land_cover: str,
    hsg: str,
    default_hsg: str = "B",
) -> int:
    """
    Pobierz wartosc CN dla pokrycia terenu i grupy HSG.

    Parameters
    ----------
    land_cover : str
        Kategoria pokrycia terenu (BDOT10k, CORINE lub nazwa ogolna)
    hsg : str
        Grupa hydrologiczna gleby: 'A', 'B', 'C', lub 'D'
    default_hsg : str, optional
        Domyslna grupa HSG gdy `hsg` nieprawidlowa, domyslnie 'B'

    Returns
    -------
    int
        Wartosc CN w zakresie 0-100

    Examples
    --------
    >>> lookup_cn("forest", "B")
    55
    >>> lookup_cn("PTLZ", "C")
    70
    >>> lookup_cn("unknown_category", "A")
    60
    """
    # Normalizuj HSG
    hsg_upper = hsg.upper() if hsg else default_hsg
    if hsg_upper not in VALID_HSG:
        logger.warning(f"Nieprawidlowa HSG '{hsg}', uzyto '{default_hsg}'")
        hsg_upper = default_hsg

    # Znajdz CN dla pokrycia
    cn_values = CN_LOOKUP_TABLE.get(land_cover, CN_LOOKUP_TABLE["other"])
    cn = cn_values.get(hsg_upper, cn_values.get("B", DEFAULT_CN))

    return cn


def calculate_weighted_cn_from_stats(
    land_cover_stats: Dict[str, float],
    dominant_hsg: str,
) -> int:
    """
    Oblicz wazony CN na podstawie statystyk pokrycia terenu.

    Parameters
    ----------
    land_cover_stats : Dict[str, float]
        Slownik {kategoria: procent_powierzchni}
    dominant_hsg : str
        Dominujaca grupa hydrologiczna gleby

    Returns
    -------
    int
        Wazony CN (0-100)

    Examples
    --------
    >>> stats = {"forest": 60.0, "arable": 40.0}
    >>> calculate_weighted_cn_from_stats(stats, "B")
    65
    """
    if not land_cover_stats:
        logger.warning("Brak statystyk pokrycia, zwracam DEFAULT_CN")
        return DEFAULT_CN

    weighted_cn = 0.0
    total_percent = 0.0

    for land_cover, percentage in land_cover_stats.items():
        cn = lookup_cn(land_cover, dominant_hsg)
        weighted_cn += cn * (percentage / 100)
        total_percent += percentage

    if total_percent <= 0:
        return DEFAULT_CN

    # Normalizacja jesli procenty nie sumuja sie do 100
    if abs(total_percent - 100) > 0.1:
        weighted_cn = weighted_cn * (100 / total_percent)

    final_cn = round(weighted_cn)
    return max(0, min(100, final_cn))
