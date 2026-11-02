# ADR-066: The Kartograf store shared with Archiwista

**Date:** 2026-11-02
**Status:** accepted; superseded in part by ADR-067 (decisions 2 and 4)
**Amends:** ADR-061 (the store of the pipeline may be a store outside the cache directory)

## Context

ADR-061 gave the pipeline a private store, `<cache_dir>/kartograf`, and made every script pass
its root explicitly. At checkpoint S4 of the store migration
(`docs/plans/2026-11-02-store-migration.md`) the author decided that Hydrograf shares the store
of the public Archiwista instance, `/home/claude-agent/data/archiwista-public/store`: a
Kartograf store (`kartograf-store/1`, producer 0.8.0.dev0, 2.7 GB, four NMT segments, 735
versions) that already holds 205 of the 207 sheets of the production area. Archiwista runs as
`claude-agent` (UID 2001, umask 077), indexes the store every few minutes and writes into it
through Kartograf's API (`run_command(root=...)`, download jobs started from its interface).
The bootstrap of Hydrograf runs in a container as `hydro` (UID 999, umask 022).

Checked on the pinned Kartograf (`26ee459`) and on this host:

1. **No lock, by design.** Kartograf publishes a version and its sidecar with an exclusive
   `os.link` (never overwrites) and re-points a standard path with a temporary link and
   `os.replace`; "concurrent writers of the same content (also from other hosts on a shared
   volume) end in one version directory without locks" (`kartograf/download/versions.py`,
   module docstring). Parallel moves of one link may leave it on an older version until the
   next call repairs it (Kartograf `docs/ARCHITECTURE.md`, "A race without locks"). Each write
   is staged in `<product>/<variant>/versions/.incoming/<host>_<pid>_<token>/` (its spec D19);
   leftovers older than 24 h are removed by the next write and reported by `iter_store` as
   `stale_incoming`.
2. **Nothing shared but the files.** The root holds no index that writers update; the SQLite
   metadata cache of each producer is its own and lives outside the store.
3. **Modes are the creator's.** Kartograf sets no mode: a file gets the umask of its writer or
   the default ACL of its directory. With `fs.protected_hardlinks = 1` (this host) a process
   may hard-link only a file it owns or can read and write; otherwise `EPERM`, which Kartograf
   reports as `download.hardlink_fs_required`.
4. **One product bypasses the directory.** *(Erratum of 2026-11-02, ADR-067: this fact named the
   wrong product.)* BDOT10k is not affected: a package is merged in the temporary directory,
   copied by content (`shutil.copyfile`) into the staging directory of the store and published
   with `os.replace`, so UID 999 reads it. The defect, a file unpacked
   with `tempfile.mkdtemp` and moved into the store with `shutil.move`, which across file systems
   copies the mode of the temporary file and narrows the ACL mask of the copy, is in Kartograf's
   `_unpack_checked_layers` (`kartograf/transport/unit_package.py`, only the channels with
   `unpack_layers`: the RCN transaction prices, `pl.gugik.rcn`) and in `_fetch_features`
   (`kartograf/download/collections.py`, the WFS cut-outs), which Hydrograf does not use.
5. **Bind mounts skip the parents.** `/home/claude-agent` and `.../archiwista-public` are 700.
   A container that bind-mounts the store itself does not look them up: UID 999 listed and
   wrote a test store below a 700 parent without any permission on the parents.

Hydrograf itself wrote `<sheet>.prj` files next to the sheets of its store (`normalize_crs`,
found in step S3); that is fixed in the same change, so Hydrograf writes nothing into a store
but what Kartograf writes.

## Options considered

- **A. Keep the private store** (ADR-061 as it is). The 205 sheets are downloaded again and
  kept twice; both producers fetch BDOT10k and SoilGrids on their own.
- **B. Share it through Kartograf's `KARTOGRAF_ROOT`.** A root a person sets for the Kartograf
  command line would silently redirect the pipeline; ADR-061 rejected relying on it.
- **C. Share it through a variable of Hydrograf** (decided), with permissions for UID 999.
  For the permissions:
  - a group (`hydro-readers`) with setgid directories: Archiwista's umask 077 strips the group
    bits of every new file, so the group loses each new download;
  - POSIX ACL with default entries (decided): a default ACL replaces the umask for the
    objects created in its directory, so the files of both producers stay open to both.

## Decision

Option C.

1. **Root.** `HYDROGRAF_KARTOGRAF_ROOT` names the store (`utils/kartograf_store.store_dir`).
   When it is set, every script uses it: the bootstrap, `download_dem`, `download_landcover`,
   `analyze_watershed`, `prepare_area` and the land cover of the CN calculation. Unset or
   empty, the private store of ADR-061 stays. The metadata cache stays in `<cache_dir>`, one
   per producer.
2. **Writers.** *(Replaced by ADR-067: Archiwista alone writes the shared store; every
   download of Hydrograf refuses while `HYDROGRAF_KARTOGRAF_ROOT` is set, and the store is
   mounted read-only for every container.)* Archiwista (its download jobs) and the bootstrap of
   Hydrograf, in a `run --rm` container that mounts the store read-write. The serving API mounts
   it read-only, so the bootstrap of its admin panel cannot write into it (it stops in step 2).
   The cache clean (`scripts.clean --include-cache` and the `cache` target of the panel)
   removes nothing from a shared store, only Hydrograf's metadata cache and the 0.7.0
   directories.
3. **Permissions.** POSIX ACL on the store only, as its owner (`claude-agent`):

   ```bash
   setfacl -R -m u:999:rwX /home/claude-agent/data/archiwista-public/store
   setfacl -R -d -m u:999:rwX,u:claude-agent:rwX /home/claude-agent/data/archiwista-public/store
   ```

   The first gives UID 999 read and write on what exists (`X`: search on directories only);
   the second makes every new file and directory open to both producers whatever their
   umask, so each can read the other's files and hard-link them when it re-points a standard
   path (fact 3). The parents keep their modes (fact 5): nothing outside the containers runs
   as UID 999.
4. **Concurrency.** *(Replaced by ADR-067: with one writer there is no rule and no guard;
   `writes_in_progress` and the guard of step 2 are removed.)* Kartograf needs no lock to keep
   the store consistent (fact 1). The rule:
   the bootstrap of Hydrograf writes into the shared store only while no Archiwista download
   job writes into it. Two writers of the same sheets would transfer them twice, and a
   standard path may stay on an older version until the next call. The guard: step 2 of the
   bootstrap stops before its first write when a staging entry in `versions/.incoming` of any
   segment changed in the last 10 minutes (`writes_in_progress`), naming the entries. The
   check is a snapshot: a job started later is not seen, and Archiwista does not check
   Hydrograf's writes, so nobody starts an Archiwista download while a bootstrap runs.

## Consequences

- Archiwista lists Hydrograf's downloads (BDOT10k, SoilGrids, the HSG raster of Poland, new
  sheets) as versions of its store, and Hydrograf reuses Archiwista's sheets.
- The store lies on `/` (ext4, 95 % used on 2026-11-02, 12 GB free); what the bootstrap adds
  lands there, not on `/data`.
- Limit of fact 4: *(erratum of 2026-11-02, ADR-067)* BDOT10k packages, of Archiwista and of
  Hydrograf alike, are readable for UID 999. The narrowed mask (`---` for UID 999) concerns only
  the RCN packages and the WFS cut-outs (fact 4), which neither the pipeline nor a set of
  Hydrograf reads; Kartograf fixes them in its own session.
- Staging: `docker-compose.staging.yml` mounts the store at `/kartograf`
  (`HYDROGRAF_KARTOGRAF_STORE` in `.env.staging`) and sets `HYDROGRAF_KARTOGRAF_ROOT=/kartograf`;
  *(erratum of 2026-11-02, ADR-067)* the mount is read-only for every container and
  `HYDROGRAF_KARTOGRAF_STORE_MODE` is removed; step H2 mounts the store and the project's
  directory read-only at their host paths. `docker-compose.yml` of the production stack does
  not change.
- Rollback: unset `HYDROGRAF_KARTOGRAF_ROOT` (the private store returns); `setfacl -R -b` on the
  store removes the ACL and gives back modes 700 and 600.
- Tests clear `HYDROGRAF_KARTOGRAF_ROOT` (`tests/conftest.py`), so a shell that sets it never
  sends a test into a real store.
