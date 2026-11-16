"""Contract: `.env.example` lists every variable the application reads (DEV-18.3)."""

import re
from pathlib import Path

from core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"

# Read by `Settings.database_url` straight from the environment, not as a field.
EXTRA_VARIABLES = {"DATABASE_URL"}


def _listed_variables() -> set[str]:
    """Return the names on `NAME=` and `# NAME=` lines of `.env.example`."""
    listed: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"#?\s*([A-Z][A-Z0-9_]*)=", line)
        if match:
            listed.add(match.group(1))
    return listed


def test_env_example_lists_every_setting():
    read = {name.upper() for name in Settings.model_fields} | EXTRA_VARIABLES

    missing = read - _listed_variables()

    assert not missing, f"missing from .env.example: {sorted(missing)}"
