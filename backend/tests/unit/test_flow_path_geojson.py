"""Tests for the length_km label in _build_flow_path_geojson."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from core.watershed_service import _build_flow_path_geojson


def _mock_cg():
    cg = MagicMock()
    cg.get_max_flow_dist_m.side_effect = lambda i: {0: 8000.0, 1: 5000.0}[i]
    cg.get_outlet_flow_dist_m.return_value = 3000.0
    cg.get_segment_idx.side_effect = lambda i: i + 1
    cg.trace_main_channel.return_value = {"main_channel_nodes": []}
    return cg


def _mock_db():
    db = MagicMock()
    row = MagicMock()
    row.geojson = (
        '{"type": "LineString", "coordinates": [[15.0, 50.0], [15.1, 50.1]]}'
    )
    db.execute.return_value.fetchone.return_value = row
    return db


class TestFlowPathLabel:
    def test_label_uses_outlet_baseline(self):
        """length_km = (max_dist - outlet_flow_dist) / 1000."""
        feature = _build_flow_path_geojson(
            _mock_cg(), np.array([0, 1]), 1, 100000, _mock_db(),
            "longest_flow_path_geom", "longest_flow_path",
        )
        assert feature["properties"]["length_km"] == pytest.approx(5.0)

    def test_label_fallback_when_outlet_dist_nan(self):
        """NaN baseline -> max_flow_dist_m[outlet] (zanizanie, nie zawyzanie)."""
        cg = _mock_cg()
        cg.get_outlet_flow_dist_m.return_value = float("nan")
        feature = _build_flow_path_geojson(
            cg, np.array([0, 1]), 1, 100000, _mock_db(),
            "longest_flow_path_geom", "longest_flow_path",
        )
        # baseline = max_flow_dist_m[outlet_idx=1] = 5000 -> (8000-5000)/1000
        assert feature["properties"]["length_km"] == pytest.approx(3.0)
