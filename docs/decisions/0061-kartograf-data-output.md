# ADR-061: Kartograf data output: the store for the cache, plain files for single-use rasters

**Date:** 2026-10-25
**Status:** accepted

## Context

Kartograf 0.8.0 (head `b73aad3`, untagged) follows the Nogat data output convention (ECO-051,
DEV §19): every command that writes has two targets, `root` (a versioned store: marker
`kartograf-store.json`, `versions/`, a hard-linked standard path, a sidecar per file) and
`output_dir` (plain files named as in the store, no metadata). A call that names neither
writes the default store in the data directory of the user. The classes `LandCoverManager` and
`HSGCalculator` are gone from the public API (`download_landcover`, `download_soil`,
`calculate_hsg`, `hsg_statistics` replace them), `DownloadManager(provider, *, root=)` takes the
provider first, `calculate_hsg` requires `depth`, the find functions require `sheet_system`,
and the errors are `KartografError`s with a registry code and a hint (ADR-060 pinned the other
two producers; this one moves Kartograf from `v0.7.0` to the head).

Hydrograf has to choose the target of each of its downloads. I ran the real Kartograf with the
network replaced by stubs of its provider classes (`tests/kartograf_offline.py`) and compared
the two modes on the same request: three sheets, one with only a partial flight (a sheet on
the border has no full flight), one whose newest flight is partial and an older one is full.

- **Store:** every sheet is written, from the newest flight, partial or not; the standard path
  is `<root>/nmt/pl_1992_5m_evrf2007/<hierarchy>/<sheet>.asc`; a second run answers `local` for
  every sheet and transfers nothing; `update="force"` fetches again and answers `unchanged`.
- **Plain (`output_dir`):** the sheet that has only a partial flight is **left out**
  (`DownloadResult.incomplete`), the sheet whose newest flight is partial gets the **older full
  flight** (another DEM than the store's), and a second run is `conflict` / `output_exists` for
  the whole request, because the files are there.

## Options considered

- **A. Plain files for every download** (`output_dir`), Hydrograf filters what exists. Drops the
  border and coast sheets (holes in the DEM mosaic and in the drainage network at the border of
  Poland), changes the selection of the flight, and needs a list of existing names that
  duplicates Kartograf's naming. Rejected for the NMT and BDOT10k.
- **B. The store for every download**, also the HSG raster of one analysis. A version of three
  SoilGrids inputs and one HSG raster per distinct bbox stays in the store for ever, for a raster
  that is read once.
- **C. Per call site** (decided): the store where Hydrograf re-runs and reuses, plain files where
  a result is used once.

## Decision

Option C. The store of the pipeline is `<cache_dir>/kartograf` (`paths.cache_dir`, default
`cache/`), a directory of its own: Kartograf refuses a root that holds other files (`conflict`,
`not_empty`) and one that has the layout and no marker (`store_unavailable`, hint
`kartograf store init --root DIR`). The metadata cache stays beside it, `<cache_dir>/kartograf_meta.db`
(SQLite needs a local disk, and a foreign file would be refused in the store). Every script passes
`root=` and `cache=` explicitly (`utils/kartograf_store.py`); none relies on `KARTOGRAF_ROOT` or on
the default store, and the read-only root file system of the API container is never written.

| Call site | Target | Reason |
|---|---|---|
| NMT sheets: `download_dem.download_sheets` (bootstrap step 2, `analyze_watershed --download`, `prepare_area`, the `download_dem` script) | store, `DownloadManager(provider, root=)` | a re-run skips the local sheets; the newest flight is used also when partial (border, coast); the standard path is stable; newer flights can be fetched later |
| BDOT10k packages: bootstrap steps 3 and 4, `prepare_area`, the land cover of the CN calculation, the `download_landcover` script | store, `download_landcover(product="bdot10k", root=)` | a county is 100 MB or more and reused by the pipeline and by the CN calculation; one request finds every county of an area |
| HSG raster of Poland: bootstrap step 5 | store, `calculate_hsg(root=, bbox=, depth="0-5cm")` | fetched once, `reused` after; replaces `soil_hsg/hsg_poland.tif` and its staleness check by the producing version (`check_hsg_cache`), which Kartograf's versions replace |
| HSG of one analysis: `get_hsg_from_soilgrids` | plain, `calculate_hsg(output_dir=<temporary directory>, cache=False)` | single-use; the inputs go to Kartograf's staging directory, nothing stays; `hsg_statistics` of a file without a sidecar counts the whole raster, as 0.7.0 did |
| `prepare_area` | its own store `<output>/kartograf` | a stand-alone script with a working directory, as before (`<output>` was its Kartograf root) |

`find_existing_nmt_files` reads the store through `iter_store` (the standard paths, `kind == "link"`)
instead of a directory scan, so neither `versions/` nor `full_sheet/` is listed. Errors: the
scripts catch `KartografError` where the old code caught `Exception` to mean "the download failed"
(an API change is no longer reported as "no land cover"), and show the registry code and the hint
(`describe_error`). The mypy overrides of `kartograf` and `imgwtools` are gone: both ship `py.typed`.

## Consequences

- **Breaking:** the cache layout changes. `cache/nmt/`, `cache/bdot10k/` and `cache/soil_hsg/`
  are not read; delete them (no data migration, the heads are unreleased). `kartograf_meta.db`
  moves nowhere; the first run writes `cache/kartograf/`.
- `download_dem` and `download_landcover` take `--root` (the store) and `--metadata-cache` instead
  of `--output`/`-o`; `prepare_area` loses `--landcover-provider` (CORINE by county never worked:
  `CorineProvider.download_by_teryt` always raised) and `analyze_watershed` has a `cache_dir`
  next to `data_dir`; `determine_cn(data_dir=)` is `cache_dir`.
- A store needs hard links: the cache directory cannot be on FAT, exFAT or SMB.
- The land cover of a CN calculation is the area-weighted sum of every county of the bbox; 0.7.0
  analysed the one county of the centre of the bbox.
- ADR-057, exception (a) (private `Bdot10kProvider._get_teryt_for_point`) is closed: Kartograf finds
  the counties of an area itself; the WFS code of Hydrograf and its contract test are deleted.
- Tests run the real Kartograf with its provider classes stubbed (`tests/kartograf_offline.py`)
  and build the stores they only read with `kartograf.testing`.
- Open: Kartograf is pinned by commit until its release; the release change narrows the range to
  `>=0.8.0,<0.9` and pins the tag (REL-5.3, REL-5.6).

## Errata

**2026-10-25: the cache clean removes the old directories.** `python -m scripts.clean
--include-cache` and the `cache` target of the admin panel remove `cache/nmt/`,
`cache/bdot10k/` and `cache/soil_hsg/` too, whole, together with the large products of the
store (`nmt`, `landcover`) and `kartograf_meta.db*`. Nothing reads them since this ADR and
there is no data migration, so nobody has to delete them by hand; there is no separate flag,
and the plan and the dry run of the clean list their files with the rest of the cache. The
Consequences above say "delete them": this is how.

**2026-10-25: the plain HSG raster keeps the statistics of the whole raster.**
`hsg_statistics` of the raster of `get_hsg_from_soilgrids` has no sidecar, so it counts every
cell of the raster and the cells at the edge of the bbox count in full, as in 0.7.0; the
store would give area weights through the sidecar of a version. The counting of the soil
groups does not change by this migration. Option B (the raster as a version per bbox in the
store) stays rejected for the reason given above; area weights would be a change of the CN
calculation, decided on its own.

**2026-10-25: the pin moved to `45dedf4`.** The Context names the head `b73aad3`. Kartograf
`45dedf4` adds the public, read-only `kartograf.store_root()` (the default root, the layer that
gave it and whether the marker exists). Nothing that Hydrograf calls changed: every script
passes `root=` and `cache=` explicitly and none relies on the default store, so no call moved.
