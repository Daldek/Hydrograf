# ADR-068: The hand-off to Hydrolog is built by the API

**Date:** 2026-11-04
**Status:** accepted

## Context

The author wants to copy a watershed with its rainfall and result from Hydrograf's GUI to
the clipboard (or a file) and paste it into Hydrolog's GUI, which reads Nogat's envelope
`nogat-handoff/1` carrying `hydrolog-network/1` and compares the producer's result with
its own. Hydrolog shows Qmax to 0.01 m³/s, the time to peak to the minute and the volume
to 1 m³, so a hand-off whose inputs are rounded shows a difference that is not there. The
responses of the API round the PMAXTP depth (0.01 mm), the time of concentration (0.1 min),
Nash's n and K and the result; a hand-off with the rounded depth of the Kamiennik differs
from Hydrograf's volume by tens of m³. Hydrograf's own tc methods (NRCS and Kirpich along
the longest flow path) are not Hydrolog's, so tc must travel as a value. The schema
`hydrolog-network/1` refuses unknown watershed keys, and Hydrolog's GUI keeps a handed
PMAXTP depth only when the provenance names its point, probability and duration.

## Options considered

- **A. The front end builds the hand-off from the existing responses.** No API change, but
  the rounded values make Hydrolog report a difference, and the front end has neither
  Hydrograf's nor Hydrolog's version.
- **B. The front end builds it, the API adds the unrounded values it lacks.** Exact, but
  the mapping to Hydrolog's names would live in JavaScript and Python, and the document
  could not be validated by the test suite (no JavaScript test runner).
- **C. A separate endpoint that builds the hand-off on demand.** One builder, but it
  recomputes the hydrograph and writes the clipboard after a request, which some browsers
  refuse outside the click.
- **D. The API builds the whole document in the responses of the delineation and of the
  hydrograph.** One builder in Python with the exact values, tested against both schemas
  and against Hydrolog's own computation; the front end copies what it received.

## Decision

Option D. `core/handoff.py` writes `nogat-handoff/1` (the vendored
`schemas/nogat/handoff-1.schema.json`) with one subcatchment `Z1` flowing to the outlet
`OUT`, as Hydrolog's „Hydrogram zlewni” writes and opens it; the watershed in the keys of
`WatershedParameters` (`length_to_centroid_km` as `Lc_km`, without `source` and `crs`),
named after its outlet („Zlewnia 51,01679° N, 15,88923° E”). `POST
/api/delineate-watershed` returns `handoff` without rainfall and result; `POST
/api/generate-hydrograph` returns `handoff` with the runoff the generator used (tc for
SCS, n and K for Nash, L, Lc, Ct and Cp for Snyder), the rainfall (the PMAXTP design storm
with its shape, or the user's series), the time step and the result with
`computed_with` Hydrolog's version, all unrounded. The provenance names the watershed
(Hydrograf with the outlet and the fields changed in the advanced mode, from the new
request field `morphometry_origin`; without it, `user`), the rainfall (`pmaxtp`, method
POT, probability, duration, the request point, `interpolation` `idw`; or `user`) and the
derived runoff parameters (the tc method, the Nash estimation). The front end
(`js/handoff.js`) copies the hand-off of what the panel shows or downloads it as
`<name>.handoff.json`.

## Consequences

- Hydrolog's `hydrograph generate` recomputes a hand-off to Hydrograf's result exactly
  (unit tests over every model, hyetograph, AMC and the user's series), so its comparison
  says „zgodny” while both use the same Hydrolog.
- The responses carry about 1–2 kB more (the series of an own rainfall more).
- Nogat's envelope is a copy: a new version of `handoff-1.schema.json` is copied again.
- Hydrolog refuses a hand-off without rainfall for now, so the watershed alone (above
  250 km², or before its hydrograph) does not open there until Hydrolog accepts it.
- `jsonschema` joins the dev dependencies for the schema tests.

## Errata

None.
