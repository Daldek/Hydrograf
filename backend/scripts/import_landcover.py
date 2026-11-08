r"""
Import the land cover of a BDOT10k county package into PostgreSQL/PostGIS (ADR-074).

The land cover is the partition that the BDOT10k layers of the category "pokrycie
terenu" (``OT_PT*_A``) form: they cover 100% of the county and do not overlap (Dz.U.
2021 poz. 1412, Zał. 3, rozdz. 5, ust. 1-2). Every PT polygon gets a Hydrograf category
from its layer and, in four layers, from the attribute that the specification defines
for it (Zał. 3, rozdz. 5, tables 14, 18, 21 and 24):

    PTZB  RODZAJ jednorodzinna, wielorodzinna,
          pozostała zabudowa                       -> zabudowa_mieszkaniowa
          RODZAJ przemysłowo-składowa,
          handlowo-usługowa                        -> zabudowa_przemysłowa
    PTTR  RODZAJ uprawa na gruntach ornych         -> grunt_orny
          RODZAJ roślinność trawiasta              -> łąka
    PTNZ  RODZAJ teren przemysłowo-składowy        -> zabudowa_przemysłowa
          RODZAJ teren pod urządzeniami
          technicznymi lub budowlami               -> inny
    PTPL  MATERIALNAWIERZCHNI grunt naturalny,
          żwir, tłuczeń                            -> inny
          any other surface                        -> droga
    PTLZ                                           -> las
    PTRK, PTUT                                     -> łąka
    PTKM                                           -> droga
    PTWP                                           -> woda
    PTGN, PTSO, PTWZ, any other PT layer           -> inny

The industrial complexes of ``OT_KUPG_A`` overlay the partition (Zał. 3, rozdz. 7): a
production, service or repair plant, a fuel depot, a gasworks, a combined heat and power
plant, a waste treatment plant, a steelworks, a refinery, a metallurgical plant and a
thermal or nuclear power plant. Their area is cut out of the PT polygons that it covers,
except water, and becomes ``zabudowa_przemysłowa``, so the rows are still a partition
and the areas of the categories sum to the area of the PT layers. Solar, wind and water
power plants, mines, farms and the other kinds of complex keep the land cover of the PT
layers.

``bdot_class`` records the source of each row: the layer code, followed after a colon by
the value of the attribute that decided its category (``PTZB:przem.-skład.``,
``KUPG:baza paliw``).

An import replaces, in one transaction, the rows of the area of the package (the rows
whose interior point lies in one of its polygons), so importing a package again leaves
the table as it was; ``--clear-existing`` deletes the whole table first.

Usage
-----
    cd backend
    uv run python -m scripts.import_landcover --help
    uv run python -m scripts.import_landcover \
        --input ../cache/kartograf/landcover/pl_bdot10k_gpkg/teryt/1465.gpkg

Examples
--------
    # Dry run (show what would be imported)
    uv run python -m scripts.import_landcover --input <package>.gpkg --dry-run

    # Delete the land cover of every county before the import
    uv run python -m scripts.import_landcover --input <package>.gpkg --clear-existing
"""

import argparse
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    import geopandas
    from shapely.geometry.base import BaseGeometry
    from sqlalchemy.engine import Connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class LandCoverClass(NamedTuple):
    """The land cover of a source: category, ``bdot_class`` and imperviousness (0-1)."""

    category: str
    bdot_class: str
    imperviousness: float


INDUSTRIAL = "zabudowa_przemysłowa"

# Average imperviousness of the urban districts of TR-55 (USDA-SCS 1986, table 2-2a):
# commercial and business 85%, industrial 72%, residential 1/8 acre 65%, 1/3 acre 30%.
IMPERVIOUS_COMMERCIAL = 0.85
IMPERVIOUS_INDUSTRIAL = 0.72
IMPERVIOUS_RESIDENTIAL_DENSE = 0.65
IMPERVIOUS_RESIDENTIAL = 0.30

# The class of a PT layer without the attribute of PT_KIND_ATTRIBUTES or with a value
# that PT_KIND_CLASSES does not list; a layer that is not here gets DEFAULT_CATEGORY.
PT_LAYER_CLASSES: dict[str, LandCoverClass] = {
    "PTLZ": LandCoverClass("las", "PTLZ", 0.0),
    "PTTR": LandCoverClass("grunt_orny", "PTTR", 0.1),
    "PTUT": LandCoverClass("łąka", "PTUT", 0.0),
    "PTRK": LandCoverClass("łąka", "PTRK", 0.0),
    "PTWP": LandCoverClass("woda", "PTWP", 1.0),
    "PTZB": LandCoverClass("zabudowa_mieszkaniowa", "PTZB", IMPERVIOUS_RESIDENTIAL),
    "PTKM": LandCoverClass("droga", "PTKM", 0.95),
    "PTPL": LandCoverClass("droga", "PTPL", 0.95),
    "PTGN": LandCoverClass("inny", "PTGN", 0.2),
    "PTNZ": LandCoverClass("inny", "PTNZ", 0.2),
    "PTSO": LandCoverClass("inny", "PTSO", 0.2),
    "PTWZ": LandCoverClass("inny", "PTWZ", 0.2),
}
DEFAULT_CATEGORY = "inny"
DEFAULT_IMPERVIOUSNESS = 0.2

# The attribute that splits a PT layer, and the class of each of its values.
PT_KIND_ATTRIBUTES: dict[str, str] = {
    "PTZB": "RODZAJ",
    "PTTR": "RODZAJ",
    "PTNZ": "RODZAJ",
    "PTPL": "MATERIALNAWIERZCHNI",
}
_PAVED = LandCoverClass("droga", "PTPL:utwardzony", 0.95)
_UNPAVED = LandCoverClass("inny", "PTPL:nieutwardzony", 0.2)
PT_KIND_CLASSES: dict[tuple[str, str], LandCoverClass] = {
    ("PTZB", "jednorodzinna"): LandCoverClass(
        "zabudowa_mieszkaniowa", "PTZB:jednorodzinna", IMPERVIOUS_RESIDENTIAL
    ),
    ("PTZB", "wielorodzinna"): LandCoverClass(
        "zabudowa_mieszkaniowa", "PTZB:wielorodzinna", IMPERVIOUS_RESIDENTIAL_DENSE
    ),
    ("PTZB", "pozostała zabudowa"): LandCoverClass(
        "zabudowa_mieszkaniowa", "PTZB:pozostała", IMPERVIOUS_RESIDENTIAL
    ),
    ("PTZB", "przemysłowo-składowa"): LandCoverClass(
        INDUSTRIAL, "PTZB:przem.-skład.", IMPERVIOUS_INDUSTRIAL
    ),
    ("PTZB", "handlowo-usługowa"): LandCoverClass(
        INDUSTRIAL, "PTZB:handl.-usług.", IMPERVIOUS_COMMERCIAL
    ),
    ("PTTR", "uprawa na gruntach ornych"): LandCoverClass(
        "grunt_orny", "PTTR:grunty orne", 0.1
    ),
    ("PTTR", "roślinność trawiasta"): LandCoverClass("łąka", "PTTR:trawiasta", 0.0),
    ("PTNZ", "teren przemysłowo-składowy"): LandCoverClass(
        INDUSTRIAL, "PTNZ:przem.-skład.", IMPERVIOUS_INDUSTRIAL
    ),
    ("PTNZ", "teren pod urządzeniami technicznymi lub budowlami"): LandCoverClass(
        "inny", "PTNZ:urządzenia", 0.2
    ),
    ("PTPL", "beton"): _PAVED,
    ("PTPL", "bruk"): _PAVED,
    ("PTPL", "kostka kamienna"): _PAVED,
    ("PTPL", "kostka prefabrykowana"): _PAVED,
    ("PTPL", "masa bitumiczna"): _PAVED,
    ("PTPL", "płyty betonowe"): _PAVED,
    ("PTPL", "grunt naturalny"): _UNPAVED,
    ("PTPL", "żwir"): _UNPAVED,
    ("PTPL", "tłuczeń"): _UNPAVED,
    ("PTPL", "inny"): PT_LAYER_CLASSES["PTPL"],
}


def _industrial(bdot_class: str) -> LandCoverClass:
    return LandCoverClass(INDUSTRIAL, bdot_class, IMPERVIOUS_INDUSTRIAL)


# The kinds (RODZAJ) of OT_KUPG_A that are industrial land, and of "elektrownia" the
# kinds of power plant (RODZAJELEKTROWNI) that are.
INDUSTRIAL_COMPLEX_CLASSES: dict[str, LandCoverClass] = {
    "zakład produkcyjny, usługowy lub remontowy": _industrial("KUPG:zakład prod."),
    "baza paliw": _industrial("KUPG:baza paliw"),
    "gazownia": _industrial("KUPG:gazownia"),
    "elektrociepłownia": _industrial("KUPG:elektrociepł."),
    "zakład utylizacji": _industrial("KUPG:zakład utyliz."),
    "huta": _industrial("KUPG:huta"),
    "rafineria": _industrial("KUPG:rafineria"),
    "zakład metalurgiczny": _industrial("KUPG:zakład metal."),
}
INDUSTRIAL_POWER_PLANT_CLASSES: dict[str, LandCoverClass] = {
    "cieplna": _industrial("KUPG:el. cieplna"),
    "atomowa": _industrial("KUPG:el. atomowa"),
}

# The categories that an industrial complex does not replace: industrial land already,
# and water, which is neither of the two covers that the TR-55 urban districts combine
# (impervious area and open space; USDA-SCS 1986, table 2-2a, footnote 2).
KEPT_UNDER_ZONES = frozenset({INDUSTRIAL, "woda"})

# A layer of the package that the import reads: "OT_PTLZ_A" or "PTLZ", "OT_KUPG_A".
_LAYER_NAME = re.compile(r"(?:OT_)?(PT[A-Z]{2}|KUPG)(?:_A)?")
_READ_COLUMNS = ["RODZAJ", "MATERIALNAWIERZCHNI", "RODZAJELEKTROWNI"]

# The columns of land_cover that the import writes.
_COLUMNS = "geom, category, imperviousness, bdot_class"


def get_database_url() -> str:
    """Get database URL from environment or config."""
    # Try environment variable first
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    # Try config file
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.config import get_settings

        return get_settings().database_url
    except ImportError:
        pass

    # Default for local development
    return "postgresql://hydro_user:@localhost:5432/hydro_db"


def read_gpkg_layers(gpkg_path: Path) -> dict[str, "geopandas.GeoDataFrame"]:
    """
    Read the PT layers and the industrial complexes of a GeoPackage.

    Parameters
    ----------
    gpkg_path : Path
        Path to the GeoPackage file

    Returns
    -------
    Dict[str, GeoDataFrame]
        The layers by code ("PTLZ", "KUPG") with the attributes that the import uses
    """
    import fiona
    import geopandas as gpd

    layers = {}
    for layer_name in fiona.listlayers(gpkg_path):
        match = _LAYER_NAME.fullmatch(layer_name.upper())
        if match is None:
            continue
        code = match.group(1)
        try:
            gdf = gpd.read_file(gpkg_path, layer=layer_name, columns=_READ_COLUMNS)
        except Exception as e:
            logger.warning("  %s: failed to read - %s", code, e)
            continue
        if len(gdf) > 0:
            layers[code] = gdf
            logger.info("  %s: %d features", code, len(gdf))

    return layers


def transform_to_2180(gdf: "geopandas.GeoDataFrame") -> "geopandas.GeoDataFrame":
    """
    Transform GeoDataFrame to EPSG:2180 (PL-1992) if needed.

    Parameters
    ----------
    gdf : GeoDataFrame
        Input GeoDataFrame

    Returns
    -------
    GeoDataFrame
        GeoDataFrame in EPSG:2180
    """
    if gdf.crs is None:
        logger.warning("No CRS defined, assuming EPSG:2180")
        gdf = gdf.set_crs("EPSG:2180")
    elif gdf.crs.to_epsg() != 2180:
        logger.info(f"Transforming from {gdf.crs} to EPSG:2180")
        gdf = gdf.to_crs("EPSG:2180")
    return gdf


def _polygonal(geom: "BaseGeometry | None") -> "BaseGeometry | None":
    """Return the polygons of a geometry as one MultiPolygon, None if it has none."""
    from shapely.geometry import MultiPolygon

    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "MultiPolygon":
        return geom
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "GeometryCollection":
        polygons = []
        for part in geom.geoms:
            polygonal = _polygonal(part)
            if polygonal is not None:
                polygons.extend(polygonal.geoms)
        return MultiPolygon(polygons) if polygons else None
    return None


def _valid_polygons(gdf: "geopandas.GeoDataFrame", code: str) -> list[Any]:
    """Return the polygons of a layer as valid MultiPolygons, None without area."""
    import shapely

    geoms = gdf.geometry.to_numpy()
    invalid = ~shapely.is_valid(geoms) & ~shapely.is_missing(geoms)
    if invalid.any():
        logger.info("  %s: %d invalid geometries made valid", code, invalid.sum())
        geoms = geoms.copy()
        geoms[invalid] = shapely.make_valid(geoms[invalid])
    result = [_polygonal(geom) for geom in geoms]
    skipped = sum(
        1
        for geom, valid in zip(geoms, result, strict=True)
        if valid is None and geom is not None and not geom.is_empty
    )
    if skipped:
        logger.warning("  %s: %d geometries without area skipped", code, skipped)
    return result


def classify(code: str, gdf: "geopandas.GeoDataFrame") -> list[LandCoverClass]:
    """Return the land cover class of every polygon of a PT layer."""
    default = PT_LAYER_CLASSES.get(
        code, LandCoverClass(DEFAULT_CATEGORY, code, DEFAULT_IMPERVIOUSNESS)
    )
    attribute = PT_KIND_ATTRIBUTES.get(code)
    if attribute is None or attribute not in gdf.columns:
        return [default] * len(gdf)

    classes = []
    unknown: Counter[str] = Counter()
    for value in gdf[attribute]:
        cls = PT_KIND_CLASSES.get((code, value)) if isinstance(value, str) else None
        if cls is None:
            unknown[str(value)] += 1
            cls = default
        classes.append(cls)
    for value, count in unknown.items():
        logger.warning(
            "  %s: %s %r not mapped, %d polygons get %s",
            code,
            attribute,
            value,
            count,
            default.category,
        )
    return classes


def industrial_zones(
    kupg: "geopandas.GeoDataFrame | None",
) -> tuple[list[Any], list[LandCoverClass]]:
    """
    Return the industrial complexes of OT_KUPG_A as disjoint polygons and classes.

    A complex that overlaps an earlier one of the layer keeps only the part outside it,
    so no area is counted twice.
    """
    import shapely

    if kupg is None or kupg.empty:
        return [], []

    kupg = transform_to_2180(kupg)
    kinds = kupg["RODZAJ"] if "RODZAJ" in kupg.columns else [None] * len(kupg)
    plants = (
        kupg["RODZAJELEKTROWNI"]
        if "RODZAJELEKTROWNI" in kupg.columns
        else [None] * len(kupg)
    )
    candidates: list[Any] = []
    classes: list[LandCoverClass] = []
    for kind, plant, geom in zip(kinds, plants, kupg.geometry.values, strict=True):
        cls = INDUSTRIAL_COMPLEX_CLASSES.get(kind)
        if cls is None and kind == "elektrownia":
            cls = INDUSTRIAL_POWER_PLANT_CLASSES.get(plant)
        if cls is None or geom is None:
            continue
        polygonal = _polygonal(geom if geom.is_valid else shapely.make_valid(geom))
        if polygonal is not None:
            candidates.append(polygonal)
            classes.append(cls)

    tree = shapely.STRtree(candidates)
    zones, zone_classes = [], []
    for i, geom in enumerate(candidates):
        earlier = [j for j in tree.query(geom, predicate="intersects") if j < i]
        if earlier:
            geom = _polygonal(
                shapely.difference(
                    geom, shapely.union_all([candidates[j] for j in earlier])
                )
            )
        if geom is not None:
            zones.append(geom)
            zone_classes.append(classes[i])
    return zones, zone_classes


def partition(
    geoms: list[Any],
    classes: list[LandCoverClass],
    zones: list[Any],
    zone_classes: list[LandCoverClass],
) -> list[tuple[Any, LandCoverClass]]:
    """
    Cut the industrial zones out of the polygons of a PT layer.

    A polygon whose category the zones replace (any but ``KEPT_UNDER_ZONES``) and that
    shares area with zones becomes its part outside them, with its class, and one piece
    per zone, with the class of the zone; any other polygon stays whole. The pieces of
    a polygon cover it exactly.
    """
    import shapely

    hits: dict[int, list[int]] = defaultdict(list)
    if zones:
        tree = shapely.STRtree(zones)
        for i, j in zip(*tree.query(geoms, predicate="intersects"), strict=True):
            if classes[i].category not in KEPT_UNDER_ZONES:
                hits[int(i)].append(int(j))

    pieces: list[tuple[Any, LandCoverClass]] = []
    for i, (geom, cls) in enumerate(zip(geoms, classes, strict=True)):
        if geom is None:
            continue
        inside = []
        for j in hits.get(i, []):
            piece = _polygonal(shapely.intersection(geom, zones[j]))
            if piece is not None:
                inside.append((j, piece))
        if not inside:
            pieces.append((geom, cls))
            continue
        cover = shapely.union_all([zones[j] for j, _ in inside])
        outside = _polygonal(shapely.difference(geom, cover))
        if outside is not None:
            pieces.append((outside, cls))
        pieces.extend((piece, zone_classes[j]) for j, piece in inside)
    return pieces


def prepare_records(
    layers: dict[str, "geopandas.GeoDataFrame"],
) -> list[dict[str, Any]]:
    """
    Prepare the land cover records of a package (ADR-074).

    Parameters
    ----------
    layers : Dict[str, GeoDataFrame]
        The layers by code (``read_gpkg_layers``): PT layers and ``KUPG``

    Returns
    -------
    List[Dict]
        One record per piece of the partition: ``geom_wkb`` (MultiPolygon, EPSG:2180),
        ``category``, ``imperviousness``, ``bdot_class``
    """
    import shapely

    zones, zone_classes = industrial_zones(layers.get("KUPG"))
    records = []
    for code, gdf in layers.items():
        if code == "KUPG":
            continue
        gdf = transform_to_2180(gdf)
        pieces = partition(
            _valid_polygons(gdf, code), classify(code, gdf), zones, zone_classes
        )
        blobs = shapely.to_wkb([geom for geom, _ in pieces])
        for blob, (_, cls) in zip(blobs, pieces, strict=True):
            records.append(
                {
                    "geom_wkb": blob,
                    "category": cls.category,
                    "imperviousness": cls.imperviousness,
                    "bdot_class": cls.bdot_class,
                }
            )

    return records


def replace_land_cover(
    conn: "Connection",
    records: list[dict[str, Any]],
    batch_size: int = 1000,
) -> tuple[int, int]:
    """
    Replace the land cover of the area of the records, in the caller's transaction.

    A row is replaced when its interior point and more than half of its area lie in the
    records: the rows of the same county from an earlier import, whatever their mapping,
    and no row of a neighbouring county, whose package may overlap this one by a sliver
    along the border. A row that a record repeats exactly is replaced without computing
    its area.

    Returns
    -------
    Tuple[int, int]
        The rows inserted and the rows replaced (deleted)
    """
    from sqlalchemy import text

    conn.execute(
        text(
            f"CREATE TEMPORARY TABLE land_cover_import AS "
            f"SELECT {_COLUMNS} FROM land_cover WITH NO DATA"
        )
    )
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        values = []
        params: dict[str, Any] = {}
        for j, rec in enumerate(batch):
            p = f"p{j}_"
            values.append(
                f"(ST_SetSRID(ST_GeomFromWKB(:{p}geom), 2180), :{p}category, "
                f":{p}imperviousness, :{p}bdot_class)"
            )
            params[f"{p}geom"] = rec["geom_wkb"]
            params[f"{p}category"] = rec["category"]
            params[f"{p}imperviousness"] = rec["imperviousness"]
            params[f"{p}bdot_class"] = rec["bdot_class"]
        conn.execute(
            text(
                f"INSERT INTO land_cover_import ({_COLUMNS}) VALUES {', '.join(values)}"
            ),
            params,
        )
        logger.info("  Prepared %d/%d records", i + len(batch), len(records))

    conn.execute(text("CREATE INDEX ON land_cover_import USING GIST (geom)"))
    conn.execute(text("ANALYZE land_cover_import"))
    replaced = conn.execute(
        text("""
            DELETE FROM land_cover AS lc
            WHERE lc.geom && (
                SELECT ST_SetSRID(ST_Extent(geom)::geometry, 2180)
                FROM land_cover_import
            )
            AND EXISTS (
                SELECT 1 FROM land_cover_import AS n
                WHERE ST_Intersects(n.geom, ST_PointOnSurface(lc.geom))
            )
            AND (
                EXISTS (
                    SELECT 1 FROM land_cover_import AS n
                    WHERE n.geom ~= lc.geom AND n.geom = lc.geom
                )
                OR (
                    SELECT SUM(ST_Area(ST_Intersection(lc.geom, n.geom)))
                    FROM land_cover_import AS n
                    WHERE n.geom && lc.geom AND ST_Relate(n.geom, lc.geom, 'T********')
                ) > 0.5 * ST_Area(lc.geom)
            )
        """)
    ).rowcount
    inserted = conn.execute(
        text(
            f"INSERT INTO land_cover ({_COLUMNS}) "
            f"SELECT {_COLUMNS} FROM land_cover_import"
        )
    ).rowcount
    conn.execute(text("DROP TABLE land_cover_import"))
    return inserted, replaced


def import_to_database(
    records: list[dict[str, Any]],
    database_url: str,
    batch_size: int = 1000,
    clear_existing: bool = False,
) -> tuple[int, int]:
    """
    Import the records of a package into the land_cover table in one transaction.

    Parameters
    ----------
    records : List[Dict]
        Records to import
    database_url : str
        Database connection URL
    batch_size : int
        Number of records per batch
    clear_existing : bool
        If True, delete the land cover of every county before the import

    Returns
    -------
    Tuple[int, int]
        The rows inserted and the rows of the area of the package that they replaced
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            if clear_existing:
                logger.info("Clearing existing land_cover data...")
                conn.execute(text("TRUNCATE TABLE land_cover RESTART IDENTITY CASCADE"))
            return replace_land_cover(conn, records, batch_size)
    finally:
        engine.dispose()


def import_landcover(
    input_path: Path,
    database_url: str | None = None,
    batch_size: int = 1000,
    dry_run: bool = False,
    clear_existing: bool = False,
) -> dict[str, Any]:
    """
    Import land cover data from GeoPackage to database.

    Parameters
    ----------
    input_path : Path
        Path to GeoPackage file
    database_url : str, optional
        Database connection URL (default: from config)
    batch_size : int
        Records per batch
    dry_run : bool
        If True, only show what would be done
    clear_existing : bool
        If True, delete the land cover of every county before the import

    Returns
    -------
    Dict
        Import statistics
    """
    stats = {
        "layers_read": 0,
        "features_total": 0,
        "records_prepared": 0,
        "records_inserted": 0,
        "records_replaced": 0,
    }

    # Read GeoPackage layers
    logger.info("Reading GeoPackage: %s", input_path)
    layers = read_gpkg_layers(input_path)

    stats["layers_read"] = len(layers)
    stats["features_total"] = sum(len(gdf) for gdf in layers.values())

    logger.info(
        "Read %d layers, %d features", stats["layers_read"], stats["features_total"]
    )

    if stats["features_total"] == 0:
        logger.warning("No features found to import!")
        return stats

    # Prepare records
    logger.info("Preparing records for database...")
    records = prepare_records(layers)
    stats["records_prepared"] = len(records)

    logger.info("Prepared %d records", len(records))

    from shapely import area, from_wkb

    areas = area(from_wkb([r["geom_wkb"] for r in records]))
    by_category: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for rec, area_m2 in zip(records, areas, strict=True):
        by_category[rec["category"]][0] += 1
        by_category[rec["category"]][1] += area_m2
    logger.info("Category distribution:")
    for cat, (count, area_m2) in sorted(by_category.items()):
        logger.info("  %s: %d records, %.3f km2", cat, count, area_m2 / 1e6)

    if dry_run:
        logger.info("DRY RUN - no data will be imported")
        return stats

    # Import to database
    if database_url is None:
        database_url = get_database_url()

    logger.info("Importing to database...")
    stats["records_inserted"], stats["records_replaced"] = import_to_database(
        records=records,
        database_url=database_url,
        batch_size=batch_size,
        clear_existing=clear_existing,
    )

    return stats


def main():
    """Run the land cover import script."""
    parser = argparse.ArgumentParser(
        description="Import land cover data from GeoPackage to PostgreSQL/PostGIS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Input
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to GeoPackage file (.gpkg)",
    )

    # Options
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Records per database batch (default: 1000)",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Delete the land cover of every county before the import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be imported",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Land Cover Import Script")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Clear existing: {args.clear_existing}")
    logger.info("=" * 60)

    # Run import
    start_time = time.time()

    try:
        stats = import_landcover(
            input_path=input_path,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            clear_existing=args.clear_existing,
        )
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error(
            "Run `uv sync --locked` in backend/ to install geopandas and fiona."
        )
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time

    # Summary
    logger.info("=" * 60)
    logger.info("Import complete!")
    logger.info("=" * 60)
    logger.info(f"  Layers read: {stats['layers_read']}")
    logger.info(f"  Features total: {stats['features_total']}")
    logger.info(f"  Records prepared: {stats['records_prepared']}")
    logger.info(f"  Records inserted: {stats['records_inserted']}")
    logger.info(f"  Records replaced: {stats['records_replaced']}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
