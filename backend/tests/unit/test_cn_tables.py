"""Unit tests of core.cn_tables: the TR-55 covers of the land cover and the runoff
of the soil-cover complexes (ADR-075)."""

from itertools import chain

import pytest

from core.cn_tables import (
    COVER_BY_SOURCE,
    HSG_GROUPS,
    complex_cn,
    cover_for,
    runoff_mm,
    weighted_runoff_mm,
)
from core.land_cover import VALID_CATEGORIES
from scripts.import_landcover import (
    INDUSTRIAL_COMPLEX_CLASSES,
    INDUSTRIAL_POWER_PLANT_CLASSES,
    OPEN_SPACE_COMPLEX_CLASSES,
    PT_KIND_CLASSES,
    PT_LAYER_CLASSES,
)

# Every source (category, bdot_class) that the land cover import writes; a PT layer
# that it does not know is `inny` under its own code and takes the cover of `inny`.
IMPORTED_SOURCES = {
    (cls.category, cls.bdot_class)
    for cls in chain(
        PT_LAYER_CLASSES.values(),
        PT_KIND_CLASSES.values(),
        INDUSTRIAL_COMPLEX_CLASSES.values(),
        INDUSTRIAL_POWER_PLANT_CLASSES.values(),
        OPEN_SPACE_COMPLEX_CLASSES.values(),
    )
}

# The sources of the import that take the TR-55 cover of their category, by the
# decisions of ADR-075 (the author's of 2026-11-08: arable land is small grain, PTUT
# is meadow, solar farms on PTNZ are open space). A source that the import adds needs
# an entry here or in COVER_BY_SOURCE.
SOURCES_WITH_THE_CATEGORY_COVER = {
    ("las", "PTLZ"),
    ("łąka", "PTTR:trawiasta"),
    ("łąka", "PTUT"),
    ("łąka", "PTRK"),
    ("grunt_orny", "PTTR:grunty orne"),
    ("grunt_orny", "PTTR"),
    ("zabudowa_mieszkaniowa", "PTZB:jednorodzinna"),
    ("zabudowa_mieszkaniowa", "PTZB:pozostała"),
    ("zabudowa_mieszkaniowa", "PTZB"),
    ("zabudowa_przemysłowa", "PTZB:przem.-skład."),
    ("zabudowa_przemysłowa", "PTNZ:przem.-skład."),
    ("zabudowa_przemysłowa", "KUPG:zakład prod."),
    ("zabudowa_przemysłowa", "KUPG:baza paliw"),
    ("zabudowa_przemysłowa", "KUPG:gazownia"),
    ("zabudowa_przemysłowa", "KUPG:elektrociepł."),
    ("zabudowa_przemysłowa", "KUPG:zakład utyliz."),
    ("zabudowa_przemysłowa", "KUPG:huta"),
    ("zabudowa_przemysłowa", "KUPG:rafineria"),
    ("zabudowa_przemysłowa", "KUPG:zakład metal."),
    ("zabudowa_przemysłowa", "KUPG:el. cieplna"),
    ("zabudowa_przemysłowa", "KUPG:el. atomowa"),
    ("droga", "PTPL:utwardzony"),
    ("droga", "PTPL"),
    ("woda", "PTWP"),
    ("inny", "PTNZ:urządzenia"),
    ("inny", "PTNZ"),
    ("inny", "PTGN"),
    ("inny", "PTSO"),
}


def test_every_source_of_the_import_has_its_cover_decided():
    """A source that the import writes has a cover of its own or its category's.

    The keys of COVER_BY_SOURCE are strings of the import exactly: a source without
    a decision fails, and so does a key that the import does not write.
    """
    own = set(COVER_BY_SOURCE)

    assert not own & SOURCES_WITH_THE_CATEGORY_COVER
    assert sorted(IMPORTED_SOURCES - own - SOURCES_WITH_THE_CATEGORY_COVER) == []
    assert sorted((own | SOURCES_WITH_THE_CATEGORY_COVER) - IMPORTED_SOURCES) == []


@pytest.mark.parametrize("category", sorted(VALID_CATEGORIES))
def test_every_category_of_the_table_has_a_cn_on_every_soil_group(category):
    """A row of any category the constraint admits gets a CN, rising from A to D."""
    cns = [complex_cn(category, None, group) for group in HSG_GROUPS]

    assert all(30 <= cn <= 98 for cn in cns)
    assert cns == sorted(cns)


@pytest.mark.parametrize(
    ("category", "bdot_class", "expected"),
    [
        # TR-55 table 2-2c: woods, good; meadow
        ("las", "PTLZ", (30, 55, 70, 77)),
        ("łąka", "PTTR:trawiasta", (30, 58, 71, 78)),
        # TR-55 table 2-2b: small grain, straight row, good
        ("grunt_orny", "PTTR:grunty orne", (63, 75, 83, 87)),
        # TR-55 table 2-2a: residential 1/3 acre and 1/8 acre, industrial, commercial
        ("zabudowa_mieszkaniowa", "PTZB:jednorodzinna", (57, 72, 81, 86)),
        ("zabudowa_mieszkaniowa", "PTZB:wielorodzinna", (77, 85, 90, 92)),
        ("zabudowa_przemysłowa", "KUPG:zakład prod.", (81, 88, 91, 93)),
        ("zabudowa_przemysłowa", "PTZB:handl.-usług.", (89, 92, 94, 95)),
        # TR-55 table 2-2a: paved; paved road with open ditches incl. right-of-way
        ("droga", "PTPL:utwardzony", (98, 98, 98, 98)),
        ("droga", "PTKM", (83, 89, 92, 93)),
        # Water surfaces (NEH 630 ch. 9, p. 9-1)
        ("woda", "PTWP", (98, 98, 98, 98)),
        # Open space, fair; dirt; newly graded areas (TR-55 table 2-2a)
        ("inny", "PTNZ:urządzenia", (49, 69, 79, 84)),
        ("inny", "PTPL:nieutwardzony", (72, 82, 87, 89)),
        ("inny", "PTWZ", (77, 86, 91, 94)),
        # Open space, good: the lawns of parks, sports grounds and airfields (ADR-078)
        ("inny", "KUSK:park", (39, 61, 74, 80)),
    ],
)
def test_cn_is_the_tr55_row_of_the_cover_of_the_source(category, bdot_class, expected):
    assert tuple(complex_cn(category, bdot_class, g) for g in HSG_GROUPS) == expected


def test_a_source_cover_applies_only_in_its_category():
    """PTWZ is bare ground in `inny`; imports before ADR-074 have it in `łąka`."""
    assert complex_cn("inny", "PTWZ", "B") == 86
    assert complex_cn("łąka", "PTWZ", "B") == 58


@pytest.mark.parametrize("bdot_class", [None, "PTZB", "PTZB:pozostała", "XYZ"])
def test_a_source_without_its_own_cover_takes_the_cover_of_the_category(bdot_class):
    """Plain layer codes (imports before ADR-074), other kinds and unknown values."""
    assert cover_for("zabudowa_mieszkaniowa", bdot_class) == cover_for(
        "zabudowa_mieszkaniowa", None
    )
    assert complex_cn("zabudowa_mieszkaniowa", bdot_class, "B") == 72


def test_a_category_outside_the_constraint_is_an_error():
    with pytest.raises(KeyError):
        complex_cn("forest", None, "B")


def _scs_runoff_mm(cn, precipitation_mm):
    """Q of the SCS-CN equation, Ia = 0.2 S (NEH 630 ch. 10), in mm."""
    s = 25400 / cn - 254
    ia = 0.2 * s
    if precipitation_mm <= ia:
        return 0.0
    return (precipitation_mm - ia) ** 2 / (precipitation_mm - ia + s)


def test_complexes_of_very_different_cn_run_off_more_than_their_composite_cn():
    """Forest on A (30) and pavement (98), equal areas, P = 25 mm (NEH 630 p. 10-10).

    The composite CN 64 holds back Ia = 28.6 mm, more than the storm: no runoff; the
    pavement alone gives 19.7 mm over its half of the watershed.
    """
    complexes = [(30, 1.0), (98, 1.0)]

    weighted = weighted_runoff_mm(complexes, 25.0)
    composite = runoff_mm(64.0, 25.0)

    assert composite == 0.0
    assert weighted == pytest.approx(_scs_runoff_mm(98, 25.0) / 2)
    assert weighted == pytest.approx(9.85, abs=0.01)
    assert weighted > composite


def test_complexes_of_equal_cn_run_off_as_their_composite_cn():
    complexes = [(75, 3.0), (75, 7.0)]

    weighted = weighted_runoff_mm(complexes, 25.0)

    assert weighted == pytest.approx(runoff_mm(75.0, 25.0))
    assert weighted == pytest.approx(_scs_runoff_mm(75, 25.0))
    assert weighted == pytest.approx(0.70, abs=0.01)
