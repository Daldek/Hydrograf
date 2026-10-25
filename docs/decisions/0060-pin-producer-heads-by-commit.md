# ADR-060: Pin the Hydrolog and IMGWTools heads by commit

**Date:** 2026-10-25
**Status:** accepted

## Context

Hydrograf pins its producers by release tag (REL-5.1): Kartograf `v0.7.0`, Hydrolog
`v0.6.3`, IMGWTools `v2.1.0`. The producers have moved on to the standard 2.1 and to the
data output convention (ECO-051) without a tag: Hydrolog 1.0.0 and IMGWTools 3.0.0 are
untagged, Kartograf 0.8.0 is untagged and its `feature/data-output` is not finished. The
Nogat adoption plan (phase 5, item 5.1) and REL-5.3 let a consumer that needs the
unreleased API migrate on a branch that pins the producer's commit; the release pull
request replaces the commit with the tag, and branch pins and editable installs are not
committed.

The heads of 2026-10-25 are:

- Hydrolog `feature/routing-network` @ `6c9ba5a` (1.0.0.dev0): `chore/nogat-2.1` and the
  flood-routing branches stacked on it. It ships `py.typed`.
- IMGWTools `feature/data-output` @ `a304521` (3.0.0). `fetch_pmaxtp`, the only function
  Hydrograf calls, keeps its model (`result.data.ks`, `sg`, `rb`, `get_precipitation`);
  its `method` argument became keyword-only, and Hydrograf passes only `latitude=` and
  `longitude=`. It ships no `py.typed` although it declares `Typing :: Typed`.
- Neither commit is on GitHub. `uv lock` and `uv sync` resolve a commit that is not on
  GitHub only on a machine whose uv git cache holds it.

What the heads change for Hydrograf, measured on the endpoint `POST /api/generate-hydrograph`
(138 combinations of three catchments, six concentration-time methods, three hyetograph
types and the three unit hydrograph models, Hydrolog 0.6.3 against the head): the results of
the Snyder model change (peak 11 to 12% higher, 25 to 70 minutes earlier at a time step of 5
minutes, the same volume) because Hydrolog now applies the duration correction of Snyder;
everything else is the same number. The typed Hydrolog makes mypy report three errors in the
hydrograph endpoint and two in `scripts/analyze_watershed.py`.

## Options considered

- **A. Wait for the tags.** The pins stay, the heads are not tested, and the migration meets
  the first release set (ADOPTION_PLAN phase 5) with nothing run against it.
- **B. Pin the commits of the heads on a topic branch** (REL-5.3), seed the uv git cache of
  the machine with the unpushed ones, migrate the calls, run the gate. The release replaces
  the commits with tags.
- **C. Path or editable dependencies on the sibling checkouts.** No git cache to seed, but
  the lock would name a directory of one machine, and REL-5.3 forbids committing it.
- **D. Hydrolog at `chore/nogat-2.1` (`d4f7282`) instead of the routing head.** The same
  library without the routing code, which Hydrograf does not call. The routing head was
  chosen because it holds everything that Hydrolog's next release is to carry once its
  branches are merged in the order of its PROGRESS, so the pin does not have to move for
  the routing.

## Decision

Option B, on the branch `feature/producer-heads`. `backend/pyproject.toml` pins Hydrolog
`6c9ba5afae65c601c447f48f5c1412e93f3a1d60` and IMGWTools
`a30452182b01f47cc18e48466da4edf4d0c8cb6a`; Kartograf stays on `v0.7.0`, because its data
output is not finished and the plain mode that its migration waits for is still moving
(`docs/PROGRESS.md`, Next 2, lists what remains). The lock records `rev=<sha>`. The unpushed
commits reach the uv git cache with `git fetch` from the local checkout into the database
of the producer's GitHub URL (the way Retman did for IMGWTools). The mypy override of
Hydrolog is gone, the one of IMGWTools and Kartograf stays with its reason. The calls into
Hydrolog and IMGWTools needed no change of behaviour; the call sites the typed Hydrolog
flagged were annotated (`api/endpoints/hydrograph.py`) or switched to the float attribute
`total_effective_mm` (`scripts/analyze_watershed.py`).

## Consequences

- The lock holds two commits that GitHub does not have. The CI jobs `gate` and `db`
  (`uv sync --locked`) and the Docker build (`uv sync --locked --no-dev`, which fetches the
  git dependencies) fail until Hydrolog and IMGWTools push those commits; the running
  stack keeps the image built on the old pins. The push is the author's step (DEV-3.3).
- `platformdirs`, a dependency of both producers, is a new package of the lock; no other
  third-party version changed.
- **Breaking** for clients of the API that use `uh_model: "snyder"`: the hydrograph differs
  (CHANGELOG).
- `nash_estimation: "from_tc"` calls `NashIUH.from_tc`, which Hydrolog has marked deprecated
  since 0.6.2 and announced for removal in 1.0.0; the head still has it and warns. Whether
  the REST option goes with it is a decision of the author (PROGRESS, Open questions).
- When a producer is tagged, the release pull request replaces its commit with the tag
  (REL-5.3), the lock is refreshed and the gate run again; the Kartograf pin changes in its
  own migration.

## Errata

**2026-10-25: the pins moved and every commit is on GitHub.** The text above records the first
migration: Hydrolog `6c9ba5a`, IMGWTools `a304521`, two commits that GitHub did not have, and
Kartograf on `v0.7.0`. The producers have pushed their heads since and the lock follows them:
IMGWTools `7e2114e`, then `3f7de36` (3.0.0: float PMAXTP percentages, so the `type: ignore` of
`scripts/preprocess_precipitation.py` is gone; it ships `py.typed`), then `6bd35a4` (a flush of
the MCP server's stdout, which Hydrograf does not start); Hydrolog `31bf796`
(`feature/routing-objects`), then `5fa22b3` (`feature/routing-schematic`); Kartograf `b73aad3`
by ADR-061, then `45dedf4`, then `c31ca04`. `uv lock`, `uv sync --locked` and the image build resolve all three
anywhere, so the Consequences about unpushed commits and the uv git cache no longer apply, and
the mypy override of IMGWTools is gone with the one of Kartograf (ADR-061). The decision
(option B) stands.
