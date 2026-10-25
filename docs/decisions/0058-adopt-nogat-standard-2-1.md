# ADR-058: Adopt the Nogat standard 2.1

**Date:** 2026-10-25
**Status:** accepted
**Amends:** [ADR-009](../DECISIONS.md) (Ruff rule set), [ADR-011](../DECISIONS.md)
(development environment)

## Context

Hydrograf is one of the projects of the Nogat ecosystem. Nogat's standard 2.1
([standards/](https://github.com/Daldek/Nogat/tree/main/standards)) sets one set of
rules for development, documentation, the agent interface, errors and releases, and
the producers Hydrograf depends on (Hydrolog, Kartograf, IMGWTools) follow it. Until
now Hydrograf followed the v1 standard through a Polish copy,
`docs/DEVELOPMENT_STANDARDS.md`: Ruff with a short rule set (ADR-009), pip with a
pinned `requirements.txt`, mypy not run, a pre-commit hook as the only gate, a Polish
`CLAUDE.md`, README and documents, and no error registry. The branch `develop` holds
the storm-sewer integration (ADR-051, ADR-052), the feedback form (ADR-053) and the
Kartograf 0.7.0 migration (ADR-057); the last release is 0.4.0.

## Options considered

- **A. Stay on the v1 standard.** No work. The gate, CI, the error registry and the
  release sets of the ecosystem would not apply to Hydrograf, and every producer
  upgrade would be checked by hand.
- **B. Adopt the standard 2.1 in full, with no deviations.** Not possible now: about
  24,000 lines of Python and most documents are Polish, about 1,260 tests carry no
  annotations, the offline suite covers 73% of the measured code, and three producers
  have no `py.typed` marker yet.
- **C. Adopt the standard 2.1 step by step on a topic branch, record every shortfall as
  a deviation, and leave the items that belong to the author.** Each step is one
  commit with its documentation, and the gate is green before it.

## Decision

Option C, on the branch `chore/nogat-2.1` from `develop`, in this order:

1. the environment: uv and `backend/uv.lock`, the version `0.5.0.dev0`, the editor, git
   and `.env.example` files (DEV-6, DEV-13.1, DEV-14, REL-1.1);
2. quality: `ruff format`, the rule set `E F W I UP B SIM C4 D`, mypy `strict`, pytest
   with `--strict-markers`, `tests/contract` and a coverage floor (DEV-7, DEV-10);
3. the gate `scripts/gate.sh`, CI with a `db` job, Dependabot (DEV-7.6, DEV-7.7,
   DEV-13.6);
4. the contribution files, `CLAUDE.md` with its Deviations section, the README in the
   order of DOC-2.1 and this ADR index (DEV-13.7, DEV-16, DEV-1, DOC);
5. the error registry and `application/problem+json` for the REST API (DEV-11.1, ERR,
   AGI-6);
6. the translation of the documents, then of the Python docstrings, comments and log
   messages, to English (DEV-2.1).

The data output convention (DEV §19) and the move to the producers' standard 2.1
releases follow the first release set; the call sites are listed in
`docs/PROGRESS.md`, Next 2.

## Consequences

- The deviations are in one place, the Deviations section of `CLAUDE.md` (DEV-1.2):
  the lowered coverage floor, the mypy overrides for untyped tests, scripts and
  producers, the Linux-only CI, the `benchmark` marker, f-string logs, the 4-space
  JavaScript and the inline Polish interface text. Each one names its way back.
- ADR-009 and ADR-011 are amended: the Ruff rule set is larger, and uv with a lock
  file replaces `requirements.txt` and optional dependency groups.
- The required checks of the branch rulesets are the `gate` job of Python 3.12 and the
  `db` job of `ci.yml`.
- Left to the author (DEV-3.3): the history rewrite of phase 1 (until then the commit
  step of the gate needs `GATE_COMMIT_RANGE=develop..HEAD`), the GitHub rulesets and
  private vulnerability reporting, the text of `docs/CLA.md`, the `Approved:` lines of
  plans, tags and releases, the replacement of the producers' tag pins, pushing the
  branch and merging it into `develop`.
- A reader of the code finds English names and text except where `docs/PROGRESS.md`
  lists Polish that remains; the interface text stays Polish (DEV-2.2).

## Errata

None.
