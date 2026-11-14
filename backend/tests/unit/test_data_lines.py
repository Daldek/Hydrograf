"""
The lines of GUGiK's and ISRIC's data (Nogat DEV §20, DEV-20.9, DEV-20.10; ADR-085).

G names the GUGiK products a product is made of with the years their data were created
and the days they were downloaded, from the Kartograf metadata of the files the instance
used (``instance.json``); SG is fixed. The strip of the kit recognises G and SG by their
text, so they must equal its templates byte for byte.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

from core.attribution import (
    CATCHMENT,
    DRAINAGE,
    ELEVATION,
    GUGIK_SOURCE,
    SOILGRIDS_SOURCE,
    data_lines,
    gugik_source,
    instance_lines,
)
from core.data_sources import BDOT10K, NMT, SOILGRIDS, ProductDates
from scripts.write_instance_info import (
    bdot10k_dates,
    build_instance_info,
    merged_sources,
    nmt_dates,
    read_sources,
    write_instance_info,
)

KIT_SOURCES = (
    Path(__file__).resolve().parents[3] / "frontend" / "nogat" / "nogat-sources.js"
)


def _kit_line(mark: str) -> str:
    """A line of LINES of the kit's nogat-sources.js, as DEV §20 writes it."""
    text = KIT_SOURCES.read_text(encoding="utf-8")
    match = re.search(rf'^  {mark}: "(.*)",$', text, re.MULTILINE)
    assert match, mark
    return match[1]


def test_g_and_sg_are_the_templates_of_the_kit_byte_for_byte():
    """A drifted text would leave the strip without GK and SK."""
    template = GUGIK_SOURCE.format(
        products="`<products>`", period="`<period>`", date="`<date>`"
    )
    assert template == _kit_line("G")
    assert _kit_line("SG") == SOILGRIDS_SOURCE


def test_g_writes_one_value_or_the_first_and_last_with_dashes():
    dates = {
        NMT: ProductDates(frozenset({2025, 2020}), frozenset({"2026-10-29"})),
        BDOT10K: ProductDates(frozenset({2026}), frozenset({"2026-03-24"})),
    }

    assert gugik_source([BDOT10K, NMT], dates) == (
        "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, NMT, BDOT10k "
        "(wytworzono 2020–2026, pozyskano 2026-03-24 – 2026-10-29); dane przetworzone"
    )
    assert gugik_source([NMT], {NMT: dates[NMT]}) == (
        "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, NMT "
        "(wytworzono 2020–2025, pozyskano 2026-10-29); dane przetworzone"
    )


def test_a_product_the_instance_does_not_name_takes_no_line():
    dates = {NMT: ProductDates(frozenset({2025}), frozenset({"2026-10-29"}))}

    # A catchment of an instance without BDOT10k and SoilGrids: G of the NMT alone
    assert data_lines(CATCHMENT, dates).attribution == (gugik_source([NMT], dates),)
    # Without dates every product used takes its line, G before SG, no terms line
    lines = data_lines(CATCHMENT, None)
    assert lines.attribution == (
        gugik_source([NMT, BDOT10K], {}),
        SOILGRIDS_SOURCE,
    )
    assert lines.terms_notice == ()
    assert "b.d." in lines.attribution[0]


def _sidecar(path: Path, **fields) -> None:
    meta = {"schema": "kartograf-meta/1", "dataset": "pl.gugik.nmt_5m", **fields}
    path.write_bytes(b"data")
    path.with_name(path.name + ".meta.json").write_text(json.dumps(meta))


def _package(path: Path, last_change: str) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE gpkg_contents (table_name TEXT, last_change TEXT)")
        db.execute("INSERT INTO gpkg_contents VALUES ('OT_PTWP_A', ?)", (last_change,))


def test_the_dates_come_from_the_metadata_of_the_files(tmp_path):
    sheet = tmp_path / "N-33-130-B-d-4-4.asc"
    _sidecar(
        sheet,
        downloaded_at="2026-10-29T21:45:33+00:00",
        extra={"source": {"acquisition_date": "2025-04-26"}},
    )
    # A package downloaded by Kartograf 0.8.0, and one of an older pipeline without
    # metadata: its tables give the year, its file the day
    current = tmp_path / "bdot10k_teryt_0205.gpkg"
    _package(current, "2026-02-11T21:48:16.179Z")
    current.with_name(current.name + ".meta.json").write_text(
        json.dumps(
            {
                "schema": "kartograf-meta/1",
                "dataset": "pl.gugik.bdot10k",
                "downloaded_at": "2026-10-29T18:56:59+00:00",
                "extra": {"http": {"last_modified": "Fri, 05 Jun 2026 13:14:15 GMT"}},
            }
        )
    )
    old = tmp_path / "bdot10k_teryt_0219.gpkg"
    _package(old, "2025-09-04T12:00:00.000Z")
    os.utime(old, (1774310400, 1774310400))  # 2026-03-24 UTC

    assert nmt_dates([sheet]) == ProductDates(
        frozenset({2025}), frozenset({"2026-10-29"})
    )
    assert bdot10k_dates([current, old]) == ProductDates(
        frozenset({2026, 2025}), frozenset({"2026-10-29", "2026-03-24"})
    )


def test_the_api_dates_g_from_the_sources_of_instance_json(tmp_path):
    sources = {
        NMT: ProductDates(frozenset({2020, 2025}), frozenset({"2026-10-29"})),
        SOILGRIDS: ProductDates(frozenset(), frozenset({"2026-11-10"})),
    }
    info = build_instance_info(generated_at="2026-11-13T00:00:00Z", sources=sources)
    write_instance_info(tmp_path, info)

    assert instance_lines(ELEVATION, str(tmp_path)).attribution == (
        "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, NMT "
        "(wytworzono 2020–2025, pozyskano 2026-10-29); dane przetworzone",
    )
    # BDOT10k is not among the instance's data: the drainage is the NMT's alone
    assert instance_lines(DRAINAGE, str(tmp_path)).attribution == (
        gugik_source([NMT], sources),
    )
    # A later run that used BDOT10k only keeps the entries of the others
    run = {BDOT10K: ProductDates(frozenset({2026}), frozenset({"2026-11-13"}))}
    assert merged_sources(read_sources(tmp_path), run) == {**sources, **run}
