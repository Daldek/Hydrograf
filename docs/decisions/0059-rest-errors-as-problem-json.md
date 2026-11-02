# ADR-059: REST errors as problem+json with registry codes

**Date:** 2026-10-25
**Status:** accepted

## Context

The API answered errors with FastAPI's `{"detail": ...}`: the texts were Polish or
English depending on the endpoint, the status of invalid values was 422, the wrong admin
key was 403, and a caller could tell errors apart only by parsing the text. The Nogat
standard 2.1 gives every project one error registry (ERR), a base exception with a
registry code (DEV-11.1) and `application/problem+json` for REST errors (AGI-6.3), with
texts that follow `Accept-Language` and English by default (AGI-6.4, AGI-9.2). The front
end reads `detail` and shows it to the user.

## Options considered

- **A. Keep `{"detail": ...}`.** No work; agents and clients keep parsing text.
- **B. Problem documents with registry codes, English by default.** One shape for every
  error; the interface asks for Polish with `Accept-Language: pl`.
- **C. Problem documents with Polish texts only** (as Archiwista does for now). Simpler
  texts, but the API would not follow AGI-9.2 and an agent would read Polish.

## Decision

Option B. Code raises a `HydrografError` subclass (`core/errors.py`) with the ID of a
message in the catalogue `core/messages.py` (an English and a Polish text, an optional
hint) and a `reason`; each subclass selects a registry code (`core/_errors.py`, generated
from the vendored registry). `api/errors.py` answers with `application/problem+json`:
`type` (the registry entry of the code), `title`, `status` from the registry, `detail`,
`instance`, `code`, `hint`, `details` and, for invalid values, `errors[]` with JSON
Pointers; unknown routes, wrong methods, invalid values and unexpected exceptions map to
`not_found`, `method_not_allowed`, `validation_error` and `internal_error`. The HTTP
statuses follow the registry, so these change: invalid values 422 to 400, a wrong admin key
403 to 401 (`unauthorized`), a catchment above 250 km² 400 to 422 (`unsupported`), a missing
precipitation 400 to 404 (`no_data`), a missing boundary file 400 to 404, a path outside the
project 400 to 403 (`forbidden`). OpenAPI names every operation after its route function and
documents the problems of each route.

## Consequences

- Clients branch on `code` and `details.reason`; the texts are for people.
- The front end sends `Accept-Language: pl` and keeps reading `detail`; `admin-sewer.js`
  does not send it yet and shows English texts.
- A contract test checks that every raised error names a catalogued message and supplies
  its fields, that both languages use the same fields, and that every catalogued message is
  used; others check the problem documents and the OpenAPI document.
- The 429 of nginx and its gateway errors stay plain responses.
- **Breaking** for every client of the API that reads statuses or texts; the CHANGELOG lists
  them.

## Errata

None.
