"""
Unit tests for the data bounds written into tiles_metadata.json.

The frontend limits tile requests to these bounds, so a wrong union would
either hide real tiles or bring back 404s outside the data.
"""

import json
import sqlite3
from pathlib import Path

from scripts.generate_tiles import _publish_mbtiles, mbtiles_bounds, write_metadata


def _mbtiles(path: Path, bounds: str | None) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    if bounds is not None:
        conn.execute("INSERT INTO metadata VALUES ('bounds', ?)", (bounds,))
    conn.commit()
    conn.close()
    return path


def test_bounds_are_the_union_of_all_files(tmp_path):
    a = _mbtiles(tmp_path / "a.mbtiles", "15.8,50.9,16.2,51.1")
    b = _mbtiles(tmp_path / "b.mbtiles", "15.7,51.0,16.3,51.2")

    assert mbtiles_bounds([a, b]) == [15.7, 50.9, 16.3, 51.2]


def test_missing_files_and_files_without_valid_bounds_are_skipped(tmp_path):
    good = _mbtiles(tmp_path / "good.mbtiles", "15.8,50.9,16.2,51.1")
    empty = _mbtiles(tmp_path / "empty.mbtiles", None)
    broken = _mbtiles(tmp_path / "broken.mbtiles", "not,bounds")

    assert mbtiles_bounds([tmp_path / "missing.mbtiles", empty, broken, good]) == [
        15.8,
        50.9,
        16.2,
        51.1,
    ]
    assert mbtiles_bounds([tmp_path / "missing.mbtiles", empty]) is None


def test_metadata_holds_the_bounds_of_streams_and_catchments(tmp_path):
    _mbtiles(tmp_path / "streams_10000.mbtiles", "15.8,50.9,16.2,51.1")
    _mbtiles(tmp_path / "catchments_100000.mbtiles", "15.7,50.8,16.1,51.0")

    meta = json.loads(write_metadata(tmp_path, [10000, 100000]).read_text())

    assert meta["bounds"] == [15.7, 50.8, 16.2, 51.1]


def test_a_tileset_built_elsewhere_is_served_from_the_output_directory(tmp_path):
    built = tmp_path / "tmp"
    built.mkdir()
    mbtiles = _mbtiles(built / "streams_10000.mbtiles", "15.8,50.9,16.2,51.1")
    conn = sqlite3.connect(mbtiles)
    conn.execute(
        "CREATE TABLE tiles (zoom_level INT, tile_column INT, tile_row INT, tile_data)"
    )
    conn.execute("INSERT INTO tiles VALUES (8, 140, 170, ?)", (b"tile",))
    conn.commit()
    conn.close()
    output = tmp_path / "tiles"
    output.mkdir()
    # What an interrupted write on a network share leaves behind
    (output / "streams_10000.mbtiles").write_bytes(b"")
    (output / "streams_10000.mbtiles-journal").write_bytes(b"\0" * 512)

    _publish_mbtiles(mbtiles, output, has_pmtiles=False)

    # MBTiles rows are TMS: y = 2^8 - 1 - 170 = 85
    assert (output / "streams_10000" / "8" / "140" / "85.pbf").read_bytes() == b"tile"
    assert not (output / "streams_10000.mbtiles-journal").exists()
    assert not mbtiles.exists()
    meta = json.loads(write_metadata(output, [10000]).read_text())
    assert meta["bounds"] == [15.8, 50.9, 16.2, 51.1]
