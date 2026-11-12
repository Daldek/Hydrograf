# Copies of the Nogat standard

Verbatim copies (ERR-3, AGI-4.1, DEV-15.6) of the files below, from commit `7786271` of the
[Nogat](https://github.com/Daldek/Nogat) repository: the standard that Nogat numbers 1.0 since
its `55a191a` (the draft called 2.1 before; no tag of it exists yet, replace the copies by the
tag when it does). Nogat's `uv run scripts/ecosystem.py drift` reports each copy as current,
behind or modified:

- `error_registry.json` (Nogat `standards/error_registry.json`): error codes, exit codes
  and HTTP statuses. `backend/core/_errors.py` is generated from it with
  `cd backend && uv run python -m scripts.generate_errors`.
- `result-1.schema.json`, `error-1.schema.json`, `commands-1.schema.json` (Nogat
  `schemas/agent/`): the schemas of the result envelope, the error document and the command
  catalog. Hydrograf has no command catalog, no result envelope and no command line, so it
  reports REST errors as `application/problem+json` and uses only the registry (see the
  deviations AGI-4.1 and AGI-4.2 in `CLAUDE.md`).

And, outside the standard, the envelope of the hand-offs, unchanged in Nogat since its commit
`8848c26` (item 6 of Nogat's `docs/plans/2026-11-01-nogat-gui-platform.md`, with the optional
`node_provenance` of step 1 of its `docs/plans/2026-11-10-node-provenance-in-handoff.md`: the
origin of each node of a network; SHA-256
`84c6856d1148acdc08bf79600c8cdab03674e81fe1f30eb7abeb66629b5742ed`. The pinned Hydrolog
`930915d` reads the copy of `8727f6e`, `node_provenance` as an unknown field; its step 3,
`cead00a` on Hydrolog's `develop` after the pin, takes this copy):

- `handoff-1.schema.json` (Nogat `schemas/exchange/handoff-1.schema.json`): the envelope
  `nogat-handoff/1` of data handed between the GUIs of the ecosystem. The API writes the
  hand-off of a watershed (ADR-068) and of a network (`POST /api/delineate-network`,
  ADR-080, with `node_provenance`) to Hydrolog with the payload `hydrolog-network/1`
  (`backend/core/handoff.py`); `backend/tests/unit/test_handoff.py` and
  `backend/tests/unit/test_network_endpoint.py` validate them against this copy.

Do not edit these files; copy them again when Nogat changes them. The copies of Nogat's GUI
kit, marks and tokens are in `frontend/` (`frontend/nogat/`, `frontend/css/tokens.css`).
