"""Tests for HSG soil group queries."""

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
