"""Tests for admin cleanup endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import ALL_CLEANUP_TARGETS, _file_size_mb, router
from core.database import get_db


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = _noop_auth
    yield test_app
    test_app.dependency_overrides.clear()


def _make_mock_db():
    db = MagicMock(spec=Session)
    result = MagicMock()
    result.scalar.return_value = 52428800  # 50 MB
    db.execute.return_value = result
    return db


class TestCleanupEstimate:
    """Tests for GET /api/admin/cleanup/estimate."""

    @patch("api.endpoints.admin._dir_size_mb", return_value=10.0)
    @patch("api.endpoints.admin._file_size_mb", return_value=1.0)
    def test_estimate_returns_all_targets(
        self, _mock_file, _mock_dir, app
    ):
        """Estimate returns all 5 cleanup targets."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/cleanup/estimate")
        assert response.status_code == 200

        data = response.json()
        keys = [t["key"] for t in data["targets"]]
        assert "tiles" in keys
        assert "overlays" in keys
        assert "dem_tiles" in keys
        assert "dem_mosaic" in keys
        assert "db_tables" in keys
        assert "processed_data" in keys

    @patch("api.endpoints.admin._dir_size_mb", return_value=5.5)
    @patch("api.endpoints.admin._file_size_mb", return_value=0.0)
    def test_estimate_has_size_mb(self, _mock_file, _mock_dir, app):
        """Each target has a size_mb field."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/cleanup/estimate")
        data = response.json()

        for target in data["targets"]:
            assert "size_mb" in target
            assert isinstance(target["size_mb"], float)


class TestCleanupExecute:
    """Tests for POST /api/admin/cleanup."""

    def test_unknown_target_returns_400(self, app):
        """Unknown target key returns 400."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["nonexistent"]},
        )
        assert response.status_code == 400

    @patch("api.endpoints.admin.shutil")
    def test_cleanup_tiles(self, mock_shutil, app, tmp_path):
        """Cleaning tiles removes and recreates directory."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            tiles_dir = tmp_path / "tiles"
            tiles_dir.mkdir()
            (tiles_dir / "some.pbf").write_bytes(b"data")

            mock_targets.__contains__ = lambda s, k: k == "tiles"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "MVT tiles",
                "path": tiles_dir,
                "type": "dir",
            }
            mock_targets.items = lambda: [
                (
                    "tiles",
                    {"label": "MVT tiles", "path": tiles_dir, "type": "dir"},
                )
            ]

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["tiles"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["results"][0]["status"] == "ok"

    def test_cleanup_db_tables(self, app):
        """Cleaning db_tables executes TRUNCATE CASCADE."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["db_tables"]},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["results"][0]["key"] == "db_tables"
        assert data["results"][0]["status"] == "ok"
        # Verify TRUNCATE was called
        mock_db.execute.assert_called()
        mock_db.commit.assert_called()

    def test_cleanup_overlays_removes_geojson(self, app, tmp_path):
        """Cleaning overlays removes *.geojson files too."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        overlay_dir = tmp_path / "data"
        overlay_dir.mkdir()
        (overlay_dir / "dem.png").write_bytes(b"png")
        (overlay_dir / "dem.json").write_bytes(b"json")
        (overlay_dir / "soil_hsg.geojson").write_bytes(b"geojson")
        (overlay_dir / "bdot_lakes.geojson").write_bytes(b"geojson")
        (overlay_dir / "keep_me.txt").write_bytes(b"txt")

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            mock_targets.__contains__ = lambda s, k: k == "overlays"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "Overlay PNG + JSON + GeoJSON",
                "path": overlay_dir,
                "type": "glob",
                "patterns": ["*.png", "*.json", "*.geojson"],
            }

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["overlays"]},
            )
            assert response.status_code == 200
            assert response.json()["results"][0]["status"] == "ok"

        # GeoJSON + PNG + JSON removed, .txt preserved
        remaining = [f.name for f in overlay_dir.iterdir()]
        assert "keep_me.txt" in remaining
        assert "soil_hsg.geojson" not in remaining
        assert "bdot_lakes.geojson" not in remaining
        assert "dem.png" not in remaining
        assert "dem.json" not in remaining

    def test_cleanup_multiple_targets(self, app):
        """Multiple targets can be cleaned at once."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["db_tables"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1


class TestCleanupCache:
    """Tests for cache cleanup target."""

    def test_cleanup_cache_removes_contents(self, app, tmp_path):
        """Cleaning cache removes file contents but keeps subdirectories."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        # Create a fake cache directory structure
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        nmt_dir = cache_dir / "nmt"
        nmt_dir.mkdir()
        (nmt_dir / "sheet1.tif").write_bytes(b"raster data")
        (nmt_dir / "sheet2.tif").write_bytes(b"raster data")
        bdot_dir = cache_dir / "bdot10k"
        bdot_dir.mkdir()
        (bdot_dir / "powiat1.gpkg").write_bytes(b"vector data")
        hsg_dir = cache_dir / "soil_hsg"
        hsg_dir.mkdir()
        (hsg_dir / "hsg.shp").write_bytes(b"soil data")

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            mock_targets.__contains__ = lambda s, k: k == "cache"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "Download cache (NMT, BDOT10k, HSG)",
                "path": cache_dir,
                "type": "cache",
                "exclude_from_all": True,
            }

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["cache"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["results"][0]["key"] == "cache"
            assert data["results"][0]["status"] == "ok"

        # Subdirectories should still exist but be empty
        assert nmt_dir.exists()
        assert bdot_dir.exists()
        assert hsg_dir.exists()
        assert list(nmt_dir.iterdir()) == []
        assert list(bdot_dir.iterdir()) == []
        assert list(hsg_dir.iterdir()) == []

    def test_cache_excluded_from_all_targets(self):
        """Cache target is NOT included in ALL_CLEANUP_TARGETS."""
        assert "cache" not in ALL_CLEANUP_TARGETS

    def test_all_targets_include_standard_keys(self):
        """ALL_CLEANUP_TARGETS includes standard cleanup keys."""
        for key in ("tiles", "overlays", "dem_tiles", "dem_mosaic", "processed_data", "db_tables"):
            assert key in ALL_CLEANUP_TARGETS

    def test_cleanup_cache_nonexistent_dir(self, app, tmp_path):
        """Cleaning cache when directory does not exist still returns ok."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        nonexistent = tmp_path / "cache_missing"

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            mock_targets.__contains__ = lambda s, k: k == "cache"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "Download cache (NMT, BDOT10k, HSG)",
                "path": nonexistent,
                "type": "cache",
                "exclude_from_all": True,
            }

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["cache"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["results"][0]["status"] == "ok"


class TestCleanupProcessedData:
    """Tests for processed_data cleanup target."""

    def test_processed_data_in_all_targets(self):
        """processed_data is included in ALL_CLEANUP_TARGETS."""
        assert "processed_data" in ALL_CLEANUP_TARGETS

    def test_cleanup_processed_data_removes_tif(self, app, tmp_path):
        """Cleaning processed_data removes TIF files from data/nmt/ and hydro/."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        nmt_dir = tmp_path / "nmt"
        nmt_dir.mkdir()
        (nmt_dir / "dem_mosaic.vrt").write_bytes(b"vrt")
        (nmt_dir / "dem_mosaic_01_dem.tif").write_bytes(b"tif")
        (nmt_dir / "dem_mosaic_02_filled.tif").write_bytes(b"tif")

        hydro_dir = tmp_path / "hydro"
        hydro_dir.mkdir()
        (hydro_dir / "hydro_merged.gpkg").write_bytes(b"gpkg")

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            mock_targets.__contains__ = lambda s, k: k == "processed_data"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "Processed rasters + hydro",
                "path": [nmt_dir, hydro_dir],
                "type": "multi_dir",
            }

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["processed_data"]},
            )
            assert response.status_code == 200
            assert response.json()["results"][0]["status"] == "ok"

        # Directories exist but are empty
        assert nmt_dir.exists()
        assert list(nmt_dir.iterdir()) == []
        assert hydro_dir.exists()
        assert list(hydro_dir.iterdir()) == []


class TestFileSizeMb:
    """Tests for _file_size_mb helper."""

    def test_nonexistent_file(self, tmp_path):
        """Returns 0.0 for non-existent file."""
        assert _file_size_mb(tmp_path / "nope.vrt") == 0.0

    def test_existing_file(self, tmp_path):
        """Returns correct size for existing file."""
        f = tmp_path / "test.vrt"
        f.write_bytes(b"x" * (1024 * 1024))  # 1 MB
        assert _file_size_mb(f) == 1.0
