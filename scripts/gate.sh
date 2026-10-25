#!/usr/bin/env bash
# Quality gate (DEV-7.6), from Nogat standards/ci/gate.sh, adapted to the layout of
# an `app`: the Python project is backend/ (own pyproject.toml, uv.lock and .venv) and
# the commit step runs from the repository root.
#
# Usage: scripts/gate.sh [extra pytest arguments]
# Runs, in order: ruff format --check, ruff check, mypy, one pytest call over
# backend/tests/ with coverage (contract tests included), and the commit step
# (scripts/check-commits.sh: identity preflight, then message checks). The
# first failure stops it.
set -euo pipefail

# --- project settings --------------------------------------------------------
# Marker expression of the gate (DEV-10.1). Without a local database `db` stays
# out; `benchmark` marks the timing tests of tests/performance, which need the
# database as well. The `db` job of CI runs the database tests.
OFFLINE="not live and not db and not benchmark"
# The application is several top-level packages, not one: the coverage source and
# the mypy targets (`files`) are set in backend/pyproject.toml, so the calls below
# name neither a package nor paths.
# ------------------------------------------------------------------------------

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step() { printf '\n== %s\n' "$1"; }
fail() { printf 'gate: %s\n' "$1" >&2; exit 1; }

command -v uv >/dev/null || fail "uv not found (DEV-6.2): https://docs.astral.sh/uv/"

started=$SECONDS

cd "$ROOT/backend"

# The environment belongs to this checkout: in a git worktree uv creates the
# worktree's own .venv, so the gate always tests the code it runs from.
step "uv sync --locked"
uv sync --locked --all-extras

run() { uv run --no-sync "$@"; }

step "ruff format --check"
run ruff format --check .

step "ruff check"
run ruff check .

step "mypy"
run mypy

step "pytest (tests/, coverage)"
# ${@+"$@"} keeps an empty argument list safe under set -u on macOS bash 3.2.
run pytest tests -m "$OFFLINE" \
  --cov --cov-report=term-missing:skip-covered -q ${@+"$@"}

cd "$ROOT"

step "commit step"
bash "$ROOT/scripts/check-commits.sh"

printf '\nGATE OK (%d s)\n' "$((SECONDS - started))"
