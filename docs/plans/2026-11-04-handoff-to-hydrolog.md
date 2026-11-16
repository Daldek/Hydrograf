# Hand-off of a watershed to Hydrolog's GUI: plan

**Approved:** 2026-11-04, the author (scope: copy/download the hand-off for Hydrolog,
clipboard + file, no sync; branch merged after v0.5.0); design details by delegated
authority, to be reviewed at the merge.

**Goal:** the person copies the watershed Hydrograf delineated, with its rainfall and
result when the hydrograph is computed, from the panel „Zlewnia” to the clipboard (or a
file) and pastes it into Hydrolog's GUI („Wczytaj z Hydrografa” → „Wklej ze schowka” /
„Plik przekazania…”), which opens it in „Hydrogram zlewni” and shows Hydrograf's result
beside its own.

**Constraints:** the format is Nogat's `nogat-handoff/1` (copied verbatim into
`schemas/nogat/`) carrying Hydrolog's `hydrolog-network/1`; clipboard and file only, no
URL or one-click sync (the author's decision); Hydrograf is frozen until v0.5.0, so the
work stays on `feature/handoff-to-hydrolog` and is merged after the release.

## Design (ADR-068)

1. **The API builds the document** (`backend/core/handoff.py`), where the exact values
   live: the PMAXTP depth, the time of concentration, Nash's n and K and the result are
   rounded in the responses, and Hydrolog's comparison (Qmax to 0.01 m³/s, the volume to
   1 m³) shows a difference for any rounded input.
2. `POST /api/delineate-watershed` returns `handoff`: the watershed without rainfall and
   result. `POST /api/generate-hydrograph` returns `handoff`: the watershed with the
   runoff (SCS-CN with the tc used, or Nash's n and K, or Snyder's L, Lc, Ct and Cp), the
   rainfall (the PMAXTP design storm or the user's series), the time step and the result
   computed with Hydrolog (its version in `result.computed_with`).
3. The request may name where its `morphometry` came from (`morphometry_origin`: the outlet
   of the delineation and the fields the person changed in the advanced mode); the
   provenance of the watershed is then Hydrograf's with that outlet, else the user's.
4. The front end (`js/handoff.js`) shows the part „Przekazanie do Hydrologa” below the
   sections of the panel: what the hand-off holds, „Kopiuj do Hydrologa” (Clipboard API,
   else a selected text field) and „Plik przekazania” (`<name>.handoff.json`).

## Verification

- Unit tests (`backend/tests/unit/test_handoff.py`): the hand-offs validate against the
  vendored envelope and the network schema of the pinned Hydrolog, and Hydrolog's
  `hydrograph generate` recomputes each payload (SCS, Nash, Snyder, every hyetograph,
  AMC I–III, the user's series) to its result exactly.
- Round trip: a hand-off of the Kamiennik (51.01544, 15.88984) from the branch's GUI
  against the read-only production API, pasted into Hydrolog's GUI, opens in „Hydrogram
  zlewni” with the comparison „zgodny”.

## Open (Hydrolog's side)

- Hydrolog refuses a hand-off without rainfall („Zlewnia Z1 nie ma opadu”), so the
  watershed alone (above 250 km², or before the hydrograph) does not open yet.
- Hydrolog's texts name Hydrograf's button „Do schowka” and say the buttons are „w
  przygotowaniu”; Hydrograf's button is „Kopiuj do Hydrologa”.
