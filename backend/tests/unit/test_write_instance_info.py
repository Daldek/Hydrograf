"""instance.json: the area, set, NMT and soil groups of an instance, from its run."""

import hashlib
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from shapely.geometry import box

from scripts.write_instance_info import (
    INSTANCE_INFO_SCHEMA,
    build_instance_info,
    main,
)

NOW = "2026-11-09T12:00:00Z"


def _boundary(path: Path) -> Path:
    """A 2 km x 3 km rectangle (6 km²) in EPSG:2180."""
    gpd.GeoDataFrame(
        geometry=[box(400_000, 300_000, 402_000, 303_000)], crs="EPSG:2180"
    ).to_file(path, driver="GPKG")
    return path


def _identity(project: Path | str = "/srv/projects/h07") -> dict[str, Any]:
    """The identity of a set as SetInputs.identity() gives it and the record keeps."""
    return {
        "project": {"path": str(project), "name": "h07", "area_sha256": "0" * 64},
        "set": {
            "name": "2026-2",
            "closed_at": "2026-11-08T10:26:02Z",
            "closed_by": "local",
            "pins_sha256": "1" * 64,
            "pins_sha256_recorded": True,
            "pins": 727,
        },
        "store": "/srv/kartograf",
        "inputs": {
            "nmt": {
                "segment": "nmt/pl_1992_5m_evrf2007",
                "sheets": 709,
                "area_sheets": 708,
            },
            "bdot10k": ["3002", "0403", "3001"],
            "hsg": None,
            "unused": 0,
            "other_producers": 0,
        },
    }


@pytest.fixture
def boundary(tmp_path: Path) -> Path:
    return _boundary(tmp_path / "zlewnia_testowa.gpkg")


def test_a_run_from_a_set_names_the_project_its_counties_and_its_nmt(boundary):
    info = build_instance_info(
        generated_at=NOW,
        boundary=boundary,
        set_identity=_identity(),
        hsg_depth_rule="least-permeable",
    )

    assert info == {
        "schema": INSTANCE_INFO_SCHEMA,
        "area": {"name": "h07", "area_km2": 6.0, "boundary": "zlewnia_testowa.gpkg"},
        "counties": ["0403", "3001", "3002"],
        "nmt": {"resolution_m": 5.0, "segment": "nmt/pl_1992_5m_evrf2007"},
        "hsg": {
            "depth_rule": "least-permeable",
            "segment": "hsg/global_soilgrids_0-100cm_least-permeable_mean",
        },
        "set": {
            "project": "h07",
            "name": "2026-2",
            "closed_at": "2026-11-08T10:26:02Z",
        },
        "sources": None,
        "generated_at": NOW,
    }


def test_the_given_name_and_resolution_win_over_the_set(boundary):
    info = build_instance_info(
        generated_at=NOW,
        area_name="obszar h_07",
        boundary=boundary,
        set_identity=_identity(),
        nmt_resolution_m=1.0,
    )

    assert info["area"]["name"] == "obszar h_07"
    assert info["nmt"]["resolution_m"] == 1.0


def test_without_a_set_the_name_is_the_boundary_stem_and_nothing_is_credited(
    boundary,
):
    info = build_instance_info(
        generated_at=NOW, boundary=boundary, nmt_resolution_m=5.0
    )

    assert info["area"] == {
        "name": "zlewnia_testowa",
        "area_km2": 6.0,
        "boundary": "zlewnia_testowa.gpkg",
    }
    assert info["counties"] is None
    assert info["set"] is None
    assert info["nmt"] == {"resolution_m": 5.0, "segment": None}
    assert info["hsg"] is None  # nothing says which rule made the soil groups


def test_a_run_by_bbox_has_no_area():
    info = build_instance_info(generated_at=NOW, nmt_resolution_m=5.0)

    assert info["area"] == {"name": None, "area_km2": None, "boundary": None}


def test_the_cli_takes_the_area_of_the_project_the_set_record_names(tmp_path):
    project = tmp_path / "h07"
    (project / "obszary").mkdir(parents=True)
    area = _boundary(project / "obszary" / "area.gpkg")
    (project / "archiwista-project.json").write_text(
        json.dumps(
            {
                "schema": "archiwista-project/1",
                "name": "h07",
                "area": {
                    "path": "obszary/area.gpkg",
                    "sha256": hashlib.sha256(area.read_bytes()).hexdigest(),
                },
                "stores": [],
                "groups": [],
            }
        )
    )
    data = tmp_path / "data"
    data.mkdir()
    record = {
        "schema": "hydrograf-bootstrap-set/1",
        **_identity(project),
        "hsg_depth_rule": "topsoil",
    }
    (data / "bootstrap_set.json").write_text(json.dumps(record))
    frontend_data = tmp_path / "frontend-data"

    main(["--data-dir", str(data), "--frontend-data", str(frontend_data)])

    info = json.loads((frontend_data / "instance.json").read_text(encoding="utf-8"))
    assert info["area"] == {"name": "h07", "area_km2": 6.0, "boundary": "area.gpkg"}
    assert info["set"]["name"] == "2026-2"
    assert info["nmt"]["resolution_m"] == 5.0
    assert info["hsg"] == {
        "depth_rule": "topsoil",
        "segment": "hsg/global_soilgrids_0-5cm_mean",
    }
    assert not list(frontend_data.glob(".*.tmp"))


def test_the_cli_without_a_set_reads_the_resolution_of_the_saved_dem(
    tmp_path, boundary
):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    nmt = tmp_path / "data" / "nmt"
    nmt.mkdir(parents=True)
    with rasterio.open(
        nmt / "dem_mosaic.tif",
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(400_000, 303_000, 5, 5),
    ) as dst:
        dst.write(np.zeros((1, 2, 2), dtype="float32"))
    frontend_data = tmp_path / "frontend-data"

    main(
        [
            "--area-name",
            "zlewnia Kaczawy do Legnicy",
            "--boundary-file",
            str(boundary),
            "--hsg-depth-rule",
            "least-permeable",
            "--data-dir",
            str(tmp_path / "data"),
            "--frontend-data",
            str(frontend_data),
        ]
    )

    info = json.loads((frontend_data / "instance.json").read_text(encoding="utf-8"))
    assert info["area"]["name"] == "zlewnia Kaczawy do Legnicy"
    assert info["nmt"]["resolution_m"] == 5.0
    assert info["hsg"]["depth_rule"] == "least-permeable"
    assert info["set"] is None


def test_the_bootstrap_writes_its_run_and_only_warns_on_a_bad_boundary(
    tmp_path, boundary, monkeypatch, caplog
):
    """The file describes the instance: it never fails a run whose data are made."""
    import argparse

    from scripts import bootstrap

    monkeypatch.setattr(bootstrap, "FRONTEND_DIR", tmp_path / "frontend")
    args = argparse.Namespace(
        area_name=None,
        boundary_file=boundary,
        boundary_layer=None,
        resolution="1m",
    )
    written = tmp_path / "frontend" / "data" / "instance.json"

    bootstrap.write_instance(args, None, "topsoil")

    info = json.loads(written.read_text(encoding="utf-8"))
    assert info["area"]["name"] == "zlewnia_testowa"
    assert info["nmt"]["resolution_m"] == 1.0
    assert info["hsg"]["segment"] == "hsg/global_soilgrids_0-5cm_mean"

    written.unlink()
    args.boundary_file = tmp_path / "missing.gpkg"
    bootstrap.write_instance(args, None, "topsoil")

    assert not written.exists()
    assert "instance.json not written" in caplog.text
