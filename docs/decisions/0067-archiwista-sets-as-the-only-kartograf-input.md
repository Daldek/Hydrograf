# ADR-067: Archiwista's sets as the only Kartograf input of the shared store

> **Amended by ADR-079 (2026-11-10):** the HSG pin of decision 3 is a version of the segment
> of `soil.hsg_depth_rule`, by default `hsg/global_soilgrids_0-100cm_least-permeable_mean/`
> (`topsoil`: `hsg/global_soilgrids_0-5cm_mean/`). A set without a raster of that segment that
> covers the mosaic is refused (`set_hsg_missing`), whatever HSG raster of another rule it
> holds; the hint names the Kartograf command that computes the raster.

**Date:** 2026-11-02
**Status:** accepted
**Supersedes in part:** ADR-066 (decisions 2 and 4)

## Context

ADR-066 shared the Kartograf store of the public Archiwista instance,
`/home/claude-agent/data/archiwista-public/store`, with Hydrograf and made the bootstrap a second
writer: a `run --rm` container that mounted the store read-write
(`HYDROGRAF_KARTOGRAF_STORE_MODE=rw`), guarded by a time window (`writes_in_progress`, step 2 stops
when a staging entry changed in the last 10 minutes) and by a rule for people (nobody starts an
Archiwista download while a bootstrap runs). The results of a run were tied to no list of inputs:
whatever the store held when step 2 ran.

On 2026-11-02 the author chose variant B of the cross-project plan
`docs/plans/2026-11-02-archiwista-sets-for-hydrograf.md` of Nogat (branch
`plan/archiwista-sets-hydrograf`, from commit `d2f17ac`):

- Archiwista is the only program that writes the shared store.
- Hydrograf reads it only through a project of Archiwista (`archiwista-project/1`, the file
  `archiwista-project.json` of the project's directory) and one of its sets (*zestaw*: a group of
  pins, each a version path of the store with its size and SHA-256), strictly: every Kartograf
  input of the bootstrap is a pin of the set, checked before step 1; a missing or changed input
  stops the run with a code of the error registry and a hint naming the Archiwista action that
  fixes it.
- Consumers read closed sets only. Archiwista's draft sets (step A2 of that plan, agreed with
  Hydrograf) give a set a `state`: `open` (*w budowie*, its content changes) or `closed` (absent
  is closed, so every set written before draft sets is closed). Closing writes `closed_at`,
  `closed_by` and `pins_sha256` together; a closed set is frozen (no re-pin, no new pin) and
  changes only by „Otwórz do edycji”, an edit and „Zamknij zestaw”, which writes a new digest.
- D3: the set holds the 205 sheets that Kartograf selects from the project's area, no extra
  sheets. Production's list of 207 came from an envelope rule: `M-33-33-C-b-2-1` touches the area
  with 0 m², and `M-33-45-B-c-1-1` holds about 935 m² of the old clip boundary at the divide,
  which is negligible.
- D4: the set's HSG raster covers Poland's box widened by 100 km, EPSG:2180
  `67000 -71000 960000 914000`; Hydrograf checks that the pinned raster covers the NMT mosaic,
  not a fixed box.
- D8: a bootstrap from a set in the admin panel is out of scope (a later plan); the panel refuses
  against the shared store.
- D11: UID 999 (the container user `hydro`) reads the store only (`rX`), as Hydrograf no longer
  writes it.

IMGW PMAXTP (step 6 of the bootstrap) stays outside sets.

## Options considered

- **A. Keep ADR-066: the bootstrap writes the shared store too.** Rejected by the author: two
  writers, a time guard that sees only a snapshot and a rule that people must keep, and results
  not tied to a set.
- **B. Archiwista alone writes; Hydrograf reads a closed set strictly and stops on a missing
  input** (decided).
- **C. Hydrograf reads a set and downloads what it lacks into its private store.** Rejected: a
  run would mix pinned and unpinned data without saying so.

## Decision

Option B.

1. **The command.** `python -m scripts.bootstrap --project PATH --set NAME [--dry-run]`;
   `--project` takes the project's directory or its `archiwista-project.json` and goes with
   `--set` only; both are exclusive with `--bbox`, `--sheets` and `--boundary-file`. The set's
   name is compared NFC-normalised, trimmed and case-folded. Before step 1 the bootstrap checks,
   in this order: the project file; the area file (`obszary/…`) with its recorded SHA-256; the
   set, which must be closed (`state` absent or `closed`); a recorded `pins_sha256`, which must
   equal the digest computed from the pins; the project's Kartograf store (absolute, or relative
   to the project's directory), whose Kartograf `store_state` must be `marked`, and, when
   `HYDROGRAF_KARTOGRAF_ROOT` is set, which must be the same directory (`os.path.samefile`); every
   Kartograf pin, read whole (size and SHA-256); then what the run needs (items 3 to 6).
   `--dry-run` stops after the checks and prints the project, the set's state (`closed_at`,
   `closed_by`), the area's SHA-256, `pins_sha256` (the file's, else computed), the store, the
   pins and steps 2 to 5 as the set gives them.
2. **Mounts.** The store and the project's directory are bind-mounted read-only at their host
   paths, so the absolute store root of the project file holds as written and no path mapping is
   kept; `HYDROGRAF_KARTOGRAF_ROOT` names the store's host path (item 11).
3. **Which pin is which product: the segment of its version.** NMT
   `nmt/pl_1992_<--resolution>_evrf2007/versions/`, BDOT10k `landcover/pl_bdot10k_gpkg/versions/`,
   HSG `hsg/global_soilgrids_0-5cm_mean/versions/`. Other Kartograf pins (the SoilGrids inputs of
   the HSG raster) are verified, not used; pins of other producers are not read. **One version per
   unit**, the unit being the stem of the file: a sheet code, a county code (TERYT), a box. Two
   versions of one unit, or two HSG rasters that both cover the mosaic, are refused.
4. **Sheets.** The sheets of the project's area, `find_sheets_for_geometry(<area file>,
   "1:10000", sheet_system="1992")` (Kartograf's selection by shape, ADR-058, the rule
   Archiwista's call applies), must be among the NMT pins. Pinned sheets beyond the area are used
   too: the mosaic is every pinned sheet of the segment.
5. **Counties** (unless `--skip-landcover`). The counties that PRG names for the box of the
   frames of the pinned sheets (`Bdot10kProvider(cache=<cache_dir>/kartograf_meta.db)
   .teryts_for_area`, the rule of steps 3 and 4 before) must be among the BDOT10k pins. PRG is a
   lookup, not data: the set's own call cannot prove what it covers.
6. **HSG coverage** (unless `--skip-hsg`). Exactly one HSG pin whose requested box, from its
   Kartograf sidecar (`read_sidecar(...).request`: `bbox` and `bbox_crs`, transformed to
   EPSG:2180), covers the box of the NMT mosaic (D4). The private-store path keeps Poland's box
   `167000 29000 860000 814000`.
7. **Steps 2 to 5 from the pins**, by their version paths, which never change: step 2 downloads
   nothing and reports `N/N arkuszy z zestawu`, step 3 burns the streams of the pinned BDOT10k
   packages, step 4 imports them, step 5 clips the pinned HSG raster to the mosaic as before.
   Steps 6 to 10 do not change; the precipitation grid takes the WGS84 box of the area.
8. **Closed sets only; the digest.** An open set is refused. `pins_sha256` is the lowercase
   hexadecimal SHA-256 of the UTF-8 lines `<producer>\t<version>\t<sha256>\n`, one per pin of the
   set, sorted by (`producer`, `version`) by code point; the definition is Archiwista's (draft
   sets) and is shared. Test vector: the pins (`kartograf`,
   `nmt/pl_1992_5m_evrf2007/versions/b.asc`, 64 × `b`) and (`kartograf`, `hsg/a.tif`, 64 × `a`)
   give `e7319a8d77a126fc2eb12f46b92ef5ac98a5b2132808474eebbb222fd5c691fe`.
9. **Refusals.** A failure ends the run with the exit code of the registry and, as the last line
   of standard error, the error document `hydrograf-error/1` (AGI-3.3, AGI-9.2;
   `HydrografError.document()`), after the Polish lines `BŁĄD:` and `Wskazówka:`. Every code is
   in the shared registry; none is new.

   | Situation | Code | `details.reason` | Exit | Hint |
   |---|---|---|---|---|
   | an argument error, `--project` without `--set` (or the reverse) included | `validation_error` | `invalid_arguments` | 2 | `--help` |
   | `--bbox`, `--sheets` or `--boundary-file` while `HYDROGRAF_KARTOGRAF_ROOT` is set | `forbidden` | `shared_store_read_only` | 12 | `--project` and `--set`, or unset the variable to download into `<cache_dir>/kartograf` |
   | no project file | `not_found` | `project_file_missing` | 3 | |
   | the project file cannot be read | `io_error` | `project_file_unreadable` | 9 | |
   | a schema other than `archiwista-project/1` | `unsupported` | `project_schema_unsupported` | 15 | |
   | the file breaks its format (a new rule: `set_state`) | `data_error` | `project_file_invalid` | 7 | `details` name the pointer and the rule |
   | the project has no area, or its file is gone | `not_found` | `area_missing` | 3 | |
   | the area file's SHA-256 differs | `data_error` | `area_changed` | 7 | |
   | the area file is no readable geometry | `data_error` | `area_unreadable` | 7 | |
   | no set of the name | `not_found` | `set_not_found` | 3 | `details.sets` lists the sets |
   | the set is open | `conflict` | `set_open` | 4 | Archiwista: „Zamknij zestaw” |
   | the recorded `pins_sha256` differs from the pins | `data_error` | `set_digest_mismatch` | 7 | |
   | no store, or not a marked Kartograf store | `store_unavailable` | `store_missing` | 8 | |
   | the store is not `HYDROGRAF_KARTOGRAF_ROOT` | `validation_error` | `store_mismatch` | 2 | |
   | a pinned file is absent | `not_found` | `pin_missing` | 3 | `details.pins`; Archiwista: „Przywróć brakujące” (`archiwista project-restore`) |
   | a pinned file cannot be read | `io_error` | `pin_unreadable` | 9 | the ACL of item 11 |
   | a pinned file's size or SHA-256 differs | `data_error` | `pin_changed` | 7 | Archiwista: „Weryfikuj” (`archiwista project-verify`), then „Przywróć brakujące” |
   | sheets, counties or the HSG raster missing from the set | `no_data` | `set_sheets_missing`, `set_counties_missing` (`details.units`), `set_hsg_missing` (`details.rasters`) | 14 | Archiwista: „Otwórz do edycji”, a call that covers the project's area, „Zamknij zestaw” |
   | PRG does not answer | `source_unavailable` | `prg_unavailable` | 5 | try again |
   | two versions of one unit, or two HSG rasters that cover the mosaic | `conflict` | `set_unit_ambiguous` | 4 | a set with one version per unit |

10. **Hydrograf never writes the shared store.** `utils/kartograf_store.py` gains
    `refuse_shared_store()` and `private_store_dir(cache_dir)`: while `HYDROGRAF_KARTOGRAF_ROOT` is
    set, every download refuses with `forbidden`, reason `shared_store_read_only`:
    `download_bdot10k`, `scripts.download_dem.download_sheets`,
    `scripts.download_landcover.fetch_landcover` and steps 2 and 5 of the bootstrap's private
    path; so `download_dem`, `download_landcover`, `prepare_area`, `analyze_watershed --download`
    and the CN fallback refuse too (the CN fallback logs the refusal as an error and takes the
    default CN). `POST /api/admin/bootstrap/start` of the admin panel answers `403` problem+json
    before it starts a process (D8). `store_dir()` still returns the shared store for the readers
    (the sheet listing of `analyze_watershed`, the cache clean). Unset, the private store of
    ADR-061 downloads as before. Removed, without shims: `writes_in_progress`,
    `ACTIVE_WRITE_WINDOW_S`, `STAGING_GLOB`, the write guard of step 2, ADR-066's rule that nobody
    downloads in Archiwista while a bootstrap runs, and `HYDROGRAF_KARTOGRAF_STORE_MODE` of
    `docker-compose.staging.yml`.
11. **Mounts and ACL** (staging, step H2 of the plan). The store and the project's directory are
    mounted read-only at their host paths:
    `${HYDROGRAF_KARTOGRAF_STORE}:${HYDROGRAF_KARTOGRAF_STORE}:ro` with
    `HYDROGRAF_KARTOGRAF_ROOT: ${HYDROGRAF_KARTOGRAF_STORE}`, and
    `${HYDROGRAF_PROJECT_DIR}:${HYDROGRAF_PROJECT_DIR}:ro` with
    `HYDROGRAF_PROJECT_DIR=/home/claude-agent/data/archiwista-public/projects/kaczawa` (after the
    author moves Kaczawa there, step A4). The owner `claude-agent` narrows ADR-066's grant to read
    (D11), on the store and on the project's directory:

    ```bash
    setfacl -R -m u:999:rX <dir>
    setfacl -R -d -m u:999:rX,u:claude-agent:rwX <dir>
    ```

    The default entries keep every new version and every new project file readable for UID 999.
12. **The set record.** A run from a set logs its identity in one line (`Bootstrap from a set:
    {json}`) and writes `<output>/bootstrap_set.json` (schema `hydrograf-bootstrap-set/1`): the
    project (path, name, the area's SHA-256), the set (name, `closed_at`, `closed_by`,
    `pins_sha256`, whether the file recorded it, the pins), the store, the inputs (the NMT segment
    with its counts, the BDOT10k packages, the HSG version, the pins not used, the pins of other
    producers), `started_at`, `finished_at` and `status` (`running`, then `ok` or `failed`). It is
    written when the run starts and completed when it ends; a run without a set deletes it, so no
    data is credited to a set it did not come from. The admin panel does not show it.

## Consequences

- One writer: the store changes only through Archiwista, and a database built by Hydrograf names
  the set and its `pins_sha256` it came from. A run may proceed while Archiwista downloads: the
  closed set does not change, its version paths never change, and every pin is hashed at the
  start; a set reopened later is refused by the next run (`set_open`).
- Hydrograf downloads only into its private store. A run against the shared store needs a closed
  set that holds every input; what is missing is added in Archiwista, never by Hydrograf.
- Every pin is read whole before step 1 (about 1.1 GB for the Kaczawa set of the plan).
- **ADR-066 fact 4 was wrong for BDOT10k** (erratum there): the mode defect (`tempfile.mkdtemp`
  plus `shutil.move`, which narrows the ACL mask across file systems) is in Kartograf's
  `_unpack_checked_layers` (`src/kartograf/transport/unit_package.py:559-588`, used only by
  channels with `unpack_layers`: the RCN transaction prices, `pl.gugik.rcn`) and in the WFS
  cut-outs of `_fetch_features` (`src/kartograf/download/collections.py:3182-3195`). BDOT10k
  packages are merged in `TMPDIR`, copied by content (`shutil.copyfile`) into the staging
  directory and published with `os.replace`, so UID 999 reads them; the writers of the NMT, the
  SoilGrids inputs and the HSG raster are not affected either. Kartograf fixes the two writers in
  its own session (D10).
- Rollback: unset `HYDROGRAF_KARTOGRAF_ROOT` to return to the private store, where the downloads
  work as before.
- Risk: a project directory created again loses its ACL; the bootstrap then stops with
  `io_error` (`pin_unreadable`, or `project_file_unreadable`) until the `setfacl` commands of
  item 11 run again.
- Risk: `archiwista-project/1` changes; only that schema id is read (`unsupported` otherwise).
- Draft sets of one producer only (Archiwista's D12): a set of several producers would need
  `archiwista-project/2`; Hydrograf reads only the `kartograf` pins of a set and ignores the
  others.
