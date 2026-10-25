"""Tests for the upload, sewer config, status and delete routes of the admin API.

The routes write real files, so the directories they use are redirected into tmp_path;
the database session is a stand-in whose answers each test sets.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import geopandas as gpd
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints import admin
from api.errors import install_error_handlers
from core.database import get_db


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def client(db):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router, prefix="/api/admin")
    app.dependency_overrides[verify_admin_key] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def geojson(*geometries):
    return gpd.GeoDataFrame(geometry=list(geometries), crs="EPSG:4326").to_json()


def upload(client, url, name, content, kind="application/geo+json"):
    if isinstance(content, str):
        content = content.encode()
    return client.post(url, files={"file": (name, content, kind)})


CATCHMENT = Polygon([(16.9, 52.4), (17.1, 52.4), (17.1, 52.5), (16.9, 52.5)])
INLETS = [Point(16.95, 52.45), Point(16.96, 52.46)]
PIPE = LineString([(16.95, 52.45), (16.96, 52.46)])


@pytest.fixture(
    params=[
        ("/api/admin/bootstrap/upload-boundary", "BOUNDARY_DIR", "MAX_UPLOAD_SIZE_MB"),
        ("/api/admin/sewer/upload", "DATA_SEWER", "MAX_SEWER_UPLOAD_MB"),
    ],
    ids=["boundary", "sewer"],
)
def target(request, tmp_path, monkeypatch):
    """Each upload route with its directory redirected into tmp_path."""
    url, directory_name, limit_name = request.param
    directory = tmp_path / "uploads"
    monkeypatch.setattr(admin, directory_name, directory)
    return SimpleNamespace(
        url=url, directory=directory, limit_name=limit_name, valid=geojson(CATCHMENT)
    )


def stored(directory):
    return sorted(p.name for p in directory.glob("*")) if directory.exists() else []


class TestUploadRules:
    """What both upload routes accept, refuse and clean up."""

    def test_file_types_outside_the_allowlist_are_refused(self, client, target):
        response = upload(client, target.url, "payload.exe", target.valid)

        assert response.status_code == 400
        details = response.json()["details"]
        assert details["reason"] == "invalid_file_type"
        assert details["suffix"] == ".exe"
        assert ".geojson" in details["allowed"]
        assert stored(target.directory) == []

    def test_the_extension_check_ignores_case(self, client, target):
        response = upload(client, target.url, "AREA.GeoJSON", target.valid)

        assert response.status_code == 200

    def test_a_file_over_the_size_limit_is_refused(self, client, target, monkeypatch):
        monkeypatch.setattr(admin, target.limit_name, 0.001)  # about 1 KiB

        response = upload(client, target.url, "big.geojson", b" " * 4096)

        assert response.status_code == 400
        details = response.json()["details"]
        assert details["reason"] == "file_too_large"
        assert details["max_mb"] == 0.001
        assert stored(target.directory) == []

    def test_a_path_in_the_file_name_cannot_leave_the_upload_directory(
        self, client, target, tmp_path
    ):
        response = upload(client, target.url, "../../escape.geojson", target.valid)

        assert response.status_code == 200
        name = response.json()["filename"]
        assert "/" not in name
        assert name.endswith("_escape.geojson")
        assert stored(target.directory) == [name]
        assert not list(tmp_path.glob("escape*"))

    def test_two_uploads_of_one_name_do_not_overwrite_each_other(self, client, target):
        first = upload(client, target.url, "area.geojson", target.valid)
        second = upload(client, target.url, "area.geojson", target.valid)

        assert first.json()["filename"] != second.json()["filename"]
        assert len(stored(target.directory)) == 2

    def test_content_that_is_not_geodata_is_refused_and_removed(self, client, target):
        response = upload(client, target.url, "broken.geojson", "not geodata at all")

        assert response.status_code == 400
        assert response.json()["details"]["reason"] in {
            "invalid_boundary_file",
            "invalid_geodata",
        }
        assert stored(target.directory) == []


class TestUploadBoundary:
    def test_the_boundary_is_described_in_wgs84_and_square_kilometres(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(admin, "BOUNDARY_DIR", tmp_path / "boundary")

        response = upload(
            client,
            "/api/admin/bootstrap/upload-boundary",
            "zlewnia.geojson",
            geojson(CATCHMENT),
        )

        body = response.json()
        assert response.status_code == 200
        assert body["filename"].endswith("_zlewnia.geojson")
        assert body["n_features"] == 1
        assert body["bbox_wgs84"] == pytest.approx([16.9, 52.4, 17.1, 52.5])
        # 0.2 degrees of longitude at 52.45 N x 0.1 degree of latitude
        assert body["area_km2"] == pytest.approx(0.2 * 67.8 * 0.1 * 111.2, rel=0.03)


class TestUploadSewer:
    @pytest.fixture(autouse=True)
    def _sewer_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(admin, "DATA_SEWER", tmp_path / "sewer")

    @pytest.mark.parametrize(
        ("geometries", "kind", "geometry_types"),
        [
            (INLETS, "points_only", ["Point"]),
            ([PIPE], "lines_only", ["LineString"]),
        ],
    )
    def test_the_layout_of_the_file_is_detected(
        self, client, geometries, kind, geometry_types
    ):
        response = upload(
            client, "/api/admin/sewer/upload", "net.geojson", geojson(*geometries)
        )

        body = response.json()
        assert response.status_code == 200
        assert body["features"] == len(geometries)
        assert body["geometry_types"] == geometry_types
        assert body["detected_format"] == kind
        assert len(body["layers"]) == 1

    @pytest.mark.filterwarnings("ignore:More than one layer found")
    def test_a_geopackage_with_points_and_lines_is_detected_as_both(
        self, client, tmp_path
    ):
        package = tmp_path / "net.gpkg"
        gpd.GeoDataFrame(geometry=INLETS, crs="EPSG:2180").to_file(
            package, layer="inlets", driver="GPKG"
        )
        gpd.GeoDataFrame(geometry=[PIPE], crs="EPSG:2180").to_file(
            package, layer="pipes", driver="GPKG"
        )

        response = upload(
            client,
            "/api/admin/sewer/upload",
            "net.gpkg",
            package.read_bytes(),
            "application/geopackage+sqlite3",
        )

        body = response.json()
        assert response.status_code == 200
        assert body["detected_format"] == "points_and_lines"
        assert sorted(body["layers"]) == ["inlets", "pipes"]


class TestSewerConfig:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        (tmp_path / "data" / "sewer").mkdir(parents=True)
        (tmp_path / "data" / "sewer" / "net.gpkg").write_bytes(b"")
        monkeypatch.setattr(admin, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(admin, "CONFIG_PATH", tmp_path / "config.yaml")
        return tmp_path

    def _saved(self, project):
        return yaml.safe_load((project / "config.yaml").read_text())["sewer"]

    def test_a_source_outside_the_project_is_forbidden(self, client, project):
        response = client.post(
            "/api/admin/sewer/config",
            json={"enabled": True, "source_path": "../../etc/passwd"},
        )

        assert response.status_code == 403
        assert response.json()["details"]["reason"] == "path_outside_project"
        assert not (project / "config.yaml").exists()

    def test_a_source_that_does_not_exist_is_not_found(self, client, project):
        response = client.post(
            "/api/admin/sewer/config",
            json={"enabled": True, "source_path": "data/sewer/gone.gpkg"},
        )

        assert response.status_code == 404
        assert response.json()["details"]["reason"] == "source_file_missing"

    def test_settings_are_merged_into_the_config_file(self, client, project):
        client.post(
            "/api/admin/sewer/config",
            json={
                "enabled": True,
                "source_path": "data/sewer/net.gpkg",
                "lines_layer": "pipes",
                "points_layer": "inlets",
                "field_mapping": {"diameter": "DN"},
            },
        )
        response = client.post(
            "/api/admin/sewer/config",
            json={"enabled": False, "field_mapping": {"material": "MAT"}},
        )

        assert response.status_code == 200
        assert response.json()["next_step"] is None
        assert self._saved(project) == {
            "enabled": False,
            "source": {
                "type": "file",
                "path": "data/sewer/net.gpkg",
                "lines_layer": "pipes",
                "points_layer": "inlets",
            },
            "field_mapping": {"diameter": "DN", "material": "MAT"},
        }

    def test_enabling_asks_for_a_pipeline_run(self, client, project):
        response = client.post("/api/admin/sewer/config", json={"enabled": True})

        assert response.json()["message"] == "Sewer enabled"
        assert response.json()["next_step"]


class TestSewerStatus:
    def test_counts_come_from_the_tables_and_the_settings_from_the_config(
        self, client, db, tmp_path, monkeypatch
    ):
        config = tmp_path / "config.yaml"
        config.write_text(
            yaml.dump({"sewer": {"enabled": True, "source": {"path": "data/net.gpkg"}}})
        )
        monkeypatch.setattr(admin, "CONFIG_PATH", config)
        db.execute.side_effect = [
            SimpleNamespace(scalar=lambda: 5),
            SimpleNamespace(scalar=lambda: 4),
            [("inlet", 3), ("outlet", 2)],
        ]

        body = client.get("/api/admin/sewer/status").json()

        assert body["loaded"] is True
        assert (body["nodes"], body["edges"]) == (5, 4)
        assert body["node_types"] == {"inlet": 3, "outlet": 2}
        assert body["config"] == {
            "enabled": True,
            "source_path": "data/net.gpkg",
            "source_type": "file",
        }

    def test_without_data_nothing_is_loaded(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr(admin, "CONFIG_PATH", tmp_path / "none.yaml")
        db.execute.side_effect = [
            SimpleNamespace(scalar=lambda: 0),
            SimpleNamespace(scalar=lambda: 0),
        ]

        body = client.get("/api/admin/sewer/status").json()

        assert body["loaded"] is False
        assert body["node_types"] == {}

    def test_a_database_without_the_sewer_tables_reports_nothing_loaded(
        self, client, db
    ):
        db.execute.side_effect = RuntimeError('relation "sewer_nodes" does not exist')

        response = client.get("/api/admin/sewer/status")

        assert response.status_code == 200
        assert response.json()["loaded"] is False


class TestSewerDelete:
    def test_data_files_and_tables_are_cleared(self, client, db, tmp_path, monkeypatch):
        sewer = tmp_path / "sewer"
        sewer.mkdir()
        (sewer / "net.gpkg").write_bytes(b"data")
        locked = sewer / "locked.shp"
        locked.write_bytes(b"data")
        locked.chmod(0o400)
        monkeypatch.setattr(admin, "DATA_SEWER", sewer)

        response = client.delete("/api/admin/sewer/delete")

        assert response.status_code == 200
        assert response.json()["pipeline_dirty"] is True
        assert not sewer.exists()
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("TRUNCATE TABLE sewer_network" in s for s in statements)
        assert any("TRUNCATE TABLE sewer_nodes" in s for s in statements)
        assert any("is_sewer_augmented = FALSE" in s for s in statements)
        db.commit.assert_called_once()

    def test_without_a_data_directory_only_the_tables_are_cleared(
        self, client, db, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(admin, "DATA_SEWER", tmp_path / "never_created")

        response = client.delete("/api/admin/sewer/delete")

        assert response.status_code == 200
        db.commit.assert_called_once()
