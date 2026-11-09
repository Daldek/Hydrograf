"""Bootstrap from a set of an Archiwista project (ADR-067), with the real Kartograf.

A store written offline by Kartograf's own writers holds three NMT sheets (the two
that the area covers and one beside them, plus a second version of one of them), the
BDOT10k packages of two counties and two HSG rasters, one covering the mosaic and one
inside it, with their SoilGrids inputs. Each test writes an ``archiwista-project/1``
file that pins versions of that store as Archiwista does and runs the bootstrap with
``--dry-run``: every check runs, nothing is processed, and a refusal ends with the
error document as the last line of standard error.
"""

import hashlib
import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kartograf
import pytest

from scripts.bootstrap import main
from tests.kartograf_offline import (
    Counties,
    GugikIndex,
    SoilRasters,
    bdot10k_counties,
    flight,
    gugik_index,
    no_network,
    soil_rasters,
)
from tests.kartograf_offline import offline as offline  # noqa: F401
from utils.archiwista_project import Pin, pins_digest
from utils.kartograf_set import set_inputs

# The area overlaps these two sheets; the third lies beside them, below the first.
AREA_SHEETS = ["N-33-130-D-d-1-1", "N-33-130-D-d-1-2"]
EXTRA_SHEET = "N-33-130-D-d-1-3"
# lon/lat: from the middle of the first sheet to the middle of the second
AREA = [
    [16.890625, 52.401042],
    [16.921875, 52.401042],
    [16.921875, 52.411458],
    [16.890625, 52.411458],
    [16.890625, 52.401042],
]
COUNTIES = ["0205", "0226"]
# The boxes of the HSG rasters (EPSG:2180): around the mosaic of the three sheets,
# and inside it
HSG_BOX = (350000, 500000, 365000, 510000)
SMALL_HSG_BOX = (356000, 504000, 358000, 506000)
SET = "Hydrograf 2020"
NMT = "nmt/pl_1992_5m_evrf2007/versions/"


@dataclass(frozen=True)
class Store:
    """The store of the module: its root and every version, by file stem."""

    root: Path
    versions: dict[str, list[str]]

    def version(self, stem: str, index: int = 0) -> str:
        return sorted(self.versions[stem])[index]

    def hsg(self, box: tuple[int, int, int, int]) -> str:
        stem = "_".join(map(str, box))
        (version,) = (v for v in self.versions[stem] if v.startswith("hsg/"))
        return version

    def pin(self, version: str) -> dict[str, Any]:
        """Return the pin of a version as Archiwista writes it."""
        path = self.root / version
        return {
            "producer": "kartograf",
            "version": version,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "unit": path.stem,
            "label": None,
            "pinned_at": "2026-11-02T12:00:00Z",
            "pinned_by": "piotr",
        }


def _box(values: tuple[int, int, int, int]) -> kartograf.BBox:
    min_x, min_y, max_x, max_y = values
    return kartograf.BBox(min_x, min_y, max_x, max_y, crs="EPSG:2180")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Store:
    """Write the store once, with Kartograf, as Archiwista's download jobs do."""
    root = tmp_path_factory.mktemp("set") / "store"
    sheets = [*AREA_SHEETS, EXTRA_SHEET]
    flights = [flight(sheet, "2020-04-18", "73715") for sheet in sheets]
    newer = flight(AREA_SHEETS[0], "2023-05-01", "84000")
    nmt = kartograf.GugikProvider(vertical_crs="EVRF2007", resolution="5m")
    with no_network():
        with gugik_index(GugikIndex(flights)):
            kartograf.DownloadManager(nmt, root=root).download_sheets(sheets)
        with gugik_index(GugikIndex([*flights, newer])):
            kartograf.DownloadManager(nmt, root=root).download_sheets(
                AREA_SHEETS[:1], update="force"
            )
        with bdot10k_counties(Counties(COUNTIES)):
            kartograf.download_landcover(
                product="bdot10k", root=root, bbox=_box(HSG_BOX), cache=False
            )
        with soil_rasters(SoilRasters()):
            for box in (HSG_BOX, SMALL_HSG_BOX):
                kartograf.calculate_hsg(
                    root=root, bbox=_box(box), depth="0-5cm", cache=False
                )
    versions: dict[str, list[str]] = {}
    for path in root.glob("*/*/versions/**/*"):
        if path.is_file() and not path.name.endswith(".meta.json"):
            versions.setdefault(path.stem, []).append(path.relative_to(root).as_posix())
    return Store(root, versions)


class Project:
    """An Archiwista project directory of a test; its file is written on demand."""

    def __init__(self, directory: Path, store: Store) -> None:
        self.directory = directory
        self.store = store
        self.area = directory / "obszary" / "88627fe9cd5763de.geojson"
        self.area.parent.mkdir(parents=True)
        feature = {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [AREA]},
        }
        self.area.write_text(
            json.dumps({"type": "FeatureCollection", "features": [feature]})
        )
        pins = [store.version(sheet) for sheet in [*AREA_SHEETS, EXTRA_SHEET]]
        pins += [store.version(teryt) for teryt in COUNTIES]
        # the HSG raster around the mosaic and its three SoilGrids inputs
        pins += sorted(store.versions["_".join(map(str, HSG_BOX))])
        self.document: dict[str, Any] = {
            "schema": "archiwista-project/1",
            "name": "Kaczawa",
            "description": "Kaczawa do Legnicy",
            "created_at": "2026-11-01T17:37:09Z",
            "created_by": "piotr",
            "area": {
                "path": "obszary/88627fe9cd5763de.geojson",
                "sha256": hashlib.sha256(self.area.read_bytes()).hexdigest(),
            },
            "stores": [{"producer": "kartograf", "root": str(store.root)}],
            "groups": [
                {
                    "name": SET,
                    "origin": {"kind": "local", "selections": [{"from": "file"}]},
                    "pins": [store.pin(version) for version in pins],
                }
            ],
        }

    @property
    def group(self) -> dict[str, Any]:
        group: dict[str, Any] = self.document["groups"][0]
        return group

    def close(self) -> None:
        """Close the set as Archiwista does: state, when, who and the digest."""
        self.group.update(
            state="closed",
            closed_at="2026-11-03T08:15:00Z",
            closed_by="piotr",
            pins_sha256=pins_digest(
                Pin(p["producer"], p["version"], p["sha256"], p["size_bytes"])
                for p in self.group["pins"]
            ),
        )

    def drop(self, prefix: str) -> None:
        """Remove the pins whose version starts with ``prefix``."""
        pins = self.group["pins"]
        self.group["pins"] = [p for p in pins if not p["version"].startswith(prefix)]

    def write(self) -> Path:
        (self.directory / "archiwista-project.json").write_text(
            json.dumps(self.document, ensure_ascii=False), encoding="utf-8"
        )
        return self.directory


@pytest.fixture
def project(tmp_path: Path, store: Store) -> Project:
    return Project(tmp_path / "kaczawa", store)


@dataclass
class Run:
    """The outcome of ``python -m scripts.bootstrap`` in this process."""

    code: int
    out: str
    err: str

    @property
    def document(self) -> dict[str, Any]:
        """The error document: the last line of standard error."""
        document: dict[str, Any] = json.loads(self.err.strip().splitlines()[-1])
        return document


@pytest.fixture
def bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., Run]:
    """Run the bootstrap with ``--dry-run``; PRG answers ``counties``."""

    def run(*args: str, counties: Counties | None = None) -> Run:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "bootstrap",
                *args,
                "--output",
                str(tmp_path / "data"),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--dry-run",
            ],
        )
        with bdot10k_counties(counties or Counties(COUNTIES)):
            try:
                main()
                code = 0
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 1
        captured = capsys.readouterr()
        return Run(code, captured.out, captured.err)

    return run


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
    }


@pytest.mark.usefixtures("offline")
class TestClosedSet:
    def test_a_set_without_state_gives_its_pinned_files(self, project, tmp_path):
        """A set written before sets had a state is closed; its digest is computed."""
        project.write()

        with bdot10k_counties(Counties(COUNTIES)):
            inputs = set_inputs(
                project.directory,
                SET.upper(),
                resolution="5m",
                cache_dir=tmp_path / "cache",
            )

        store = project.store
        # the pinned sheet beside the area is part of the mosaic too
        assert inputs.sheets == {
            sheet: store.root / store.version(sheet)
            for sheet in sorted([*AREA_SHEETS, EXTRA_SHEET])
        }
        assert inputs.required_sheets == tuple(AREA_SHEETS)
        assert inputs.counties == {
            teryt: store.root / store.version(teryt) for teryt in COUNTIES
        }
        assert inputs.hsg == store.root / store.hsg(HSG_BOX)
        assert len(inputs.unused) == 3  # the SoilGrids inputs of the HSG raster
        identity = inputs.identity()["set"]
        assert identity["closed_at"] is None
        assert identity["pins_sha256"] == pins_digest(inputs.pin_set.pins)
        assert identity["pins_sha256_recorded"] is False

    def test_dry_run_of_a_closed_set_in_the_shared_store(
        self, project, bootstrap, monkeypatch
    ):
        """HYDROGRAF_KARTOGRAF_ROOT names the project's store, as in staging."""
        project.close()
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", str(project.store.root))
        before = _snapshot(project.store.root)

        run = bootstrap("--project", str(project.write()), "--set", SET)

        assert run.code == 0, run.err
        assert "nmt/pl_1992_5m_evrf2007: 3 ark. (obszar projektu: 2 ark.)" in run.out
        assert "powiaty mozaiki (PRG): 0205, 0226" in run.out
        digest = project.group["pins_sha256"]
        assert f"pins_sha256: {digest} (z pliku projektu)" in run.out
        assert _snapshot(project.store.root) == before

    def test_a_skipped_step_needs_nothing_from_the_set(self, project, bootstrap):
        project.drop("hsg/")

        run = bootstrap("--project", str(project.write()), "--set", SET, "--skip-hsg")

        assert run.code == 0, run.err
        assert "raster z zestawu -" in run.out


def _first_pin(**members: Any) -> Callable[[Project], None]:
    def change(project: Project) -> None:
        project.group["pins"][0].update(members)

    return change


def _set(**members: Any) -> Callable[[Project], None]:
    def change(project: Project) -> None:
        project.group.update(members)

    return change


def _drop(prefix: str) -> Callable[[Project], None]:
    def change(project: Project) -> None:
        project.drop(prefix)

    return change


def _schema(project: Project) -> None:
    project.document["schema"] = "archiwista-project/2"


def _area_gone(project: Project) -> None:
    project.area.unlink()


def _area_changed(project: Project) -> None:
    project.area.write_text(project.area.read_text() + "\n")


def _wrong_digest(project: Project) -> None:
    project.close()
    project.group["pins_sha256"] = "0" * 64


def _no_store(project: Project) -> None:
    project.document["stores"] = []


def _not_a_store(project: Project) -> None:
    (project.directory / "empty").mkdir()
    project.document["stores"] = [{"producer": "kartograf", "root": "empty"}]


def _second_version(project: Project) -> None:
    store = project.store
    project.group["pins"].append(store.pin(store.version(AREA_SHEETS[0], 1)))


def _small_hsg_only(project: Project) -> None:
    project.drop("hsg/")
    project.group["pins"].append(project.store.pin(project.store.hsg(SMALL_HSG_BOX)))


MISSING_VERSION = f"{NMT}N-33/130/D/d/1/1/2019-01-01_1_00000000/N-33-130-D-d-1-1.asc"
REFUSALS = {
    "a newer schema": (_schema, "unsupported", "project_schema_unsupported", 15),
    "an unknown state": (_set(state="draft"), "data_error", "project_file_invalid", 7),
    "the area file gone": (_area_gone, "not_found", "area_missing", 3),
    "the area file changed": (_area_changed, "data_error", "area_changed", 7),
    "an open set": (_set(state="open"), "conflict", "set_open", 4),
    "a digest the pins do not give": (
        _wrong_digest,
        "data_error",
        "set_digest_mismatch",
        7,
    ),
    "no Kartograf store": (_no_store, "store_unavailable", "store_missing", 8),
    "a root without a marker": (_not_a_store, "store_unavailable", "store_missing", 8),
    "a pinned file missing": (
        _first_pin(version=MISSING_VERSION),
        "not_found",
        "pin_missing",
        3,
    ),
    "a pinned file changed": (
        _first_pin(sha256="f" * 64),
        "data_error",
        "pin_changed",
        7,
    ),
    "a sheet of the area missing": (
        _drop(f"{NMT}N-33/130/D/d/1/2/"),
        "no_data",
        "set_sheets_missing",
        14,
    ),
    "two versions of a sheet": (_second_version, "conflict", "set_unit_ambiguous", 4),
    "an HSG raster inside the mosaic": (
        _small_hsg_only,
        "no_data",
        "set_hsg_missing",
        14,
    ),
}


@pytest.mark.usefixtures("offline")
class TestRefusals:
    @pytest.mark.parametrize("case", REFUSALS)
    def test_a_refusal_ends_with_its_error_document(self, project, bootstrap, case):
        change, code, reason, exit_code = REFUSALS[case]
        change(project)

        run = bootstrap("--project", str(project.write()), "--set", SET)

        assert run.code == exit_code
        assert run.document["schema"] == "hydrograf-error/1"
        assert run.document["code"] == code
        assert run.document["details"]["reason"] == reason
        assert run.document["exit_code"] == exit_code
        assert run.document["hint"]
        assert "BŁĄD: " in run.err

    def test_no_project_file(self, bootstrap, tmp_path):
        run = bootstrap("--project", str(tmp_path), "--set", SET)

        assert run.code == 3
        assert run.document["details"]["reason"] == "project_file_missing"

    def test_a_fill_setting_that_is_not_true_or_false(
        self, project, bootstrap, tmp_path
    ):
        # A quoted "false" is a string, and a string is true
        config = tmp_path / "config.yaml"
        config.write_text('dem:\n  fill_enclosed_nodata: "false"\n', encoding="utf-8")

        run = bootstrap(
            "--project", str(project.write()), "--set", SET, "--config", str(config)
        )

        assert run.code == 2
        assert run.document["details"]["reason"] == "invalid_arguments"
        assert "dem.fill_enclosed_nodata" in run.err

    def test_the_missing_sheets_are_named(self, project, bootstrap):
        project.drop(f"{NMT}N-33/130/D/d/1/2/")

        run = bootstrap("--project", str(project.write()), "--set", SET)

        assert run.document["details"]["units"] == [AREA_SHEETS[1]]

    def test_a_county_of_the_mosaic_missing_from_the_set(self, project, bootstrap):
        run = bootstrap(
            "--project",
            str(project.write()),
            "--set",
            SET,
            counties=Counties([*COUNTIES, "0261"]),
        )

        assert run.code == 14
        assert run.document["details"]["reason"] == "set_counties_missing"
        assert run.document["details"]["units"] == ["0261"]

    def test_the_county_register_not_answering(self, project, bootstrap):
        class Unavailable(Counties):
            def counties(self, bbox: Any, timeout: int = 30) -> list[str]:
                raise kartograf.DownloadError("PRG: HTTP 503")

        run = bootstrap(
            "--project",
            str(project.write()),
            "--set",
            SET,
            counties=Unavailable(COUNTIES),
        )

        assert run.code == 5
        assert run.document["details"]["reason"] == "prg_unavailable"

    def test_an_unknown_set_lists_the_sets_of_the_project(self, project, bootstrap):
        run = bootstrap("--project", str(project.write()), "--set", "2021")

        assert run.code == 3
        assert run.document["details"]["sets"] == [SET]

    def test_a_store_other_than_the_shared_one(
        self, project, bootstrap, monkeypatch, tmp_path
    ):
        (tmp_path / "other").mkdir()
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", str(tmp_path / "other"))

        run = bootstrap("--project", str(project.write()), "--set", SET)

        assert run.code == 2
        assert run.document["details"]["reason"] == "store_mismatch"

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
    def test_an_unreadable_pinned_file(self, project, bootstrap, tmp_path):
        copy = tmp_path / "store"
        shutil.copytree(project.store.root, copy)
        project.document["stores"] = [{"producer": "kartograf", "root": str(copy)}]
        (copy / project.group["pins"][0]["version"]).chmod(0)

        run = bootstrap("--project", str(project.write()), "--set", SET)

        assert run.code == 9
        assert run.document["details"]["reason"] == "pin_unreadable"


@pytest.mark.usefixtures("offline")
class TestAreaOptionsAgainstASharedStore:
    @pytest.mark.parametrize(
        "area",
        [
            ["--bbox", "16.89,52.40,16.92,52.41"],
            ["--sheets", AREA_SHEETS[0]],
            ["--boundary-file", "obszar.gpkg"],
        ],
    )
    def test_an_area_option_is_refused_before_anything_is_written(
        self, bootstrap, monkeypatch, tmp_path, area
    ):
        shared = tmp_path / "shared"
        shared.mkdir()
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", str(shared))

        run = bootstrap(*area)

        assert run.code == 12
        assert run.document["code"] == "forbidden"
        assert run.document["details"]["reason"] == "shared_store_read_only"
        assert list(shared.iterdir()) == []
        assert not (tmp_path / "cache").exists()

    def test_a_project_without_a_set_is_an_invalid_call(self, bootstrap, tmp_path):
        run = bootstrap("--project", str(tmp_path))

        assert run.code == 2
        assert run.document["code"] == "validation_error"
        assert run.document["details"]["reason"] == "invalid_arguments"


def test_the_digest_is_the_one_archiwista_writes_on_close():
    """The test vector that Archiwista's draft sets use too (Nogat plan, D12)."""
    pins = [
        Pin("kartograf", "nmt/pl_1992_5m_evrf2007/versions/b.asc", "b" * 64, 1),
        Pin("kartograf", "hsg/a.tif", "a" * 64, 1),
    ]

    assert pins_digest(pins) == (
        "e7319a8d77a126fc2eb12f46b92ef5ac98a5b2132808474eebbb222fd5c691fe"
    )
