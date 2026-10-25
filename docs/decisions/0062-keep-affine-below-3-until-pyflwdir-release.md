# ADR-062: Keep affine below 3 until pyflwdir releases its fix

**Date:** 2026-10-25
**Status:** accepted

## Context

`backend/pyproject.toml` caps `affine>=2.4,<3` (`f3f23dd`, 2026-10-18, carried into
`pyproject.toml` by the uv step of ADR-058): affine 3 made `Affine` an attrs class instead of a
namedtuple, and pyflwdir hands the transform to functions that numba compiles, which cannot
type that class (`Cannot determine Numba type of affine.Affine`).

Nogat's final integration run of 2026-10-25 installed every project of the ecosystem in one
environment. The cap made it resolve affine 2.4.0, where the lock of every other project has
3.0.1, and Archiwista, whose previews use the `@` operator of affine 3, failed there (F3 of
the run's report). Archiwista now declares `affine>=3,<4`, so the two cannot be installed
together. Whether the cap can go depends on the current pyflwdir.

Checked on 2026-10-25 with pyflwdir 0.5.12 (its latest release, 2026-07-01), affine 3.0.1,
numba 0.68.0, numpy 2.5.4 and Python 3.12:

- Hydrograf's offline suite on its lock with affine 3.0.1 put in front: 15 failed and 1,287
  passed (on the lock all 1,302 pass). The 15 are `tests/unit/test_flow_path.py` (13:
  `FlwdirRaster.stream_distance` and `FlwdirRaster.path`) and the DEM step of `prepare_area`
  and `analyze_watershed` (`tests/unit/test_process_dem_callers.py`, 2). Each fails in numba's
  typing of `pyflwdir.gis_utils.distance` with `Cannot determine Numba type of <class
  'affine.Affine'>`. `FlwdirRaster.set_transform` turns any transform, a tuple too, into an
  `Affine`, so no call of Hydrograf can avoid it, and `scripts/process_dem.py` needs both
  calls: `stream_distance` for `stream_distance.tif` and `hydraulic_length_km` (ADR-054),
  `path` for the flow paths (ADR-048).
- pyflwdir's own tests at `v0.5.12` pass as shipped (84), because its `tests/conftest.py` sets
  `NUMBA_DISABLE_JIT=1`. With the JIT on, 39 fail and 3 error with affine 3.0.1, against 6 and
  3 with affine 2.4.0; the 33 more are the same numba error (`slope`, `distance`, `spread2d`,
  basins, streams, upscaling, sub-grid).
- The fix is pyflwdir pull request #109 (issue #108), merged on 2026-08-17 and listed under
  0.5.13, which is not released.

## Options considered

- **A. Lift the cap now.** The DEM pipeline fails at run time (stream distance, flow paths).
- **B. Keep the cap until pyflwdir 0.5.13 is released**, then lift it.
- **C. Pin pyflwdir to the merge commit of #109** on GitHub. A third-party git dependency that
  the audit job, which exports the locked PyPI packages, does not see; and 0.5.13 also changes
  the order of cells (pyflwdir #114, #115: labels of sub-basins, the last bits of
  accumulations), which needs its own comparison of the pipeline's results.
- **D. Work around it in Hydrograf.** Not possible from outside: pyflwdir builds the `Affine`
  itself.

## Decision

Option B. The cap stays `affine>=2.4,<3`; its comment in `backend/pyproject.toml` names this
ADR.

## Consequences

- Hydrograf and Archiwista are a known incompatible pair: no environment holds both. Each is
  an application with its own lock, so only an environment of the whole ecosystem, as Nogat's
  integration run builds, meets the conflict, and such a run tests the two apart until the
  cap goes.
- When pyflwdir 0.5.13 is on PyPI: raise `pyflwdir` to `>=0.5.13`, drop the cap, refresh the
  lock, run the gate, and compare the results of the pipeline on a test area, because the
  order of cells changed.
