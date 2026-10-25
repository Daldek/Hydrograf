"""Version of Hydrograf, read from the one place that declares it (REL-1.1)."""

import tomllib
from functools import cache
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@cache
def get_version() -> str:
    """Return the version of Hydrograf declared in ``backend/pyproject.toml``.

    The application is not installed as a package (``[tool.uv] package = false``),
    so ``importlib.metadata`` has no record of it; the file is part of the Docker
    image for this reason.

    Returns
    -------
    str
        The PEP 440 version, for example ``"0.5.0.dev0"`` between releases.

    Raises
    ------
    FileNotFoundError
        If ``pyproject.toml`` is not next to the ``core`` package.
    """
    with _PYPROJECT.open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])
