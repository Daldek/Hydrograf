# Contributing to Hydrograf

Thanks for your interest in Hydrograf! Bug reports, fixes, features, and documentation are
welcome.

## Getting started

```bash
# Install the locked development environment (uv: https://docs.astral.sh/uv/)
cd backend && uv sync --locked && cd ..

# Run the gate before opening a pull request: ruff, mypy, tests with coverage and the
# commit check (contributors keep their own identity, so skip the author check)
GATE_CHECK_AUTHOR=0 scripts/gate.sh
```

The gate runs the tests that need no database. The tests marked `db` need PostGIS: start
the database (`docker compose up -d db`), run `uv run alembic upgrade head` and
`uv run pytest tests -m "db and not benchmark"` in `backend/`; CI runs them too.

[`CLAUDE.md`](CLAUDE.md) lists the rules of the project for people and agents who develop
it, and [`docs/PROGRESS.md`](docs/PROGRESS.md) the current state and the next steps.

## Contribution guidelines

- **Plans.** A change of a public interface or across several modules starts with a plan in
  `docs/plans/YYYY-MM-DD-slug.md` (goal, options, decision, steps) that the maintainer
  approves; a decision with alternatives is recorded as an ADR in
  [`docs/DECISIONS.md`](docs/DECISIONS.md).
- **Producers.** Hydrograf uses Hydrolog, Kartograf and IMGWTools through their public
  APIs. If a producer lacks a function, open an issue labelled `request` in its repository
  instead of working around it here.
- **Language.** Code, identifiers, docstrings, comments, logs, tests, documentation,
  commit messages and contributor-facing files are in English. The user interface is
  Polish. Some documents under `docs/` are still Polish and are being translated; new and
  edited documents are English.
- **Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/) in English,
  for example `docs(readme): describe the admin panel`. Messages carry no AI attribution.
- **Branches.** Open pull requests against `develop`; address one concern per pull
  request.
- **Data.** Do not commit data (`data/` and `cache/` are ignored) and do not put downloaded
  data in `/tmp`; use an explicit directory elsewhere.
- **Python environment.** Use the `backend/.venv` that uv creates, through `uv run`; the
  gate runs `ruff format --check`, `ruff check`, `mypy` and `pytest` with a coverage floor
  (`fail_under` in `backend/pyproject.toml`).

## Contributor License Agreement (CLA)

Before your first contribution can be merged, we ask you to sign our **Contributor License
Agreement**. In plain terms:

- **What it is.** A short agreement in which you confirm that you wrote (or have the right
  to submit) your contribution, and that you grant the necessary rights to use and
  redistribute it. The full text is `docs/CLA.md`, which the maintainer adds to the
  repository before the first external pull request is merged.
- **Why it is required.** It keeps the project's licensing on solid legal footing and
  preserves the option to relicense in the future if that ever becomes necessary.
- **Your contribution stays MIT.** Signing the CLA does **not** change the licence. The
  project is and remains distributed under the [MIT License](LICENSE), and so is your
  contribution.
- **Signing is one comment, and the process is manual.** There is no bot and no form. When
  your pull request is ready, add a comment on it with exactly this text:

  > I have read the CLA document and hereby sign it.

  When the maintainer merges your pull request, they record your signature (your GitHub
  handle, the date and the pull request number) in [`CONTRIBUTORS.md`](CONTRIBUTORS.md).
  You only have to sign once; it also covers your future contributions.

Please also tick the CLA box in the pull request template.

## Reporting issues

Found a bug or have a feature idea? Open an issue at
<https://github.com/Daldek/Hydrograf/issues> with as much detail as you can (steps to
reproduce, expected and actual behaviour, the versions of Hydrograf, Hydrolog, Kartograf
and IMGWTools).

Security problems are not reported as public issues: see [`SECURITY.md`](SECURITY.md).
