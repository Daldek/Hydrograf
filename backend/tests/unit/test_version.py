"""The version of the API comes from pyproject.toml, the one source (REL-1.1)."""

import tomllib
from pathlib import Path

from packaging.version import Version

from api.main import app
from core.version import get_version

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_get_version_is_the_project_version():
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert get_version() == declared["version"]


def test_get_version_is_a_pep_440_version():
    assert str(Version(get_version())) == get_version()


def test_openapi_document_carries_the_project_version():
    assert app.openapi()["info"]["version"] == get_version()
