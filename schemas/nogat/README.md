# Copies of the Nogat standard

Verbatim copies (ERR-3, AGI-4.1, DEV-15.6) of the files below of the
[Nogat](https://github.com/Daldek/Nogat) repository. Nogat's `uv run scripts/ecosystem.py
drift` reports each copy as current, behind or modified.

The standard's agent schemas, the server and job documents and the registry, copied
from Nogat's `develop` `f5f6e67` (the merge of its `feat/latarnik-nogat`, standard 1.3,
ECO-095: AGI-6.1 to AGI-6.10) for Hydrograf's `/api/v1` (ADR-091):

- `error_registry.json` (Nogat `standards/error_registry.json`): error codes, exit codes
  and HTTP statuses, with the meanings of `job_expired`, `job_running` and `run_as_job`.
  `backend/core/_errors.py` is generated from it with
  `cd backend && uv run python -m scripts.generate_errors`.
- `result-1.schema.json`, `error-1.schema.json`, `commands-1.schema.json`,
  `command-list-1.schema.json` (Nogat `schemas/agent/`): the schemas of the result
  envelope `hydrograf-result/1` of every command, the error document, the full catalog
  `hydrograf-commands/1` and its summary `hydrograf-command-list/1` (`backend/api/catalog.py`,
  `GET /api/v1/commands/schema`, `GET /api/v1/commands/list`). REST errors are
  `application/problem+json` with the members of the error document (AGI-6.3).
- `server-1.schema.json` (Nogat `schemas/exchange/server-1.schema.json`): `nogat-server/1`,
  the answer of `GET /api/v1/server`.
- `job-1.schema.json` (Nogat `schemas/exchange/job-1.schema.json`): `nogat-job/1`, the job
  of a long command (`POST /api/v1/jobs`, `backend/api/jobs.py`).

`backend/tests/contract/test_catalog.py` validates Hydrograf's documents against these copies.

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
0.10.0 (`v0.10.0`) reads the same copy (the same SHA-256), with `node_provenance`, `attribution` and
`terms_notice`:

- `handoff-1.schema.json` (Nogat `schemas/exchange/handoff-1.schema.json`): the envelope
  `nogat-handoff/1` of data handed between the GUIs of the ecosystem. The API writes the
  hand-off of a watershed (ADR-068, with `attribution` and `terms_notice` of a PMAXTP rainfall,
  ADR-083) and of a network (`network delineate`, ADR-080, with `node_provenance`) to
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
