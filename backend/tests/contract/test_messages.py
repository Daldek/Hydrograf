"""Contract: errors raised in the code use the message catalogue correctly (DEV-2.3).

Every ``<Something>Error("<message id>", reason=..., key=value)`` call in ``api`` and
``core`` names a message of ``core.messages``, gives its ``reason`` and supplies every
``{field}`` of the English text and its hint; both languages of a message use the same
fields.
"""

import ast
import string
from collections.abc import Iterator
from pathlib import Path

from core.errors import HydrografError
from core.messages import MESSAGES

BACKEND = Path(__file__).resolve().parents[2]
ERROR_CLASSES = {cls.__name__ for cls in HydrografError.__subclasses__()} | {
    "HydrografError"
}


def _fields(template: str | None) -> set[str]:
    if template is None:
        return set()
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _raised_errors() -> Iterator[tuple[str, ast.Call]]:
    for folder in ("api", "core"):
        for path in sorted((BACKEND / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ERROR_CLASSES
                ):
                    yield f"{path.relative_to(BACKEND)}:{node.lineno}", node


def test_every_raised_error_names_a_message_and_supplies_its_fields():
    problems = []
    calls = list(_raised_errors())
    assert calls, "no error is raised in api or core"

    for where, call in calls:
        first = call.args[0] if call.args else None
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            problems.append(f"{where}: the message ID must be a string literal")
            continue
        entry = MESSAGES.get(first.value)
        if entry is None:
            problems.append(f"{where}: {first.value!r} is not in the catalogue")
            continue
        given = {kw.arg for kw in call.keywords}
        if None in given:  # **details: the keys are not known statically
            continue
        if "reason" not in given:
            problems.append(f"{where}: no reason")
        needed = _fields(entry.en) | _fields(entry.hint_en)
        if needed - given:
            problems.append(f"{where}: missing {sorted(needed - given)}")

    assert not problems, problems


def test_both_languages_of_a_message_use_the_same_fields():
    for message_id, entry in MESSAGES.items():
        assert _fields(entry.en) == _fields(entry.pl), message_id
        assert _fields(entry.hint_en) == _fields(entry.hint_pl), message_id
        assert (entry.hint_en is None) == (entry.hint_pl is None), message_id


def test_every_message_of_the_catalogue_is_used():
    used = {
        call.args[0].value
        for _, call in _raised_errors()
        if call.args and isinstance(call.args[0], ast.Constant)
    }
    # Messages that the handlers of api/errors.py use by ID, not through a class.
    handled = {
        "invalid_request",
        "route_not_found",
        "method_not_supported",
        "http_error",
        "internal_error",
    }

    assert set(MESSAGES) - used - handled == set()
