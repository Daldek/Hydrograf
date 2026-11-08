"""Unit tests of core.cn_tables: the TR-55 covers of the land cover (ADR-075)."""

from itertools import chain

import pytest

from core.cn_tables import COVER_BY_SOURCE, HSG_GROUPS, complex_cn, cover_for
from core.land_cover import VALID_CATEGORIES
from scripts.import_landcover import (
    INDUSTRIAL_COMPLEX_CLASSES,
    INDUSTRIAL_POWER_PLANT_CLASSES,
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
    ("droga", "PTKM"),
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
        # Paved areas (TR-55 table 2-2a) and water surfaces (NEH 630 ch. 9, p. 9-1)
        ("droga", "PTKM", (98, 98, 98, 98)),
        ("woda", "PTWP", (98, 98, 98, 98)),
        # Open space, fair; dirt; newly graded areas (TR-55 table 2-2a)
        ("inny", "PTNZ:urządzenia", (49, 69, 79, 84)),
        ("inny", "PTPL:nieutwardzony", (72, 82, 87, 89)),
        ("inny", "PTWZ", (77, 86, 91, 94)),
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
