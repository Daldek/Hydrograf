"""
Curve numbers of the hydrologic soil-cover complexes of the land cover (ADR-075).

A hydrologic soil-cover complex is a land cover on a hydrologic soil group (HSG); its
curve number (CN) for the average antecedent runoff condition (AMC II) comes from the
tables of TR-55 (USDA-NRCS, NEH Part 630, chapter 9). Here a land cover is a category
of the table ``land_cover`` with the source of its row (``bdot_class``) and a soil
group is one of ``soil_hsg``. The numbers are Hydrolog's TR-55 table
(:func:`hydrolog.runoff.get_cn`), the single source of the CN; this module says only
which TR-55 cover each category stands for and gives Hydrolog's conversion to AMC I
and III and its runoff depth of a storm.

Sources:

- USDA-SCS (1986). Urban Hydrology for Small Watersheds, TR-55, 2nd ed., tables 2-2a
  (urban areas), 2-2b (cultivated agricultural lands) and 2-2c (other agricultural
  lands).
- USDA-NRCS (2004). NEH Part 630, chapter 9 (hydrologic soil-cover complexes;
  "impervious and water surfaces ... are always assigned a CN of 98", p. 9-1) and
  chapter 10 (the weighted CN of a watershed of several complexes and the weighted
  runoff, p. 10-10; the antecedent runoff condition).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from hydrolog.runoff import AMC, SCSCN, HydrologicCondition, LandCover, get_cn

# The soil groups of soil_hsg, from the most to the least permeable
HSG_GROUPS: Final = ("A", "B", "C", "D")

# The soil group assumed for a land cover outside soil_hsg when the watershed has no
# soil data at all (with some, the soil groups of the rest of the watershed apply:
# ADR-075); the same fallback as the HSG of the Kartograf CN (core/cn_calculator.py)
DEFAULT_HSG: Final = "B"


@dataclass(frozen=True)
class Tr55Cover:
    """A cover of the TR-55 tables, as Hydrolog names it.

    Attributes
    ----------
    land_cover : LandCover
        The cover type of Hydrolog's table.
    condition : HydrologicCondition | None
        The hydrologic condition; None for a cover the table gives without one.
    row : str
        The row of TR-55 (or NEH 630) that the numbers are.
    """

    land_cover: LandCover
    condition: HydrologicCondition | None
    row: str


# The TR-55 cover of each land cover category (the categories of the constraint of
# land_cover). The reasons are in ADR-075.
COVER_BY_CATEGORY: Final[dict[str, Tr55Cover]] = {
    "las": Tr55Cover(
        LandCover.FOREST,
        HydrologicCondition.GOOD,
        "Woods, good: protected from grazing, litter and brush cover the soil "
        "(TR-55 table 2-2c)",
    ),
    "łąka": Tr55Cover(
        LandCover.MEADOW,
        None,
        "Meadow: continuous grass, protected from grazing and generally mowed for hay "
        "(TR-55 table 2-2c)",
    ),
    "grunt_orny": Tr55Cover(
        LandCover.SMALL_GRAIN,
        HydrologicCondition.GOOD,
        "Small grain, straight row, good (TR-55 table 2-2b)",
    ),
    "zabudowa_mieszkaniowa": Tr55Cover(
        LandCover.RESIDENTIAL_MEDIUM,
        None,
        "Residential districts, 1/3 acre lots, 30% impervious (TR-55 table 2-2a)",
    ),
    "zabudowa_przemysłowa": Tr55Cover(
        LandCover.INDUSTRIAL,
        None,
        "Urban districts: industrial, 72% impervious (TR-55 table 2-2a)",
    ),
    "droga": Tr55Cover(
        LandCover.PAVED,
        None,
        "Impervious areas: paved parking lots, roofs, driveways; paved streets and "
        "roads (TR-55 table 2-2a)",
    ),
    "woda": Tr55Cover(
        LandCover.PAVED,
        None,
        "Water surfaces: CN 98, as impervious areas (NEH 630, chapter 9, p. 9-1)",
    ),
    "inny": Tr55Cover(
        LandCover.OPEN_SPACE,
        HydrologicCondition.FAIR,
        "Open space, fair condition: grass cover 50 to 75% (TR-55 table 2-2a)",
    ),
}

# Sources (bdot_class) of a category that a TR-55 cover describes better than the cover
# of the category: (category, bdot_class) -> cover. bdot_class is the source of the row
# as the land cover import writes it ("<layer>:<kind>" for a split layer).
COVER_BY_SOURCE: Final[dict[tuple[str, str], Tr55Cover]] = {
    ("zabudowa_mieszkaniowa", "PTZB:wielorodzinna"): Tr55Cover(
        LandCover.RESIDENTIAL_HIGH,
        None,
        "Residential districts, 1/8 acre or less (town houses), 65% impervious "
        "(TR-55 table 2-2a)",
    ),
    ("zabudowa_przemysłowa", "PTZB:handl.-usług."): Tr55Cover(
        LandCover.COMMERCIAL,
        None,
        "Urban districts: commercial and business, 85% impervious (TR-55 table 2-2a)",
    ),
    ("inny", "PTPL:nieutwardzony"): Tr55Cover(
        LandCover.DIRT,
        None,
        "Streets and roads: dirt, including right-of-way (TR-55 table 2-2a)",
    ),
    ("inny", "PTWZ"): Tr55Cover(
        LandCover.FALLOW,
        None,
        "Newly graded areas, no vegetation (TR-55 table 2-2a); the same numbers as "
        "fallow, bare soil (table 2-2b)",
    ),
}


def cover_for(category: str, bdot_class: str | None) -> Tr55Cover:
    """Return the TR-55 cover of a land cover row.

    Parameters
    ----------
    category : str
        Category of the row (one of ``COVER_BY_CATEGORY``).
    bdot_class : str | None
        Source of the row (``land_cover.bdot_class``).

    Returns
    -------
    Tr55Cover
        The cover of the source when ``COVER_BY_SOURCE`` has it, else the cover of the
        category.

    Raises
    ------
    KeyError
        For a category outside ``COVER_BY_CATEGORY`` (the constraint of land_cover
        admits no other).
    """
    if bdot_class is not None:
        cover = COVER_BY_SOURCE.get((category, bdot_class))
        if cover is not None:
            return cover
    return COVER_BY_CATEGORY[category]


def complex_cn(category: str, bdot_class: str | None, hsg: str) -> int:
    """CN (AMC II) of a land cover row on a soil group, from Hydrolog's TR-55 table.

    Parameters
    ----------
    category : str
        Category of the row.
    bdot_class : str | None
        Source of the row (``land_cover.bdot_class``).
    hsg : str
        Hydrologic soil group, "A" to "D".

    Returns
    -------
    int
        Curve number, 30-98.

    Examples
    --------
    >>> complex_cn("las", "PTLZ", "B")
    55
    >>> complex_cn("zabudowa_przemysłowa", "PTZB:handl.-usług.", "B")
    92
    """
    cover = cover_for(category, bdot_class)
    return get_cn(hsg, cover.land_cover, cover.condition)


def cn_for_amc(cn: float, amc: AMC) -> int:
    """CN of a watershed for an antecedent runoff condition, by Hydrolog's conversion.

    The conversion of the hydrograph (``SCSCN.adjust_cn_for_amc``: Hawkins et al.
    1985, approximating NEH 630 chapter 10, table 10-1), applied to the CN of the
    watershed for AMC II as the hydrograph applies it; Hydrolog rounds the result to an
    integer and warns (``OutsideTypicalRange``) for a CN outside 55-95.

    Parameters
    ----------
    cn : float
        CN of the watershed for AMC II (1-100), e.g. the area-weighted CN.
    amc : AMC
        The antecedent runoff condition.

    Returns
    -------
    int
        CN for ``amc``.
    """
    # Hydrolog annotates the CN as int; its formulas take the weighted CN of a
    # watershed, as the hydrograph passes it (api/endpoints/hydrograph.py).
    return SCSCN(cn=cn).adjust_cn_for_amc(amc)  # type: ignore[arg-type]


def runoff_mm(cn: float, precipitation_mm: float) -> float:
    """Direct runoff depth Q of a storm for AMC II, by Hydrolog's SCS-CN equation.

    ``SCSCN.effective_precipitation``: Q = (P - Ia)^2 / (P - Ia + S) for P > Ia, else
    0, with S = 25400 / CN - 254 and Ia = 0.2 S (NEH 630 chapter 10).

    Parameters
    ----------
    cn : float
        CN for AMC II (1-100), of a complex or the composite CN of a watershed.
    precipitation_mm : float
        Storm depth P [mm].

    Returns
    -------
    float
        Runoff depth Q [mm].
    """
    # Hydrolog annotates the CN as int; its equation takes the weighted CN of a
    # watershed, as the hydrograph passes it (api/endpoints/hydrograph.py).
    scs = SCSCN(cn=cn)  # type: ignore[arg-type]
    return scs.effective_precipitation(precipitation_mm, AMC.II).total_effective_mm


def weighted_runoff_mm(
    complexes: Iterable[tuple[float, float]], precipitation_mm: float
) -> float:
    """Area-weighted runoff depth of soil-cover complexes, each with its own CN.

    The method of weighted Q of NEH 630 chapter 10 (p. 10-10): the runoff of each
    complex from its CN, weighted by its area, sum(A_i Q(CN_i)) / sum(A_i). It
    exceeds the runoff of the area-weighted CN (``runoff_mm`` of the composite CN)
    where the CN of the complexes differ, most for small storms; equal CN give equal
    runoff.

    Parameters
    ----------
    complexes : Iterable[tuple[float, float]]
        (CN for AMC II, area) of each complex; the area in any unit, total > 0.
    precipitation_mm : float
        Storm depth P [mm].

    Returns
    -------
    float
        Runoff depth Q [mm].
    """
    pairs = list(complexes)
    area = sum(a for _, a in pairs)
    return sum(runoff_mm(cn, precipitation_mm) * a for cn, a in pairs) / area
