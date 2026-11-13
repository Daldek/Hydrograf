"""
The state_dir of the logs (core/config.py; Nogat DEV-18.1, DEV-18.2, DEV-12.6).

The first of HYDROGRAF_STATE_DIR, NOGAT_STATE_DIR, `[hydrograf] state_dir` and
`[nogat] state_dir` of the nogat.toml of NOGAT_CONFIG, and platformdirs' user state
directory of `nogat`.
"""

from pathlib import Path

import platformdirs
import pytest

from core.config import Settings, nogat_table, state_dir

BOTH_SECTIONS = (
    '[nogat]\nstate_dir = "/srv/nogat"\n[hydrograf]\nstate_dir = "/srv/hg"\n'
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Build the settings of the environment variables given, with a nogat.toml."""
    for name in ("HYDROGRAF_STATE_DIR", "NOGAT_STATE_DIR", "NOGAT_CONFIG"):
        monkeypatch.delenv(name, raising=False)

    def build(toml: str = "", **variables: str) -> Settings:
        path = tmp_path / "nogat.toml"
        path.write_text(toml, encoding="utf-8")
        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        return Settings(nogat_config=str(path) if toml else "")

    nogat_table.cache_clear()
    yield build
    nogat_table.cache_clear()


def test_the_tool_variable_comes_first(settings):
    resolved = settings(
        BOTH_SECTIONS, HYDROGRAF_STATE_DIR="/tool", NOGAT_STATE_DIR="/shared"
    )

    assert state_dir(resolved) == Path("/tool")


def test_the_shared_variable_comes_before_the_file(settings):
    assert state_dir(settings(BOTH_SECTIONS, NOGAT_STATE_DIR="/shared")) == Path(
        "/shared"
    )


def test_the_tool_section_of_the_file_comes_before_the_shared_one(settings):
    assert state_dir(settings(BOTH_SECTIONS)) == Path("/srv/hg")


def test_the_shared_section_of_the_file_comes_before_the_default(settings):
    assert state_dir(settings('[nogat]\nstate_dir = "~/state"\n')) == (
        Path.home() / "state"
    )


def test_without_any_the_default_is_the_user_state_directory(settings):
    assert state_dir(settings()) == platformdirs.user_state_path("nogat")
