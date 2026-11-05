# Copies of the Nogat standard

Verbatim copies (ERR-3, AGI-4.1) of the files below, from the standard 2.1 of the
[Nogat](https://github.com/Daldek/Nogat) repository at commit `cc656e7` (the tag
`std-2.1` does not exist yet; replace the copies by the tag when it does):

- `error_registry.json` (Nogat `standards/error_registry.json`): error codes, exit codes
  and HTTP statuses. `backend/core/_errors.py` is generated from it with
  `cd backend && uv run python -m scripts.generate_errors`.
- `result-1.schema.json`, `error-1.schema.json`, `commands-1.schema.json` (Nogat
  `schemas/agent/`): the schemas of the result envelope, the error document and the command
  catalog. Hydrograf has no command catalog, no result envelope and no command line, so it
  reports REST errors as `application/problem+json` and uses only the registry (see the
  deviations AGI-4.1 and AGI-4.2 in `CLAUDE.md`).

And, outside the standard, from commit `8727f6e` of Nogat (item 6 of Nogat's
`docs/plans/2026-11-01-nogat-gui-platform.md`; its example carries the flow path fields of
the official tc inputs; SHA-256
`15c82f6a9e0107ddf1c6846f8053d7da9991c1e91679f93d5da4a2fadf6fd6e4`, the copy Hydrolog
reads):

- `handoff-1.schema.json` (Nogat `schemas/exchange/handoff-1.schema.json`): the envelope
  `nogat-handoff/1` of data handed between the GUIs of the ecosystem. The API writes the
  hand-off of a watershed to Hydrolog with the payload `hydrolog-network/1`
  (`backend/core/handoff.py`, ADR-068); `backend/tests/unit/test_handoff.py` validates
  it against this copy.

Do not edit these files; copy them again when the standard changes.
