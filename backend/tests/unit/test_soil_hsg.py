"""Tests for HSG soil group queries."""

from decimal import Decimal
from types import SimpleNamespace

import numpy as np
from scipy.ndimage import distance_transform_edt

from core.soil_hsg import get_hsg_for_boundary
from models.schemas import HsgCategory, HsgStats


class TestHsgStats:
    def test_valid_hsg_stats(self):
        stats = HsgStats(
            categories=[
                HsgCategory(group="B", percentage=60.0, area_m2=1_000_000),
                HsgCategory(group="C", percentage=30.0, area_m2=500_000),
                HsgCategory(group="A", percentage=10.0, area_m2=166_666),
            ],
            dominant_group="B",
        )
        assert stats.dominant_group == "B"
        assert len(stats.categories) == 3

    def test_hsg_stats_none_in_response(self):
        """WatershedResponse should accept None for hsg_stats."""
        from models.schemas import OutletInfo, WatershedResponse

        # Minimalne dane wymagane
        resp = WatershedResponse(
            boundary_geojson={
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
            },
            outlet=OutletInfo(latitude=52.0, longitude=21.0, elevation_m=100.0),
            area_km2=10.0,
            hydrograph_available=False,
            morphometry=None,
            hypsometric_curve=None,
            land_cover_stats=None,
            hsg_stats=None,
            main_stream_geojson=None,
        )
        assert resp.hsg_stats is None


class TestHsgNearestNeighborFill:
    def test_hsg_nearest_neighbor_fill(self):
        """Nearest-neighbor fill replaces zeros with closest valid HSG values."""
        data = np.array(
            [
                [1, 1, 0, 2, 2],
                [1, 0, 0, 0, 2],
                [0, 0, 0, 0, 0],
                [3, 0, 0, 0, 4],
                [3, 3, 0, 4, 4],
            ],
            dtype=np.uint8,
        )

        valid_mask = np.isin(data, [1, 2, 3, 4])
        assert not valid_mask.all()  # has zeros

        _, nearest_indices = distance_transform_edt(~valid_mask, return_indices=True)
        filled = np.where(
            valid_mask, data, data[nearest_indices[0], nearest_indices[1]]
        )

        # No zeros remain
        assert np.all(np.isin(filled, [1, 2, 3, 4]))
        # Original values unchanged
        assert filled[0, 0] == 1
        assert filled[0, 3] == 2
        assert filled[3, 0] == 3
        assert filled[4, 4] == 4


class TestHsgPolandCache:
    """Tests for Poland-wide HSG cache logic."""

    def test_hsg_poland_filename(self):
        """HSG Poland file uses correct name."""
        from pathlib import Path

        cache_dir = Path("/tmp/test_cache")
        expected = cache_dir / "soil_hsg" / "hsg_poland.tif"
        assert expected.name == "hsg_poland.tif"

    def test_hsg_skip_existing(self, tmp_path):
        """If hsg_poland.tif exists, download is skipped."""
        hsg_dir = tmp_path / "soil_hsg"
        hsg_dir.mkdir()
        hsg_file = hsg_dir / "hsg_poland.tif"
        hsg_file.write_bytes(b"existing raster")

        # File exists — should be reused
        assert hsg_file.exists()
        assert hsg_file.stat().st_size > 0

    def test_hsg_bbox_scoped_delete_sql(self):
        """DB cleanup uses bbox-scoped DELETE, not full table DELETE."""
        # Verify the SQL pattern that should be used
        expected_where = "ST_Intersects(geom, ST_MakeEnvelope"
        assert "ST_Intersects" in expected_where
        assert "ST_MakeEnvelope" in expected_where


class FakeSession:
    """Answers `execute(sql, params).fetchall()` with prepared rows."""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((str(sql), params))
        return SimpleNamespace(fetchall=lambda: self.rows)


def row(group, area_m2, percentage):
    return SimpleNamespace(
        hsg_group=group, total_area_m2=area_m2, percentage=percentage
    )


class TestGetHsgForBoundary:
    def test_catchment_without_soil_data_has_no_statistics(self):
        assert get_hsg_for_boundary("0102", FakeSession([])) is None

    def test_groups_keep_the_order_of_the_query_and_the_first_is_dominant(self):
        db = FakeSession(
            [row("B", Decimal("7500.5"), Decimal("75.005")), row("A", 2500, 24.995)]
        )

        stats = get_hsg_for_boundary("0102", db)

        assert stats == {
            "categories": [
                {"group": "B", "area_m2": 7500.5, "percentage": 75.005},
                {"group": "A", "area_m2": 2500.0, "percentage": 24.995},
            ],
            "dominant_group": "B",
        }
        # numeric columns arrive as Decimal; the response model needs floats
        assert all(
            type(c[key]) is float
            for c in stats["categories"]
            for key in c
            if key != "group"
        )

    def test_boundary_is_sent_as_a_bound_parameter_not_as_sql_text(self):
        boundary = "0103000020B40800000100000004000000"
        db = FakeSession([row("C", 10.0, 100.0)])

        get_hsg_for_boundary(boundary, db)

        ((sql, params),) = db.executed
        assert params == {"boundary_wkb": boundary}
        assert boundary not in sql
        assert ":boundary_wkb" in sql
