"""Contract: the error module is generated from the vendored registry (ERR-3)."""

import json

from scripts.generate_errors import MODULE, REGISTRY, render


def test_error_module_equals_the_output_of_the_generator():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    assert MODULE.read_text(encoding="utf-8") == render(registry), (
        "core/_errors.py is stale: run `uv run python -m scripts.generate_errors`"
    )
