"""Tests for sewer config defaults and loading."""

from core.config import _DEFAULT_CONFIG, load_config


class TestSewerConfigDefaults:
    def test_sewer_section_exists(self):
        assert "sewer" in _DEFAULT_CONFIG

    def test_sewer_disabled_by_default(self):
        assert _DEFAULT_CONFIG["sewer"]["enabled"] is False

    def test_sewer_default_burn_depth(self):
        assert _DEFAULT_CONFIG["sewer"]["inlet_burn_depth_m"] == 0.5

    def test_sewer_default_snap_tolerance(self):
        assert _DEFAULT_CONFIG["sewer"]["snap_tolerance_m"] == 2.0

    def test_sewer_source_defaults(self):
        source = _DEFAULT_CONFIG["sewer"]["source"]
        assert source["type"] == "file"
        assert source["path"] is None
        assert source["lines_layer"] is None
        assert source["points_layer"] is None
        assert source["assumed_crs"] is None

    def test_sewer_attribute_mapping_defaults(self):
        mapping = _DEFAULT_CONFIG["sewer"]["attribute_mapping"]
        assert mapping["diameter"] is None
        assert mapping["depth"] is None
        assert mapping["flow_direction"] is None


class TestSewerConfigMerge:
    def test_yaml_overrides_sewer_enabled(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("sewer:\n  enabled: true\n  inlet_burn_depth_m: 0.8\n")
        cfg = load_config(str(yaml_file))
        assert cfg["sewer"]["enabled"] is True
        assert cfg["sewer"]["inlet_burn_depth_m"] == 0.8
        # Non-overridden defaults preserved
        assert cfg["sewer"]["snap_tolerance_m"] == 2.0
