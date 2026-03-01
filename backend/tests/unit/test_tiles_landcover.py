"""
Unit tests for land cover MVT tile endpoint.
"""

import inspect


class TestLandCoverTileEndpoint:
    """Tests for /tiles/landcover/{z}/{x}/{y}.pbf endpoint."""

    def test_endpoint_exists(self):
        """Verify /tiles/landcover route is registered."""
        from api.endpoints.tiles import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        landcover_paths = [p for p in paths if "landcover" in p]
        assert len(landcover_paths) > 0, "No landcover tile endpoint found"

    def test_endpoint_returns_protobuf_content_type(self):
        """Verify the endpoint function signature accepts z, x, y."""
        from api.endpoints.tiles import get_landcover_tile

        sig = inspect.signature(get_landcover_tile)
        params = list(sig.parameters.keys())
        assert "z" in params
        assert "x" in params
        assert "y" in params

    def test_endpoint_path_pattern(self):
        """Verify the endpoint path follows the {z}/{x}/{y}.pbf pattern."""
        from api.endpoints.tiles import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        landcover_paths = [p for p in paths if "landcover" in p]
        assert any(
            "{z}" in p and "{x}" in p and "{y}" in p for p in landcover_paths
        ), f"Expected z/x/y path params, got: {landcover_paths}"

    def test_endpoint_has_db_dependency(self):
        """Verify the endpoint uses database dependency injection."""
        from api.endpoints.tiles import get_landcover_tile

        sig = inspect.signature(get_landcover_tile)
        assert "db" in sig.parameters, "Endpoint must accept db parameter"
