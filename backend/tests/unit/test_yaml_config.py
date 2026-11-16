"""Tests for YAML configuration loading (load_config, _deep_merge)."""

import yaml


class TestLoadConfig:
    def test_load_from_file(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "dem": {"stream_burning": "main"},
                    "paths": {"cache_dir": "/srv/cache"},
                }
            )
        )
        config = load_config(str(config_file))
        assert config["dem"]["stream_burning"] == "main"
        assert config["paths"]["cache_dir"] == "/srv/cache"

    def test_missing_file_returns_defaults(self):
        from core.config import load_config

        config = load_config("/nonexistent/path.yaml")
        assert config["dem"]["stream_burning"] == "all"
        assert config["sewer"]["enabled"] is False

    def test_partial_config_merges_with_defaults(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"dem": {"stream_burning": "main"}}))
        config = load_config(str(config_file))
        assert config["dem"]["stream_burning"] == "main"
        assert config["dem"]["fill_enclosed_nodata"] is False

    def test_empty_yaml_file_returns_defaults(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = load_config(str(config_file))
        assert config["dem"]["stream_burning"] == "all"
        assert config["paths"]["cache_dir"] == "cache"


class TestDeepMerge:
    def test_nested_override(self):
        from core.config import _deep_merge

        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"b": 99}}
        result = _deep_merge(base, override)
        assert result["a"]["b"] == 99
        assert result["a"]["c"] == 2

    def test_new_key_added(self):
        from core.config import _deep_merge

        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"] == 2

    def test_does_not_mutate_base(self):
        from core.config import _deep_merge

        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        _deep_merge(base, override)
        assert base["a"]["b"] == 1

    def test_override_replaces_non_dict_with_dict(self):
        from core.config import _deep_merge

        base = {"a": 1}
        override = {"a": {"nested": True}}
        result = _deep_merge(base, override)
        assert result["a"] == {"nested": True}

    def test_override_replaces_dict_with_non_dict(self):
        from core.config import _deep_merge

        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        result = _deep_merge(base, override)
        assert result["a"] == "flat"

    def test_deeply_nested_merge(self):
        from core.config import _deep_merge

        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"] == 99
        assert result["a"]["b"]["d"] == 2


class TestSettingsSecurityWarnings:
    """Tests for security warnings on default credentials (S5.3)."""

    def test_warns_on_empty_password(self, caplog, monkeypatch):
        """Startup logs WARNING when postgres_password is empty."""
        import logging

        from core.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        with caplog.at_level(logging.WARNING):
            settings = Settings()
            settings.warn_if_default_credentials()

        assert "POSTGRES_PASSWORD" in caplog.text and "empty" in caplog.text.lower()
        get_settings.cache_clear()

    def test_no_warning_with_custom_password(self, caplog, monkeypatch):
        """No warning when password is explicitly set."""
        import logging

        from core.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("POSTGRES_PASSWORD", "my-secure-password")

        with caplog.at_level(logging.WARNING):
            settings = Settings()
            settings.warn_if_default_credentials()

        assert "hydro_password" not in caplog.text
        get_settings.cache_clear()
