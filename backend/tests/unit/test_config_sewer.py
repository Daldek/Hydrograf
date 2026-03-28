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


class TestSewerFieldMappingDefaults:
    def test_field_mapping_exists(self):
        from core.config import _DEFAULT_CONFIG
        assert "field_mapping" in _DEFAULT_CONFIG["sewer"]

    def test_field_mapping_has_node_id(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["node_id"] == "id"

    def test_field_mapping_has_node_role(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["node_role"] == "role"

    def test_field_mapping_has_downstream_id(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["downstream_id"] == "downstream_id"

    def test_field_mapping_has_edge_from_to(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["edge_from"] == "from_node"
        assert fm["edge_to"] == "to_node"

    def test_field_mapping_core_attrs_null(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        assert fm["invert_elev"] is None
        assert fm["depth"] is None
        assert fm["diameter"] is None

    def test_field_mapping_extended_attrs_null(self):
        from core.config import _DEFAULT_CONFIG
        fm = _DEFAULT_CONFIG["sewer"]["field_mapping"]
        for key in ("rim_elevation", "max_depth", "ponded_area",
                     "outfall_type", "manning", "material",
                     "cross_section", "width", "height"):
            assert fm[key] is None, f"{key} should be None"


class TestSewerRoleMappingDefaults:
    def test_role_mapping_exists(self):
        from core.config import _DEFAULT_CONFIG
        assert "role_mapping" in _DEFAULT_CONFIG["sewer"]

    def test_role_mapping_four_roles(self):
        from core.config import _DEFAULT_CONFIG
        rm = _DEFAULT_CONFIG["sewer"]["role_mapping"]
        assert rm == {
            "inlet": "inlet",
            "outlet": "outlet",
            "junction": "junction",
            "storage": "storage",
        }


class TestSewerSourceFormat:
    def test_source_format_default_auto(self):
        from core.config import _DEFAULT_CONFIG
        assert _DEFAULT_CONFIG["sewer"]["source"]["format"] == "auto"


class TestSewerBackwardCompat:
    def test_attribute_mapping_still_present(self):
        """attribute_mapping kept for backward compat with old config.yaml files."""
        from core.config import _DEFAULT_CONFIG
        assert "attribute_mapping" in _DEFAULT_CONFIG["sewer"]
