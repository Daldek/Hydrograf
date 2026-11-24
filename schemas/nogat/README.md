# Copies of the Nogat standard

Verbatim copies (ERR-3, AGI-4.1, DEV-15.6) of the files below of the
[Nogat](https://github.com/Daldek/Nogat) repository, current with the Nogat standard 1.1 (tag
`std-1.1`): the files named without a commit of their own are copies of Nogat's `7786271`
(standard 1.0), which 1.1 did not change. Nogat's `uv run scripts/ecosystem.py drift` reports
each copy as current, behind or modified:

- `error_registry.json` (Nogat `standards/error_registry.json`), copied again from Nogat's
  `975136e` (standard 1.1, the computation standard CMP; of the registry only its
  `standard_version` changed, the codes are those of 1.0): error codes, exit codes
  and HTTP statuses. `backend/core/_errors.py` is generated from it with
  `cd backend && uv run python -m scripts.generate_errors`.
- `result-1.schema.json`, `error-1.schema.json`, `commands-1.schema.json` (Nogat
  `schemas/agent/`): the schemas of the result envelope, the error document and the command
  catalog. Hydrograf has no command catalog, no result envelope and no command line, so it
  reports REST errors as `application/problem+json` and uses only the registry (see the
  deviations AGI-4.1 and AGI-4.2 in `CLAUDE.md`).

And, outside the standard, the envelope of the hand-offs, copied from Nogat's `develop`
`2bbb507` (the merge of its `fix/handoff-example-beta`; unchanged at `263e83c`): item 6 of
Nogat's `docs/plans/2026-11-01-nogat-gui-platform.md`, with the optional `node_provenance` of
step 1 of its `docs/plans/2026-11-10-node-provenance-in-handoff.md`: the origin of each node
of a network, and the optional `attribution` and `terms_notice` of its
`docs/plans/2026-11-13-provider-attribution.md`: the lines the providers' terms require, DEV §20,
ECO-060, with the description and examples of ECO-065: `terms_notice` holds the links to the
terms only; its first example records the result of Hydrolog 0.9.0 (57.9 m³/s and
1 046 737.6 m³, the exact Beta storm and Kirpich's 0.0078). SHA-256
`10de3e18aafe37d413d19bd849730a2bee2b64603eb5d2c01c992f80c662c62f`. The pinned Hydrolog
0.9.1 (`a59753c`) reads the same copy (the same SHA-256), with `node_provenance`, `attribution` and
`terms_notice`:

- `handoff-1.schema.json` (Nogat `schemas/exchange/handoff-1.schema.json`): the envelope
  `nogat-handoff/1` of data handed between the GUIs of the ecosystem. The API writes the
  hand-off of a watershed (ADR-068, with `attribution` and `terms_notice` of a PMAXTP rainfall,
  ADR-083) and of a network (`POST /api/delineate-network`, ADR-080, with `node_provenance`) to
  Hydrolog with the payload `hydrolog-network/1` (`backend/core/handoff.py`);
  `backend/tests/unit/test_handoff.py` and `backend/tests/unit/test_network_endpoint.py`
  validate them against this copy.

And the logging of ECO-066 (Nogat DEV-12.4 to DEV-12.9), copied from Nogat's `develop`
`a41d971` (the merge of its `feat/unified-logging`, the files of `f370afe`):

- `record-1.schema.json` (Nogat `schemas/log/record-1.schema.json`), SHA-256
  `cac452bd338054916d7837820053b0a5ed8f5a076a33f95ed0448ded170984d0`: the record
  `nogat-log/1` of the API's access, application and lifecycle logs;
  `backend/tests/integration/test_access_log.py` validates an access record against it.
- `backend/core/nogat_logging.py` (Nogat `standards/reference/nogat_logging.py`), SHA-256
  `66964a5167ab8edd40f5bcae4462bf685bbe2e34456e8bead6722fe8cf0d32b7`: the reference module
  that writes those logs (`ServerLog`, `AccessLog`), used by `backend/api/main.py`. It passes
  Hydrograf's ruff and mypy configuration unchanged.

Do not edit these files; copy them again when Nogat changes them. The copies of Nogat's GUI
kit, marks and tokens are in `frontend/` (`frontend/nogat/`, `frontend/css/tokens.css`).
