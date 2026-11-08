"""
Land cover of a watershed and its curve number (CN) for the SCS-CN method.

The CN of a watershed is the area-weighted mean of the CN of its hydrologic
soil-cover complexes (USDA-NRCS NEH 630, chapters 9 and 10; ADR-075): the pieces where
a land cover row of ``land_cover`` lies on a soil group of ``soil_hsg``, intersected in
PostGIS. The CN of a complex is the TR-55 value of Hydrolog for its cover and soil
group (``core/cn_tables.py``).
"""

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from hydrolog.runoff import calculate_weighted_cn
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.cn_tables import DEFAULT_HSG, HSG_GROUPS, complex_cn
from core.constants import DEFAULT_CN

logger = logging.getLogger(__name__)

# Valid land cover categories (from database constraint)
VALID_CATEGORIES = frozenset(
    [
        "las",
        "łąka",
        "grunt_orny",
        "zabudowa_mieszkaniowa",
        "zabudowa_przemysłowa",
        "droga",
        "woda",
        "inny",
    ]
)

# The land cover of Lutz's estimation of Nash's n and K (KZGW 2017, eq. 6.17): W is the
# share of forest, U the share of urbanised land ("udział terenów zurbanizowanych";
# Lutz 1984: "Bebauungsanteil"). Urbanised land is the built-up and the transport land
# (BDOT10k PTZB, and PTKM with PTPL as `droga`), as the land register counts it (its
# "grunty zabudowane i zurbanizowane" include roads and railways: Dz.U. 2021 poz. 1390,
# § 9 ust. 3) and as KZGW names the impervious surfaces of an urbanised catchment
# (roads, pavements, car parks and buildings); `inny` (unused land, undeveloped land,
# dumps) is not.
FOREST_CATEGORIES: Final = frozenset({"las"})
URBAN_CATEGORIES: Final = frozenset(
    {"zabudowa_mieszkaniowa", "zabudowa_przemysłowa", "droga"}
)

# The land cover of a watershed, once whole (hsg_group NULL) and once in its pieces on
# each soil group. The soil polygons are clipped to the watershed and subdivided first,
# so the pieces come from the index of land_cover and small soil geometries.
_COMPLEXES_SQL = text("""
    WITH watershed AS (
        SELECT ST_SetSRID(ST_GeomFromWKB(decode(:boundary_wkb, 'hex')), 2180) AS geom
    ),
    soils AS (
        SELECT
            sh.hsg_group,
            ST_Subdivide(
                ST_CollectionExtract(ST_Intersection(sh.geom, w.geom), 3), 256
            ) AS geom
        FROM soil_hsg sh
        CROSS JOIN watershed w
        WHERE ST_Intersects(sh.geom, w.geom)
    )
    SELECT
        lc.category,
        lc.bdot_class,
        lc.imperviousness,
        NULL::varchar AS hsg_group,
        SUM(ST_Area(ST_Intersection(lc.geom, w.geom))) AS area_m2
    FROM land_cover lc
    CROSS JOIN watershed w
    WHERE ST_Intersects(lc.geom, w.geom)
    GROUP BY lc.category, lc.bdot_class, lc.imperviousness
    UNION ALL
    SELECT
        lc.category,
        lc.bdot_class,
        lc.imperviousness,
        s.hsg_group,
        SUM(ST_Area(ST_Intersection(lc.geom, s.geom))) AS area_m2
    FROM soils s
    JOIN land_cover lc ON ST_Intersects(lc.geom, s.geom)
    GROUP BY lc.category, lc.bdot_class, lc.imperviousness, s.hsg_group
""")


def get_land_cover_for_boundary(
    boundary: Polygon | MultiPolygon,
    db: Session,
) -> dict[str, Any] | None:
    """
    Land cover of a watershed with the CN of its soil-cover complexes.

    Parameters
    ----------
    boundary : Polygon | MultiPolygon
        Watershed boundary in EPSG:2180.
    db : Session
        Database session.

    Returns
    -------
    dict | None
        ``summarize_complexes`` of the land cover in the boundary: ``categories``,
        ``total_area_m2``, ``weighted_cn``, ``weighted_imperviousness``, ``forest_pct``,
        ``urban_pct`` and ``hsg_assumed_pct``; None for an invalid boundary, a database
        error or a watershed without land cover.
    """
    if not boundary.is_valid:
        return None

    try:
        rows = db.execute(_COMPLEXES_SQL, {"boundary_wkb": boundary.wkb_hex}).fetchall()
    except Exception as e:
        logger.error("Database error getting land cover: %s", e)
        return None
    return summarize_complexes(rows)


def summarize_complexes(rows: Iterable[Any]) -> dict[str, Any] | None:
    """
    Summarize the land cover of a watershed and its weighted CN from its pieces.

    Each row has ``category``, ``bdot_class``, ``imperviousness``, ``hsg_group`` and
    ``area_m2``: with ``hsg_group`` None the whole area of the land cover of that
    category, source and imperviousness in the watershed, otherwise its part on that
    soil group. The part of a land cover outside ``soil_hsg`` takes the soil groups of
    the land cover of the watershed that lies on ``soil_hsg``, in their shares; without
    any, group ``DEFAULT_HSG`` (ADR-075). The CN of the watershed and of each category
    is the area-weighted mean of the CN of the complexes (NEH 630, chapter 10, the
    weighted CN; Hydrolog's ``calculate_weighted_cn``).

    Parameters
    ----------
    rows : Iterable
        Rows of the land cover query.

    Returns
    -------
    dict | None
        - categories: one entry per category, largest first: ``category``,
          ``area_m2``, ``percentage`` and ``cn_value`` (its weighted CN, to 0.1)
        - total_area_m2: area of the land cover [m2]
        - weighted_cn: CN of the watershed for AMC II, to 0.1
        - weighted_imperviousness: area-weighted imperviousness (0-1), to 0.001
        - forest_pct, urban_pct: Lutz's W and U [%] (``FOREST_CATEGORIES``,
          ``URBAN_CATEGORIES``), to 0.1
        - hsg_assumed_pct: share of the land cover outside ``soil_hsg``, whose soil
          group was assumed [%], to 0.1

        None when the land cover has no area.
    """
    totals: dict[tuple[str, str | None, float | None], float] = {}
    parts: dict[tuple[str, str | None, float | None], dict[str, float]] = {}
    for row in rows:
        key = (row.category, row.bdot_class, row.imperviousness)
        area_m2 = float(row.area_m2 or 0.0)
        if row.hsg_group is None:
            totals[key] = totals.get(key, 0.0) + area_m2
        else:
            groups = parts.setdefault(key, {})
            groups[row.hsg_group] = groups.get(row.hsg_group, 0.0) + area_m2

    totals = {key: area for key, area in totals.items() if area > 0}
    total_area = sum(totals.values())
    if total_area <= 0:
        return None

    on_soil = {
        group: sum(groups.get(group, 0.0) for groups in parts.values())
        for group in HSG_GROUPS
    }
    known_area = sum(on_soil.values())
    if known_area > 0:
        soil_shares = {g: a / known_area for g, a in on_soil.items() if a > 0}
    else:
        soil_shares = {DEFAULT_HSG: 1.0}

    pairs: dict[str, list[tuple[int, float]]] = {}
    assumed_area = 0.0
    for key, area in totals.items():
        category, bdot_class, _ = key
        groups = {g: a for g, a in parts.get(key, {}).items() if a > 0}
        known = sum(groups.values())
        if known > area:
            # Overlapping soil polygons: the pieces cannot exceed the land cover
            groups = {g: a * area / known for g, a in groups.items()}
            known = area
        missing = area - known
        assumed_area += missing
        for group, share in soil_shares.items():
            groups[group] = groups.get(group, 0.0) + missing * share
        pairs.setdefault(category, []).extend(
            (complex_cn(category, bdot_class, group), group_area)
            for group, group_area in groups.items()
            if group_area > 0
        )

    category_area = {
        category: sum(area for _, area in cat_pairs)
        for category, cat_pairs in pairs.items()
    }
    categories = [
        {
            "category": category,
            "area_m2": round(category_area[category], 1),
            "percentage": round(category_area[category] / total_area * 100, 1),
            "cn_value": round(calculate_weighted_cn(cat_pairs), 1),
        }
        for category, cat_pairs in sorted(
            pairs.items(), key=lambda item: (-category_area[item[0]], item[0])
        )
    ]
    all_pairs = [pair for cat_pairs in pairs.values() for pair in cat_pairs]
    imperviousness = (
        sum((key[2] or 0.0) * area for key, area in totals.items()) / total_area
    )

    return {
        "categories": categories,
        "total_area_m2": round(total_area, 1),
        "weighted_cn": round(calculate_weighted_cn(all_pairs), 1),
        "weighted_imperviousness": round(imperviousness, 3),
        "forest_pct": _share_pct(category_area, FOREST_CATEGORIES, total_area),
        "urban_pct": _share_pct(category_area, URBAN_CATEGORIES, total_area),
        "hsg_assumed_pct": round(assumed_area / total_area * 100, 1),
    }


def _share_pct(
    category_area: dict[str, float], categories: frozenset[str], total_area_m2: float
) -> float:
    """Return the share of the categories in the land cover of a watershed.

    Parameters
    ----------
    category_area : dict[str, float]
        Area of each category [m2].
    categories : frozenset[str]
        The categories counted.
    total_area_m2 : float
        Area of all the land cover [m2], > 0.

    Returns
    -------
    float
        The share [%], rounded to 0.1 like the shares of the categories.
    """
    area_m2 = sum(area for cat, area in category_area.items() if cat in categories)
    return round(area_m2 / total_area_m2 * 100, 1)


def determine_cn(
    boundary: Polygon | MultiPolygon,
    db: Session,
    config_cn: float | None = None,
    default_cn: int = DEFAULT_CN,
    use_kartograf: bool = True,
    boundary_wgs84: list[list[float]] | None = None,
    cache_dir: Path | None = None,
    teryt: str | None = None,
) -> tuple[float, str, dict[str, Any] | None]:
    """
    Okresl wartosc CN wedlug hierarchii zrodel.

    Hierarchia:
    1. Jawnie podana wartosc w konfiguracji (config_cn)
    2. Z tabel land_cover i soil_hsg w bazie danych (``get_land_cover_for_boundary``)
    3. Z Kartografa (HSG + land cover) - jesli use_kartograf=True
    4. Wartosc domyslna (default_cn)

    Parameters
    ----------
    boundary : Polygon | MultiPolygon
        Granica zlewni w EPSG:2180
    db : Session
        Sesja bazy danych
    config_cn : float, optional
        Wartosc CN z konfiguracji (najwyzszy priorytet)
    default_cn : int, optional
        Domyslna wartosc CN, domyslnie 75
    use_kartograf : bool, optional
        Czy uzywac Kartografa, domyslnie True
    boundary_wgs84 : List[List[float]], optional
        Granica w WGS84 (wymagana dla Kartografa)
    cache_dir : Path, optional
        Katalog cache pobranych danych (wymagany dla Kartografa): jego magazyn to
        ``<cache_dir>/kartograf`` (ADR-061)

    Returns
    -------
    Tuple[float, str, Optional[Dict[str, Any]]]
        (cn_value, source, details)
        - cn_value: wartosc CN (0-100, wartosci wazone zaokraglone do 0.1)
        - source: zrodlo ('config', 'database_land_cover', 'kartograf_hsg', 'default')
        - details: dodatkowe informacje (udzialy kategorii z bazy; dane Kartografa)

    Examples
    --------
    >>> cn, source, details = determine_cn(boundary, db, config_cn=80)
    >>> print(f"CN={cn} (zrodlo: {source})")
    CN=80 (zrodlo: config)
    """
    # 1. Jawnie podana wartosc
    if config_cn is not None:
        logger.info(f"CN z konfiguracji: {config_cn}")
        return (config_cn, "config", None)

    # 2. Z tabel land_cover i soil_hsg w DB
    lc_data = get_land_cover_for_boundary(boundary, db)
    if lc_data:
        logger.info(
            "CN z bazy danych (land_cover, soil_hsg): %s", lc_data["weighted_cn"]
        )
        return (
            lc_data["weighted_cn"],
            "database_land_cover",
            {
                "stats": {
                    c["category"]: c["percentage"] for c in lc_data["categories"]
                },
                "hsg_assumed_pct": lc_data["hsg_assumed_pct"],
            },
        )

    # 3. Z Kartografa
    if use_kartograf and boundary_wgs84 and cache_dir:
        from core.cn_calculator import calculate_cn_from_kartograf

        result = calculate_cn_from_kartograf(boundary_wgs84, cache_dir, teryt=teryt)

        if result and result.cn:
            logger.info(f"CN z Kartografa (HSG={result.dominant_hsg}): {result.cn}")
            return (
                result.cn,
                "kartograf_hsg",
                {
                    "dominant_hsg": result.dominant_hsg,
                    "hsg_stats": result.hsg_stats,
                    "land_cover_stats": result.land_cover_stats,
                    "cn_details": result.cn_details,
                },
            )

    # 4. Wartosc domyslna
    logger.warning(f"Brak danych CN, uzyto wartosci domyslnej: {default_cn}")
    return (default_cn, "default", None)
