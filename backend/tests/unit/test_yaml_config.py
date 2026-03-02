"""Tests for YAML configuration loading (load_config, get_database_url_from_config)."""

import yaml


class TestLoadConfig:
    def test_load_from_file(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "database": {"host": "testhost", "port": 5433},
                    "dem": {"resolution": "1m"},
                }
            )
        )
        config = load_config(str(config_file))
        assert config["database"]["host"] == "testhost"
        assert config["database"]["port"] == 5433

    def test_missing_file_returns_defaults(self):
        from core.config import load_config

        config = load_config("/nonexistent/path.yaml")
        assert "database" in config
        assert "dem" in config

    def test_partial_config_merges_with_defaults(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"dem": {"resolution": "1m"}}))
        config = load_config(str(config_file))
        assert config["dem"]["resolution"] == "1m"
        assert "host" in config["database"]

    def test_get_database_url_from_config(self, tmp_path):
        from core.config import get_database_url_from_config, load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "database": {
                        "host": "myhost",
                        "port": 5433,
                        "name": "mydb",
                        "user": "myuser",
                        "password": "mypass",
                    }
                }
            )
        )
        config = load_config(str(config_file))
        url = get_database_url_from_config(config)
        assert "myhost" in url
        assert "5433" in url
        assert "mydb" in url

    def test_defaults_include_all_sections(self):
        from core.config import load_config

        config = load_config("/nonexistent/path.yaml")
        assert "database" in config
        assert "dem" in config
        assert "paths" in config
        assert "steps" in config

    def test_steps_all_true_by_default(self):
        from core.config import load_config

        config = load_config("/nonexistent/path.yaml")
        for key, value in config["steps"].items():
            assert value is True, f"steps.{key} should default to True"

    def test_override_single_step(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"steps": {"tiles": False}}))
        config = load_config(str(config_file))
        assert config["steps"]["tiles"] is False
        assert config["steps"]["download_nmt"] is True

    def test_empty_yaml_file_returns_defaults(self, tmp_path):
        from core.config import load_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = load_config(str(config_file))
        assert config["database"]["host"] == "localhost"
        assert config["dem"]["resolution"] == "5m"


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

    def test_warns_on_default_password(self, caplog, monkeypatch):
        """Startup logs WARNING when using default postgres_password."""
        import logging
        from core.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        with caplog.at_level(logging.WARNING):
            settings = Settings()
            settings.warn_if_default_credentials()

        assert "hydro_password" in caplog.text or "default" in caplog.text.lower()
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
