"""Contract: the examples of README.md agree with the code (DOC-2.6).

The REST examples name a route of the application and send a body that its request
model accepts, the table of capabilities names existing routes, and the commands of
the shell blocks start programs and options that exist.
"""

import importlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from api.main import app
from models import schemas

README = Path(__file__).resolve().parents[3] / "README.md"
BACKEND = Path(__file__).resolve().parents[2]
URL_PREFIX = "http://localhost:8080"
# Commands the test does not run and does not look into: setup and Docker.
NOT_CHECKED = {"git", "cd", "cp", "docker"}
# Programs that `uv run` starts in the README.
UV_RUN_PROGRAMS = {"alembic", "uvicorn", "python"}


def _commands() -> list[list[str]]:
    """Return the commands of the README's bash blocks, continuation lines joined."""
    text = README.read_text(encoding="utf-8")
    commands: list[list[str]] = []
    for block in re.findall(r"```bash\n(.*?)```", text, flags=re.S):
        for line in re.sub(r"\\\n", " ", block).splitlines():
            words = shlex.split(line, comments=True)
            if words:
                commands.append(words)
    return commands


def test_readme_commands_start_known_programs():
    unknown = []
    for words in _commands():
        if words[0] in NOT_CHECKED or words[0] == "curl":
            continue
        if words[:2] == ["uv", "sync"]:
            continue
        if words[:2] == ["uv", "run"] and words[2] in UV_RUN_PROGRAMS:
            continue
        unknown.append(" ".join(words))

    assert not unknown, f"README commands this test does not know: {unknown}"


def test_readme_curl_examples_match_the_routes():
    paths = app.openapi()["paths"]
    curls = [words for words in _commands() if words[0] == "curl"]
    assert curls, "README has no curl example"

    for words in curls:
        method = words[words.index("-X") + 1].lower()
        url = next(word for word in words if word.startswith("http"))
        assert url.startswith(URL_PREFIX), url
        path = url[len(URL_PREFIX) :]
        assert method in paths.get(path, {}), f"README names {method} {path}"
        schema = paths[path][method]["requestBody"]["content"]["application/json"]
        model = getattr(schemas, schema["schema"]["$ref"].rsplit("/", 1)[1])
        model.model_validate(json.loads(words[words.index("-d") + 1]))


def test_readme_capabilities_name_existing_routes():
    paths = app.openapi()["paths"]
    text = README.read_text(encoding="utf-8")
    # `METHOD /route` in the table, under the prefix /api; routes with a {placeholder}
    # or a * are not matched.
    listed = re.findall(r"`(GET|POST|PUT|DELETE) (/[^`{*]*)`", text)
    assert listed, "README lists no route"

    missing = [
        f"{method} {path}"
        for method, path in listed
        if method.lower() not in paths.get(f"/api{path}", {})
    ]

    assert not missing, f"routes of the README that the API lacks: {missing}"


def test_readme_bootstrap_options_exist():
    commands = [
        words
        for words in _commands()
        if words[:5] == ["uv", "run", "python", "-m", "scripts.bootstrap"]
    ]
    assert commands, "README has no bootstrap example"
    help_text = subprocess.run(
        [sys.executable, "-m", "scripts.bootstrap", "--help"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    for words in commands:
        for option in (word for word in words if word.startswith("--")):
            assert option in help_text, f"bootstrap has no option {option}"


def test_readme_uvicorn_target_exists():
    targets = [
        words[3] for words in _commands() if words[:3] == ["uv", "run", "uvicorn"]
    ]
    assert targets, "README has no uvicorn example"

    for target in targets:
        module, attribute = target.split(":")
        assert hasattr(importlib.import_module(module), attribute), target
