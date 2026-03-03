"""Tests for discover_asc_files() — bbox-based ASC file discovery."""

from pathlib import Path
from unittest.mock import patch

from utils.raster_utils import discover_asc_files


def _write_asc(
    path: Path, xll: float, yll: float,
    ncols: int, nrows: int, cellsize: float,
) -> None:
    """Write a minimal ASC header (no data rows needed for discovery)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"ncols {ncols}\n"
        f"nrows {nrows}\n"
        f"xllcorner {xll}\n"
        f"yllcorner {yll}\n"
        f"cellsize {cellsize}\n"
        f"NODATA_value -9999\n"
    )


# Bbox for a small area in EPSG:2180 (PUWG 1992)
BBOX = (400_000.0, 200_000.0, 410_000.0, 210_000.0)


class TestDiscoverAscFiles:
    """Tests for discover_asc_files()."""

    def test_filters_by_bbox(self, tmp_path: Path) -> None:
        """Files inside bbox are kept, files outside are excluded."""
        inside = tmp_path / "inside.asc"
        outside = tmp_path / "outside.asc"

        # Inside: origin at (401000, 201000), 1000x1000 cells at 5m → fits in bbox
        _write_asc(inside, 401_000, 201_000, 1000, 1000, 5.0)
        # Outside: origin at (500_000, 500_000) — far from bbox
        _write_asc(outside, 500_000, 500_000, 1000, 1000, 5.0)

        result = discover_asc_files(tmp_path, BBOX)

        assert inside in result
        assert outside not in result

    def test_excludes_reprojected_dir(self, tmp_path: Path) -> None:
        """Files in the reprojected/ subdirectory are excluded."""
        normal = tmp_path / "tile.asc"
        reprojected = tmp_path / "reprojected" / "tile.asc"

        _write_asc(normal, 401_000, 201_000, 1000, 1000, 5.0)
        _write_asc(reprojected, 401_000, 201_000, 1000, 1000, 5.0)

        result = discover_asc_files(tmp_path, BBOX)

        assert normal in result
        assert reprojected not in result

    def test_handles_puwg2000_coords(self, tmp_path: Path) -> None:
        """PUWG 2000 files (xll > 1M) have bounds transformed before filtering."""
        tile = tmp_path / "puwg2000.asc"
        # Zone 7 PUWG 2000 (EPSG:2178): easting starts with 7_xxx_xxx
        # These coords should transform to roughly the bbox area in EPSG:2180
        _write_asc(tile, 7_401_000, 5_501_000, 1000, 1000, 5.0)

        # Use a bbox that matches the transformed coordinates
        # We mock the transformer to control the output
        with patch("utils.raster_utils.Transformer") as mock_tf_cls:
            mock_tf = mock_tf_cls.from_crs.return_value
            # Simulate transform: return values inside our BBOX
            mock_tf.transform.side_effect = [
                (405_000.0, 205_000.0),  # min corner
                (410_000.0, 210_000.0),  # max corner
            ]

            result = discover_asc_files(tmp_path, BBOX)

        assert tile in result
        mock_tf_cls.from_crs.assert_called_once_with(
            "EPSG:2178", "EPSG:2180", always_xy=True,
        )

    def test_empty_dir(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        result = discover_asc_files(tmp_path, BBOX)
        assert result == []

    def test_partial_overlap(self, tmp_path: Path) -> None:
        """File partially overlapping bbox is included."""
        tile = tmp_path / "partial.asc"
        # Tile starts at (399_000, 199_000) with 1000 cols × 1000 rows at 5m
        # → extent (399_000, 199_000) to (404_000, 204_000)
        # → overlaps BBOX (400_000, 200_000, 410_000, 210_000) partially
        _write_asc(tile, 399_000, 199_000, 1000, 1000, 5.0)

        result = discover_asc_files(tmp_path, BBOX)
        assert tile in result

    def test_no_overlap(self, tmp_path: Path) -> None:
        """File entirely outside bbox is excluded."""
        tile = tmp_path / "far_away.asc"
        # Tile at (100_000, 100_000) — nowhere near BBOX
        _write_asc(tile, 100_000, 100_000, 100, 100, 5.0)

        result = discover_asc_files(tmp_path, BBOX)
        assert result == []

    def test_nested_subdirectory(self, tmp_path: Path) -> None:
        """Files in nested subdirectories (not reprojected/) are found."""
        nested = tmp_path / "subdir" / "deep" / "tile.asc"
        _write_asc(nested, 405_000, 205_000, 100, 100, 5.0)

        result = discover_asc_files(tmp_path, BBOX)
        assert nested in result
