# Runbook: production (Kaczawa) on the integrated code of 2026-11-10

**Status:** executed on 2026-11-10 (the author's decision of 2026-11-09): staging 01:25–04:47 CET,
the switch of §6 on `894810c` instead of the `545f109` of §4.1 with 25 s of downtime at 05:00 CET,
§7 and §9 done; the rasters re-cut to the sub-catchments of the tables at 23:53 CET with 14 s of
downtime (the `cut.py` of §4.2 now cuts them so); the log is §11.

For the coordinator and the author, on the production host, with the system Docker daemon. It
moves production (`~/workspace/Hydrograf`, local `develop` at `94d7523`, alembic `004`) onto the
new `develop` (the integration `integrate/2026-11-09`, head `e14910f`) and processes the
Kaczawa data again: land cover from the BDOT10k attributes, soil group D under the wetlands,
one full DEM run with the new directions of the burned lines on the data from before the cut
of 2026-11-01, cut to the boundary afterwards as production was, new tiles. Everything is done
first on a **staging copy** (its own compose project, ports, volume and directories); the
switch then swaps the database (by renaming, inside `hydro_db`) and the data directories (by
renaming) and fast-forwards the checkout. **Nothing in sections 2–5 writes to production**;
section 6 does, only with the author's decision, at a quiet hour.

## 0. What changes, and what each change needs

| Change since `94d7523` | On production | Needs |
|---|---|---|
| Sink fixing never creates flow cycles (`3b968d0`) | the saved run has the cycles of the old fix (the PROGRESS before 2026-11-10, `git show 39849f0:docs/PROGRESS.md`: 2,335 on the production raster, outlets understated by about 1,047 km² in total) | full `process_dem` |
| ADR-071, processing by PGW units | not used: production stays one raster | migration 005 (two empty tables) |
| ADR-072/077, the burned lines flow the way of their watercourse | about 110 km of lines, mostly `OT_SWRM_L`, digitized against the DEM (table in §1) | full `process_dem` (smoothing is on by default) |
| ADR-073, enclosed nodata filled | off: `dem.fill_enclosed_nodata` defaults to `false` and `process_dem` never sets it | nothing |
| ADR-074, land cover from the BDOT10k attributes; migration 006 drops `land_cover.cn_value` | categories change (table in §1) | migration 006, re-import of the 8 packages |
| ADR-075, CN of the soil-cover complexes; Hydrolog `4fad769` | catchment CN is computed at query time from `land_cover` × `soil_hsg` | the two tables above, the new image |
| ADR-076, bootstrap refuses uncovered NMT sheets | only bootstrap step 1, which is not run | nothing |
| ADR-078, wetlands (`OT_OIMK_A`) are group D, KU lawns are `inny` | 2.836 km² of soil becomes D inside the boundary | soil step (bootstrap step 5) with the packages; land cover re-import |
| `instance.json` (welcome dialog names the area) | file missing | `write_instance_info` |
| `bdot_streams` names `'nan'` | 3,436 of 3,812 rows | none: `cut.py` (§4.9) loads `bdot_streams` again from the cut `hydro_merged.gpkg` with the fixed loader (no `UPDATE`) |
| Stream burning | production has no `config.yaml`, so `dem.stream_burning` is the default `all`; the `process_dem` CLI burns `all` as well | nothing |

Inputs of production, reused as they are: `data/nmt/dem_mosaic.tif` (the DEM cut on
2026-11-01 to the boundary: 7,194 × 8,143 = 58.6 M cells, 31,622,576 valid, 5 m),
`data/hydro/hydro_merged.gpkg` (cut on 2026-11-01: 796 `OT_SWRS_L` + 3,016 `OT_SWRM_L` lines,
with `IDENTYFIKATORMPHP`), `data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg` (790.564 km²).
The DEM run of §4.9 reads instead the inputs of production's run of 2026-10-30, from before
the cut, out of the backup `/data/nmt/hydrograf-backup-2026-11-01/data.tar.zst`:
`data/nmt/dem_mosaic.tif` (7,894 × 8,405 = 66.3 M cells, 42,058,347 valid) and
`data/hydro/hydro_merged.gpkg` (30,105 lines of `OT_SWRS_L`, `OT_SWKN_L` and `OT_SWRM_L`).
The cache of production has the Kartograf 0.7.0 layout (`cache/bdot10k/`, `cache/soil_hsg/`;
there is no `cache/kartograf/` store), which the new code does not look up: the runbook passes
the packages and the HSG raster explicitly, so **nothing is downloaded**. The BDOT10k packages
whose land cover meets the boundary are 0205, 0206, 0207, 0209, 0219, 0221, 0226 and 0262
(checked against the boundary layer by layer); the HSG raster is
`cache/soil_hsg/hsg_poland.tif` (SoilGrids 0–5 cm, 2026-10-18), the one production uses.

How production was cut on 2026-11-01 (`git show 39849f0:docs/PROGRESS.md`, the session of that day, the
script outside the repository `~/scratch/hydrograf-clip/clip_hydrograf.py` and its logs): the
boundary is the exterior ring of the union of the sub-catchments of the threshold 100000
upstream of segment 159, which ends at the node 51.222825 N 16.179380 E; a MultiPolygon of
two parts kept in the table `_clip_boundary` and exported to the boundary file. The script
ran in one-off containers of the API in phases. `rasters` cut all 16 rasters of `data/nmt` to
the window of the boundary, nodata outside (`geometry_mask`, cell centres), into
`data/nmt_clip`, renamed into place. `db` kept in `stream_catchments` and `stream_network` the
sub-catchments upstream of segments 159 (100000) and 870 (10000), cut `land_cover`,
`soil_hsg` and `bdot_streams` geometrically, kept the `precipitation_data` within 3.5 km of
the boundary and computed `depressions` again from the cut rasters. `vectors` cut
`hydro_merged.gpkg` and `sewer_network.gpkg`; `frontend` built the overlays, the BDOT10k
GeoJSON files and the tiles again. The downstream link of the two outlets was then set to
NULL with `psql`. A first pass that day went to the node 51.229046 N 16.198853 E (813.17 km²)
and was cut again. The thresholds of 1 and 10 km² came on 2026-11-05 from the cut rasters
(`--from-intermediates`, runbook v0.5.0 §5).

## 1. What was measured (2026-11-10)

Read only on the production files, and on a throwaway PostGIS 16-3.4 with the dump
`/data/nmt/hydrograf-backup-2026-11-05-v050/hydro_db.dump` (the production database before the
v0.5.0 run: alembic 003, thresholds 10000 and 100000), with the code of `e14910f` from a virtual
environment on the host. The DEM run itself was not repeated (§4.9 gives the estimate).

| Step | Time | Result |
|---|---|---|
| `pg_restore` into a fresh database (template0) | 26 s | 0 errors with `--exit-on-error` |
| migrations 003 → 006 | 2.6 s | `006 (head)` |
| land cover, 8 packages (`--clear-existing` on the first) | 51 s | 81,202 rows |
| soil step with wetlands | 3 s | `1233 wetlands of 8 packages, 3.89 km2 of soil made group D`; `17 poligonów (B: 1, C: 14, D: 2), mokradła 3.89 km² → D` |
| clip of `land_cover` and `soil_hsg` to the boundary | 4.4 min | `land_cover: 66497 outside deleted, 519 clipped`; `soil_hsg: 8 outside deleted, 3 clipped`; `soil_hsg.geojson: 9 features` |
| `write_instance_info` | 1.4 s | `{"name": "zlewnia Kaczawy", "area_km2": 790.6, …}` |

Expected values from these runs (the API of `e14910f` on the copy; the network there is still
the old one, so the DEM run of §4.9 can move them a little):

- Land cover inside the boundary (km², %), production today → after: `grunt_orny` 495.404
  (62.66) → 383.900 (48.56); `las` 243.025 (30.74) → 243.018 (30.74); `łąka` 4.799 (0.61) →
  111.233 (14.07); `zabudowa_mieszkaniowa` 28.797 (3.64) → 24.652 (3.12); `droga` 9.912 (1.25) →
  8.999 (1.14); `inny` 3.139 (0.40) → 7.283 (0.92); `zabudowa_przemysłowa` 0 → 5.990 (0.76);
  `woda` 5.489 (0.69) → 5.489 (0.69). The total stays 790.564 km².
- Soil groups inside the boundary: B 789.541 (99.87 %), C 1.024 (0.13 %) → B 786.640 (99.50 %),
  C 1.089 (0.14 %), D 2.836 (0.36 %).
- Kamiennik, 51.01678 N 15.88921 E: 134.968 km², CN **69.6 → 61.2**, `hsg_assumed_pct` 0.0,
  categories `las` 47.9, `łąka` 26.0, `grunt_orny` 22.6 %. An independent recomputation (the
  basin of the production D8 raster, the old category CN) gives 69.6, the production value.
  Whole Kaczawa, recomputed the same way: CN 73.1 → 67.0. All the ADRs push the CN down on
  soil B (meadow instead of arable land for `PTTR:trawiasta`, forest B 55 instead of 60, arable
  B 75 instead of 78); ADR-078 adds a little (+0.3 on h07).
- Design hydrograph, 50.861 N 16.144 E, 1 h, p = 10 %: 0.02 km², P 29.47 mm, CN 73.4,
  **Qmax 0.015 m³/s** (production recorded 0.028 on 2026-11-04 with `9e50785`; the baseline
  of §4.4 takes it again on `94d7523`).
- Outlet accumulation, production raster `dem_mosaic_04_flowacc.tif` near 51.222825 N
  16.179380 E: 31,622,632 cells = 790.566 km² (the basin in the run before the cut: 61 of its
  cells lie beyond the boundary and 5 cells of the boundary drain elsewhere, so it has 56 cells
  more than the cut DEM has valid ones).
- Directions (`scripts.check_stream_directions --burning all` on the production inputs, 11 s):
  of 4,494 burned pieces (1,552 km), the rules of the smoothing reverse **211 pieces, 111.2 km**:
  7 (4.5 km) towards the MPHP mouth, 0 down their watercourse, 204 (106.7 km) by their own rise;
  957 pieces are decided by the mouth rule. The smoothing of `process_dem` counts whole lines,
  so its numbers are of the same order, not equal.
- The run before the cut (§4.9), read only on the backup of 2026-11-01: its DEM covers the
  boundary (all 31,622,576 cells have data; the nearest nodata lies 56 m from the boundary, on
  the divide at 50.896 N 16.032 E), and cut as on 2026-11-01 it equals production's
  `dem_mosaic.tif` bit for bit. At the node a tributary of 21.73 km² joins the Kaczawa, so the
  outlet segment ends there at all four thresholds. Over the footprint of that DEM
  `check_stream_directions --burning all` reverses 250 of 6,917 burned pieces, 133.9 km: 8
  (5.7 km) to the mouth, 2 (0.4 km) down their watercourse, 240 (127.8 km) by their own rise.
- `cut.py` (§4.2) on the rasters of the run of 2026-10-30 (`/data/nmt/hydrograf-v050/precut`)
  and the database of the backup of 2026-11-01, restored into a throwaway database, in 29 s:
  it finds the outlet segments 870 (10000) and 159 (100000) of that cut, keeps 41,277 and
  4,492 sub-catchments of 790.566 km² each, deletes 15,080 rows of `stream_catchments` and
  15,011 of `stream_network` (13,733 + 1,347 and 13,664 + 1,347 in the two passes of
  2026-11-01), counts 61 basin cells beyond the boundary and 5 boundary cells draining
  elsewhere, and writes the six rasters exactly as production has them.

## 2. Before

- `develop` contains the integration: `git -C ~/workspace/Hydrograf fetch origin && git -C
  ~/workspace/Hydrograf merge-base --is-ancestor e14910f origin/develop && echo ok`. Staging
  and the switch use the same commit (`$NEW`, written to the backup directory in §4.1).
- Production as expected: `git -C ~/workspace/Hydrograf rev-parse --short HEAD` = `94d7523`,
  `git -C ~/workspace/Hydrograf status --short` shows only `?? .claude/`, alembic `004`
  (`docker exec hydro_db psql -U hydro_user -d hydro_db -tAc "SELECT version_num FROM
  alembic_version"`).
- Space: `df -h / /data`. `/` needs about 17 GB (staging copies 2 GB, the inputs and rasters
  of the DEM run before the cut 1.6 GB, new tiles 2.7 GB, the staging image 2 GB, the staging
  volume and the second database inside `hydro_db` about 2 GB each, the old `data/nmt` and
  `frontend/tiles` kept until §9). `/data` needs 0.3 GB.
- Memory: `free -g` shows at least 7 GB available before §4.9 (the DEM run in a one-off
  container with the 8G limit of the `api` service, never in a running API). Do not run it
  together with the gate or another DEM run; the Hydroni instance may stay up.
- Port 8083 free: `ss -ltn | grep -c ':8083 '` prints 0.

All commands below run in one shell with these variables:

```bash
export DOCKER_HOST=unix:///var/run/docker.sock   # the system daemon, never the rootless one
PROD=~/workspace/Hydrograf
WT=~/workspace/Hydrograf-stg1110                  # staging worktree (new develop)
STG=~/data/hydrograf-stg1110                      # staging data; same filesystem as $PROD
BK=/data/nmt/hydrograf-backup-2026-11-10
TERYT="0205 0206 0207 0209 0219 0221 0226 0262"
dcs() { docker compose -p hydrograf-stg1110 --project-directory "$WT" --env-file "$STG/stg.env" \
          -f "$WT/docker-compose.yml" -f "$WT/docker-compose.override.yml" "$@"; }
run() { dcs run --rm --no-deps -T api "$@"; }   # one-off container; its entrypoint migrates
```

Staging loads the same compose files as production (`docker-compose.yml` and the development
override that production runs: code mounted from the checkout, `--reload`).
`scripts/staging-compose.sh` does not fit: it refuses any branch but `feature/store-migration`
and its overlay mounts the shared Kartograf store and a LAN port; the instance variables of the
compose file (`HYDROGRAF_CONTAINER_PREFIX`, `HYDROGRAF_PORT`, `HYDROGRAF_*_PATH`) are enough.

## 3. Backup (production is only read)

```bash
mkdir -p "$BK" && cd "$PROD"
docker exec hydro_db pg_dump -U hydro_user -d hydro_db -Fc > "$BK/hydro_db.dump"
docker exec -i hydro_db pg_restore -l < "$BK/hydro_db.dump" | grep -c "TABLE DATA"
git rev-parse HEAD > "$BK/git-head.txt"
docker exec hydro_db psql -U hydro_user -d hydro_db -tAc "SELECT version_num FROM alembic_version" \
  > "$BK/alembic.txt"
install -m 600 .env "$BK/env"
tar -C frontend -cf - data | zstd -q > "$BK/frontend_data.tar.zst"   # with results/ (SFINCS)
cp frontend/tiles/tiles_metadata.json "$BK/"
docker tag hydrograf-api:latest hydrograf-api:pre-2026-11-10
(cd "$BK" && sha256sum hydro_db.dump frontend_data.tar.zst > SHA256SUMS)
```

The `TABLE DATA` count equals that of `/data/nmt/hydrograf-backup-2026-11-05-v050/hydro_db.dump`
(the dump is about 100 MB); `alembic.txt` is `004`. `data/nmt` and `frontend/tiles` are not
copied: the switch renames them aside, and the old `hydro_db` stays as a renamed database.

## 4. Staging

### 4.1 Worktree of the new `develop`

```bash
git -C "$PROD" fetch origin
NEW=$(git -C "$PROD" rev-parse origin/develop)
git -C "$PROD" merge-base --is-ancestor e14910f "$NEW" && echo "$NEW" > "$BK/new-head.txt"
(umask 022 && git -C "$PROD" worktree add --detach "$WT" "$NEW")
mkdir -p "$WT/frontend/data" "$WT/frontend/tiles"    # mount points nginx needs
```

`umask 022`: the API runs as uid 999 and must read the checkout (2026-11-01 lost 4 min to files
written 600).

### 4.2 Directories, settings, helper files

```bash
mkdir -p "$STG/frontend-tiles" "$STG/cache/bdot10k" "$STG/cache/soil_hsg"
(umask 077 && printf '%s\n' "POSTGRES_PASSWORD=$(openssl rand -hex 16)" \
  HYDROGRAF_CONTAINER_PREFIX=hydro_stg HYDROGRAF_PORT=8083 LOG_LEVEL=INFO \
  "HYDROGRAF_CACHE_PATH=$STG/cache" "HYDROGRAF_DATA_PATH=$STG/data" \
  "HYDROGRAF_FRONTEND_DATA_PATH=$STG/frontend-data" \
  "HYDROGRAF_FRONTEND_TILES_PATH=$STG/frontend-tiles" > "$STG/stg.env")
cp -r --preserve=mode,timestamps "$PROD/data" "$STG/data"
cp -r --preserve=mode,timestamps "$PROD/frontend/data" "$STG/frontend-data"
for t in $TERYT; do cp "$PROD/cache/bdot10k/bdot10k_teryt_$t.gpkg" "$STG/cache/bdot10k/"; done
cp "$PROD"/cache/soil_hsg/hsg_poland.tif* "$STG/cache/soil_hsg/"
chmod -R a+rwX "$STG/data" "$STG/frontend-data" "$STG/frontend-tiles" "$STG/cache"
```

The staging cache holds only the 8 packages (0.8 GB) and the HSG raster, so no step can reach
the production cache or the network. Seven helper files, written once:

```bash
cat > "$STG/compare.sql" <<'EOF'
\pset footer off
SELECT version_num AS alembic FROM alembic_version;
SELECT n.threshold_m2, n.segments, n.real, c.catchments, c.outlets, c.area_km2,
       n.max_upstream_km2
FROM (SELECT threshold_m2, count(*) AS segments,
             count(*) FILTER (WHERE is_real_stream) AS real,
             round(max(upstream_area_km2)::numeric, 3) AS max_upstream_km2
      FROM stream_network GROUP BY 1) n
JOIN (SELECT threshold_m2, count(*) AS catchments,
             count(*) FILTER (WHERE downstream_segment_idx IS NULL) AS outlets,
             round(sum(area_km2)::numeric, 3) AS area_km2
      FROM stream_catchments GROUP BY 1) c USING (threshold_m2)
ORDER BY 1;
SELECT category, round((sum(ST_Area(geom)) / 1e6)::numeric, 3) AS km2,
       round((100 * sum(ST_Area(geom)) / sum(sum(ST_Area(geom))) OVER ())::numeric, 2) AS pct
FROM land_cover GROUP BY 1 ORDER BY 2 DESC;
SELECT hsg_group, round((sum(ST_Area(geom)) / 1e6)::numeric, 3) AS km2,
       round((100 * sum(ST_Area(geom)) / sum(sum(ST_Area(geom))) OVER ())::numeric, 2) AS pct
FROM soil_hsg GROUP BY 1 ORDER BY 1;
SELECT count(*) AS bdot_streams,
       count(*) FILTER (WHERE btrim(name) IN ('', 'nan')) AS name_nan,
       count(*) FILTER (WHERE name IS NULL) AS name_null
FROM bdot_streams;
SELECT count(*) AS depressions, round(sum(volume_m3)::numeric) AS volume_m3 FROM depressions;
SELECT count(*) AS feedback, max(id) AS feedback_max_id FROM feedback;
SELECT (SELECT count(*) FROM sewer_nodes) AS sewer_nodes,
       (SELECT count(*) FROM sewer_network) AS sewer_network,
       (SELECT count(*) FROM precipitation_data) AS precipitation_points;
EOF

cat > "$STG/probe.py" <<'EOF'
"""Reference queries of the runbook 2026-11-10: python3 probe.py BASE_URL (read only)."""

import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")


def post(path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def get(path):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.load(r)


print("thresholds", json.dumps(get("/api/tiles/thresholds")))
w = post("/api/delineate-watershed", {"latitude": 51.01678, "longitude": 15.88921})["watershed"]
m, lc = w["morphometry"], w.get("land_cover_stats") or {}
print("kamiennik", json.dumps({
    "area_km2": m["area_km2"], "cn": m.get("cn"),
    "hsg_assumed_pct": lc.get("hsg_assumed_pct"),
    "flow_path_length_km": m.get("flow_path_length_km"),
    "channel_slope_m_per_m": m.get("channel_slope_m_per_m"),
    "categories": {c["category"]: round(c["percentage"], 2) for c in lc.get("categories", [])},
}, ensure_ascii=False))
h = post("/api/generate-hydrograph",
         {"latitude": 50.861, "longitude": 16.144, "duration": "1h", "probability": 10})
print("hydrograph", json.dumps({
    "area_km2": (h.get("watershed") or {}).get("morphometry", {}).get("area_km2"),
    "qmax_m3s": h["hydrograph"]["peak_discharge_m3s"],
    "cn_used": h["water_balance"]["cn_used"],
    "precip_mm": h["precipitation"]["total_mm"],
    "tc_min": h["metadata"].get("tc_min"), "uh_model": h["metadata"].get("uh_model"),
}))
EOF

cat > "$STG/flowacc.py" <<'EOF'
import rasterio
from pyproj import Transformer

x, y = Transformer.from_crs(4326, 2180, always_xy=True).transform(16.179380, 51.222825)
with rasterio.open("/data/nmt/dem_mosaic_04_flowacc.tif") as src:
    acc = src.read(1, masked=True)
    r, c = src.index(x, y)
    near = acc[max(r - 5, 0) : r + 6, max(c - 5, 0) : c + 6]
    cell_km2 = abs(src.res[0] * src.res[1]) / 1e6
with rasterio.open("/data/nmt/dem_mosaic.tif") as dem:
    valid = dem.read(1, masked=True).count()
print(f"outlet {int(near.max()):,} cells = {near.max() * cell_km2:.3f} km2; "
      f"raster max {int(acc.max()):,}; DEM valid cells {valid:,}")
EOF

cat > "$STG/units.py" <<'EOF'
"""Every sub-catchment of stream_catchments against its label raster, cell by cell."""
import os

import numpy as np
import rasterio
import sqlalchemy as sa

engine = sa.create_engine(os.environ["DATABASE_URL"])
with engine.connect() as con:
    rows = con.execute(sa.text("SELECT threshold_m2, segment_idx, area_km2 "
                               "FROM stream_catchments")).all()
for t in sorted({row[0] for row in rows}):
    with rasterio.open(f"/data/nmt/dem_mosaic_10_subcatchments_{t}.tif") as src:
        labels = src.read(1)
        cell_km2 = abs(src.res[0] * src.res[1]) / 1e6
    counts = np.bincount(labels[labels > 0].astype(np.int64))
    units = {seg: round(area / cell_km2) for th, seg, area in rows if th == t}
    differ = sum(1 for seg, n in units.items() if (counts[seg] if seg < len(counts) else 0) != n)
    orphans = len(set(np.flatnonzero(counts).tolist()) - set(units))
    print(f"threshold {t}: {len(units)} units, {differ} with other cells than the raster, "
          f"{orphans} labels without a row, {int((labels > 0).sum()):,} labelled cells")
EOF

cat > "$STG/soil.py" <<'EOF'
import logging
from pathlib import Path

import rasterio

from scripts.bootstrap import step_soil_hsg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
with rasterio.open("/data/nmt/dem_mosaic.tif") as src:
    b = src.bounds
packages = {
    t: Path(f"/cache/bdot10k/bdot10k_teryt_{t}.gpkg")
    for t in "0205 0206 0207 0209 0219 0221 0226 0262".split()
}
print(step_soil_hsg([], Path("/data"), Path("/cache"),
                    mosaic_bbox_2180=(b.left, b.bottom, b.right, b.top),
                    hsg_raster=Path("/cache/soil_hsg/hsg_poland.tif"), bdot10k=packages))
EOF

cat > "$STG/clip.py" <<'EOF'
import json
import os

import geopandas as gpd
import sqlalchemy as sa

from scripts.bootstrap import HSG_MAP_TOLERANCE_M

boundary = gpd.read_file("/data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg")
wkb = boundary.to_crs(2180).union_all().wkb
cut = "ST_Multi(ST_CollectionExtract(ST_Intersection(t.geom, b.geom), 3))"
engine = sa.create_engine(os.environ["DATABASE_URL"])
with engine.begin() as c:
    c.execute(sa.text("SET LOCAL statement_timeout = 0"))
    c.execute(sa.text("CREATE TEMP TABLE clip_b ON COMMIT DROP AS "
                      "SELECT ST_Multi(ST_GeomFromWKB(:wkb, 2180)) AS geom"), {"wkb": wkb})
    c.execute(sa.text("CREATE TEMP TABLE clip_s ON COMMIT DROP AS "
                      "SELECT ST_Subdivide(geom, 256) AS geom FROM clip_b"))
    c.execute(sa.text("CREATE INDEX ON clip_s USING gist (geom)"))
    for table, extra in (("land_cover", ""), ("soil_hsg", f", area_m2 = ST_Area({cut})")):
        n = c.execute(sa.text(f"DELETE FROM {table} t WHERE NOT EXISTS "
                              "(SELECT 1 FROM clip_s s WHERE ST_Intersects(s.geom, t.geom))")).rowcount
        m = c.execute(sa.text(f"UPDATE {table} t SET geom = {cut}{extra} "
                              "FROM clip_b b WHERE NOT ST_CoveredBy(t.geom, b.geom)")).rowcount
        e = c.execute(sa.text(f"DELETE FROM {table} WHERE ST_IsEmpty(geom)")).rowcount
        print(f"{table}: {n} outside deleted, {m} clipped, {e} empty dropped")
    rows = c.execute(sa.text(
        "SELECT hsg_group, area_m2, ST_AsGeoJSON(ST_Transform("
        "ST_SimplifyPreserveTopology(geom, :tol), 4326), 6) AS g FROM soil_hsg"),
        {"tol": HSG_MAP_TOLERANCE_M}).fetchall()
features = [{"type": "Feature", "geometry": json.loads(r.g),
             "properties": {"hsg_group": r.hsg_group, "area_m2": round(r.area_m2, 1)}}
            for r in rows]
with open("/frontend/data/soil_hsg.geojson", "w") as f:
    json.dump({"type": "FeatureCollection", "features": features}, f)
print(f"soil_hsg.geojson: {len(features)} features")
with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
    for table in ("land_cover", "soil_hsg"):
        c.execute(sa.text(f"VACUUM ANALYZE {table}"))
EOF

cat > "$STG/cut.py" <<'EOF'
"""Cut the run of §4.9 to the Kaczawa outlet: the tables by flow topology, the rasters to the
same units.

stream_network and stream_catchments keep the sub-catchments upstream of the outlet, whose
downstream link goes; the rasters of /precut/out go to /data/nmt in the window of the boundary
with nodata outside the kept sub-catchments of 10000 m2, so the tables and the rasters hold the
same cells; dem_mosaic.tif becomes the run's 01_dem with that mask; bdot_streams is loaded again
from the cut hydro_merged.gpkg. Stops before writing anything when a raster in /data/nmt did not
come from the run, the run did not read the DEM of 2026-11-01, the outlet is not found, its
catchment is more than 2 km2 off the boundary or the kept units leave the window.
"""

import os
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import sqlalchemy as sa
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window
from sqlalchemy.orm import Session

from core.db_bulk import insert_bdot_streams, load_bdot_streams_from_gpkg

SRC, DST = Path("/precut/out"), Path("/data/nmt")
BOUNDARY_KM2, STOP_KM2 = 790.564, 2.0
CLOSURE = sa.text("""
    INSERT INTO keep
    WITH RECURSIVE u(seg) AS (
      SELECT :s UNION
      SELECT sc.segment_idx FROM stream_catchments sc JOIN u
        ON sc.threshold_m2 = :t AND sc.downstream_segment_idx = u.seg)
    SELECT :t, seg FROM u""")
OUTLET = sa.text("""
    SELECT (SELECT max(upstream_area_km2) FROM stream_network n
            WHERE n.threshold_m2 = :t AND n.segment_idx = :s),
           c.downstream_segment_idx,
           (SELECT max(upstream_area_km2) FROM stream_network n
            WHERE n.threshold_m2 = :t AND n.segment_idx = c.downstream_segment_idx)
    FROM stream_catchments c WHERE c.threshold_m2 = :t AND c.segment_idx = :s""")
AREA = sa.text("SELECT sum(area_km2) FROM stream_catchments sc JOIN keep k "
               "ON k.t = sc.threshold_m2 AND k.seg = sc.segment_idx WHERE k.t = :t")


def km2(v):
    return "?" if v is None else f"{v:.3f}"


start = time.time()
boundary = gpd.read_file("/data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg")
poly = boundary.to_crs(2180).union_all()
names = sorted(p.name for p in SRC.glob("dem_mosaic_*.tif"))
stale = sorted(p.name for p in DST.glob("dem_mosaic_*.tif") if p.name not in names)
if not names or stale:
    raise SystemExit(f"stop: {len(names)} rasters in {SRC}; in {DST} not from this run: {stale}")
with rasterio.open(SRC / "dem_mosaic_04_flowacc.tif") as src:
    minx, miny, maxx, maxy = poly.bounds
    col0, row0 = (int(np.floor(v)) for v in ~src.transform * (minx, maxy))
    col1, row1 = (int(np.ceil(v)) for v in ~src.transform * (maxx, miny))
    col0, row0 = max(col0, 0), max(row0, 0)
    col1, row1 = min(col1, src.width), min(row1, src.height)
    win = Window(col0, row0, col1 - col0, row1 - row0)
    transform = src.window_transform(win)
    cell_km2 = abs(src.res[0] * src.res[1]) / 1e6
    acc = src.read(1, window=win)
inside = ~geometry_mask([poly], out_shape=acc.shape, transform=transform)
# the main stem above any junction at the edge: largest accumulation of the boundary + STOP_KM2
limit = int(inside.sum()) + STOP_KM2 / cell_km2
r, c = np.unravel_index(np.argmax(np.where(inside & (acc <= limit), acc, 0)), acc.shape)
lon, lat = Transformer.from_crs(2180, 4326, always_xy=True).transform(
    *rasterio.transform.xy(transform, r, c))
basin = int(acc[r, c])
print(f"outlet {lat:.6f} N {lon:.6f} E: {basin:,} cells = {basin * cell_km2:.3f} km2 "
      f"(boundary {int(inside.sum()):,} cells)", flush=True)
del acc

engine = sa.create_engine(os.environ["DATABASE_URL"])
with engine.begin() as con:
    con.execute(sa.text("SET LOCAL statement_timeout = 0"))
    con.execute(sa.text("CREATE TEMP TABLE keep (t int, seg int) ON COMMIT DROP"))
    outlets = {}
    for t in con.execute(sa.text("SELECT DISTINCT threshold_m2 FROM stream_catchments "
                                 "ORDER BY 1")).scalars().all():
        with rasterio.open(SRC / f"dem_mosaic_10_subcatchments_{t}.tif") as src:
            whole = src.read(1)
        labels = whole[row0:row1, col0:col1]
        seg = outlets[t] = int(labels[r, c])
        row = con.execute(OUTLET, {"t": t, "s": seg}).one_or_none() if seg > 0 else None
        if row is None:
            raise SystemExit(f"stop: no sub-catchment of {t} at the outlet (label {seg})")
        seg_up, ds, ds_up = row
        con.execute(CLOSURE, {"t": t, "s": seg})
        kept = np.array(con.execute(sa.text("SELECT seg FROM keep WHERE t = :t"),
                                    {"t": t}).scalars().all())
        area = con.execute(AREA, {"t": t}).scalar()
        in_window = np.isin(labels, kept)
        drained = int((in_window & inside).sum())
        print(f"threshold {t}: outlet segment {seg} ({km2(seg_up)} km2), downstream {ds} "
              f"({km2(ds_up)} km2); keep {len(kept)} segments, {km2(area)} km2; boundary cells "
              f"draining elsewhere {int(inside.sum()) - drained}, basin cells beyond the "
              f"boundary {basin - drained}", flush=True)
        if abs(area - BOUNDARY_KM2) > STOP_KM2:
            raise SystemExit(f"stop: the catchment of {t} is {km2(area)} km2, "
                             f"not {BOUNDARY_KM2} ± {STOP_KM2}")
        if int(np.isin(whole, kept).sum()) != int(in_window.sum()):
            raise SystemExit(f"stop: the kept units of {t} leave the window of the boundary")
        if t == 10000:
            keep_cells = in_window
        del whole, labels
    # the rasters: the window of the boundary, nodata outside the kept units (ADR-080 B5 needs
    # the label rasters and stream_catchments to hold the same cells)
    for name in names:
        with rasterio.open(SRC / name) as src:
            data = src.read(1, window=win)
            data[~keep_cells] = src.nodata
            profile = src.profile | {"width": data.shape[1], "height": data.shape[0],
                                     "transform": transform}
            size = f"{src.width}x{src.height}"
        with rasterio.open(DST / name, "w", **profile) as dst:
            dst.write(data, 1)
        print(f"{name}: {size} -> {data.shape[1]}x{data.shape[0]}, "
              f"kept {int(keep_cells.sum())} cells", flush=True)
    with rasterio.open(DST / "dem_mosaic.tif") as old, \
            rasterio.open(DST / "dem_mosaic_01_dem.tif") as new:
        dem, cut_dem, profile = new.read(1), old.read(1), old.profile
        both = keep_cells & inside
        same = old.transform == new.transform and np.array_equal(dem[both], cut_dem[both])
    print(f"dem_mosaic_01_dem.tif equals the DEM of 2026-11-01 inside the boundary: {same}")
    if not same:
        raise SystemExit("stop: the run did not read the DEM of 2026-11-01")
    with rasterio.open(DST / "dem_mosaic.tif", "w", **profile) as dst:
        dst.write(dem, 1)
    del dem, cut_dem
    con.execute(sa.text("CREATE INDEX ON keep (t, seg)"))
    n = con.execute(sa.text("DELETE FROM stream_catchments sc WHERE NOT EXISTS (SELECT 1 FROM keep "
                            "k WHERE k.t = sc.threshold_m2 AND k.seg = sc.segment_idx)")).rowcount
    m = con.execute(sa.text("DELETE FROM stream_network sn WHERE NOT EXISTS (SELECT 1 FROM keep "
                            "k WHERE k.t = sn.threshold_m2 AND k.seg = sn.segment_idx)")).rowcount
    for t, seg in outlets.items():
        con.execute(sa.text("UPDATE stream_catchments SET downstream_segment_idx = NULL "
                            "WHERE threshold_m2 = :t AND segment_idx = :s"), {"t": t, "s": seg})
    dangling = con.execute(sa.text(
        "SELECT count(*) FROM stream_catchments c WHERE downstream_segment_idx IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM stream_catchments d WHERE d.threshold_m2 = c.threshold_m2 "
        "AND d.segment_idx = c.downstream_segment_idx)")).scalar()
    print(f"stream_catchments deleted {n}, stream_network deleted {m}, outlets {outlets}, "
          f"dangling links {dangling}")
    if dangling:
        raise SystemExit("stop: links to deleted sub-catchments")
with Session(engine) as db:
    n = insert_bdot_streams(db, load_bdot_streams_from_gpkg("/data/hydro/hydro_merged.gpkg"))
print(f"bdot_streams: {n} lines of the cut hydro_merged.gpkg")
with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
    for table in ("stream_catchments", "stream_network", "bdot_streams"):
        con.execute(sa.text(f"VACUUM ANALYZE {table}"))
print(f"done in {time.time() - start:.0f} s")
EOF
```

`clip.py` repeats the cut of 2026-11-01 (the out-of-repo `clip_hydrograf.py`, phase `db`) for
the two tables the re-import fills beyond the boundary, so the land cover map layer (served
from PostGIS) still ends at the boundary.

`cut.py` repeats, for the run of §4.9, the phase `db` of that script and cuts the rasters to
the same sub-catchments: the outlet is the cell of the largest accumulation inside the boundary
and its segment at each threshold is the label there; the sub-catchments upstream of it stay,
the rest of `stream_catchments` and `stream_network` goes, and the outlet loses its downstream
link, as on 2026-11-01. Every raster the run wrote goes into `$STG/data/nmt` in the window of
the boundary with nodata outside the kept sub-catchments of 10000 m², not outside the boundary
polygon: the boundary is the divide of the run of 2026-10-30, and a new run drains other cells,
so a cut by the polygon leaves cells in the tables that the rasters lack and labels in the
rasters that the tables lack (the run of 2026-11-10: 64,321 and 6,540 cells, re-cut on
2026-11-10, §11). The network delineation's check B5 (ADR-080) and the precise mode count the
cells of the rasters, the graph counts the rows. `land_cover` and `soil_hsg` are cut to the
boundary by `clip.py`; `precipitation_data` was cut on 2026-11-01 and the run does not touch it.

### 4.3 Image and the copy of the database

```bash
dcs build api                                           # image hydrograf-stg1110-api
dcs up -d db
until docker logs hydro_stg_db 2>&1 | grep -q 'init process complete' &&
      docker exec hydro_stg_db pg_isready -U hydro_user -d hydro_db -q; do sleep 2; done
docker exec hydro_stg_db psql -U hydro_user -d postgres \
  -c "DROP DATABASE hydro_db" -c "CREATE DATABASE hydro_db TEMPLATE template0"
docker exec -i -e PGOPTIONS='-c statement_timeout=0' hydro_stg_db \
  pg_restore -U hydro_user -d hydro_db --exit-on-error < "$BK/hydro_db.dump"
```

A database from `template0` takes the PostGIS extensions and schemas of the dump without
conflicts with those the image creates; `--exit-on-error` makes any error stop the restore.
Do not run `docker builder prune` from here to §6: the switch reuses this build cache.

### 4.4 Baseline (before anything changes)

```bash
docker exec -i hydro_stg_db psql -U hydro_user -d hydro_db < "$STG/compare.sql" \
  | tee "$STG/compare-before.txt"
python3 "$STG/probe.py" http://127.0.0.1:8080 | tee "$STG/probe-production.txt"  # read-only queries
```

Expected (production today): alembic `004`; thresholds 10000 / 100000 / 1000000 / 10000000 with
41277 / 4492 / 479 / 49 segments and catchments, 1 outlet each, 790.566 / 790.566 / 790.564 /
790.564 km²; land cover and soil groups as in §1; `bdot_streams` 3812, 3436 `'nan'`;
depressions 214,907. The probe gives the Kamiennik delineation (134.97 km², CN 69.6) and the
Qmax of the design hydrograph on `94d7523`.

### 4.5 Migrations 005 and 006

```bash
run alembic current
run python - < "$STG/flowacc.py" | tee "$STG/flowacc-before.txt"
```

The entrypoint of the first one-off container runs `alembic upgrade head` (`004 -> 005`,
`005 -> 006` in its log); `alembic current` then prints `006 (head)`. The second command reads
the copied raster: `outlet 31,622,632 cells = 790.566 km2; raster max 31,622,632; DEM valid
cells 31,622,576`.

### 4.6 Land cover (ADR-074, ADR-078 lawns)

```bash
first=--clear-existing
for t in $TERYT; do
  run python -m scripts.import_landcover --input /cache/bdot10k/bdot10k_teryt_$t.gpkg $first \
    || break
  first=
done 2>&1 | tee "$STG/landcover.log"
grep -E "Records inserted" "$STG/landcover.log"
```

`--clear-existing` on the first package empties `land_cover`; together the packages insert
81,202 rows (9558, 12322, 7127, 13338, 17270, 10383, 8863, 2341).

### 4.7 Soil groups with the wetlands (ADR-078)

```bash
run python - < "$STG/soil.py" 2>&1 | tee "$STG/soil.log"
```

Expected: `HSG: 1233 wetlands of 8 packages, 3.89 km2 of soil made group D` and the line
`17 poligonów (B: 1, C: 14, D: 2), mokradła 3.89 km² → D` (the 3.89 km² are those of the
mosaic's rectangle, 2.836 km² of them inside the boundary).

### 4.8 Cut both tables to the boundary

```bash
run python - < "$STG/clip.py" 2>&1 | tee "$STG/clip.log"
```

Expected: `land_cover: 66497 outside deleted, 519 clipped, 0 empty dropped`, `soil_hsg: 8 outside
deleted, 3 clipped, 0 empty dropped`, `soil_hsg.geojson: 9 features`.

### 4.9 The DEM before the cut, burned and smoothed, then the cut

Production was built in two steps: the run of 2026-10-30 on the whole raster of the area and
the cut of 2026-11-01 (§0). A run on the cut DEM loses area along the boundary: the fill takes
every cell beside the nodata of the cut for an outlet, so hollows and flats on the divide drain
over the cut edge (the staging run of 2026-11-10 on the cut DEM lost 2.41 km² of the Kaczawa
outlet to 783 such exits). So the run reads the DEM and BDOT10k from before the cut, and
`cut.py` (§4.2) then cuts its rows as on 2026-11-01 and its rasters to the same sub-catchments.

```bash
B1=/data/nmt/hydrograf-backup-2026-11-01
(cd "$B1" && grep ' data.tar.zst$' SHA256SUMS | sha256sum -c -)
mkdir -p "$STG/precut/in" "$STG/precut/out"
zstd -dc "$B1/data.tar.zst" | tar -xf - -C "$STG/precut/in" --strip-components=2 \
  data/nmt/dem_mosaic.tif data/hydro/hydro_merged.gpkg
chmod 755 "$STG/precut" "$STG/precut/in" && chmod 644 "$STG/precut/in"/* && chmod 777 "$STG/precut/out"
runp() { dcs run --rm --no-deps -T -v "$STG/precut/in:/precut/in:ro" \
           -v "$STG/precut/out:/precut/out" api "$@"; }
time runp python -m scripts.process_dem --input /precut/in/dem_mosaic.tif --output-dir /precut/out \
  --save-intermediates --clear-existing --burn-streams /precut/in/hydro_merged.gpkg \
  2>&1 | tee "$STG/process_dem.log"
grep -E "Read raster|Monotonic smoothing|Inserted .* BDOT|Stream matching|Threshold .* segments" \
  "$STG/process_dem.log"
```

`data.tar.zst: OK`; the two files have 124,182,733 and 27,328,512 bytes (sha256 `381eb9c0…`
and `4aaec8e3…`) and lie in `$STG/precut`, outside `$STG/data`, so §6 does not move them. The
defaults are those of the run of 2026-10-30: depth 2 m, smoothing on, burning `all`,
`--waterbody-mode none`, no enclosed-nodata fill, no units; the new code adds the thresholds
of 1 and 10 km², which production took on 2026-11-05 from the cut rasters. The run writes its
rasters (`dem_mosaic_01_dem` to `_10_subcatchments_*`) into `$STG/precut/out` and replaces
`stream_network`, `stream_catchments` (with the flow path heads, ADR-070, traced before the
cut as the backfill of v0.5.0 did) and `bdot_streams` (all 30,105 lines, matched against the
segments for `is_real_stream` as on 2026-10-30). Expected log: `Read raster: 8405x7894
cells`; `Monotonic smoothing: … (N against their digitized direction: a to the mouth, b down
their watercourse, c by their own rise; …)` with N of the order of 230, a and b a few and most
by their own rise [INFERENCE: §1 gives 250 pieces, 133.9 km, over this raster; on the cut DEM
the run reversed 194 lines against 211 pieces]; `Inserted 30105 BDOT stream features`; the
segments of the whole raster (2026-10-30: 54,966 at 10000 m² and 5,883 at 100000 m²).

Estimate: about 10 min and at most 4 GB [INFERENCE: the run on the cut DEM of 58.6 M cells
took 7 min on 2026-11-10; this raster has 66.3 M, 42 M of them valid; after F1–F7 the peak is
about 50 B per cell]. Watch it with `docker stats` in a second shell; an OOM kills only the
one-off container.

```bash
time runp python - < "$STG/cut.py" 2>&1 | tee "$STG/cut.log"
```

Expected: the outlet at about 51.2228 N 16.1794 E with about 31.68 M cells (792.0 km²;
2026-10-30: 31,622,632 = 790.566 km²). The outlet is the inside cell with the largest
accumulation not above the boundary's cells plus 2 km², the Kaczawa above the node: a
tributary of 21.9 km² joins at the edge of the boundary, and on the run of 2026-11-10 its
junction lies on the boundary's cell of largest accumulation (813.96 km²; 2026-10-30: two
cells further down). For each threshold its outlet segment, a downstream segment of about
814 km², the kept segments with about 792.0 km² (within 2 km² of 790.564), a few thousand
boundary cells draining elsewhere and a few dozen thousand basin cells beyond the boundary
(2026-11-01: 5 and 61; the run of 2026-11-10: 6,540 and 64,321); nineteen lines
`dem_mosaic_….tif: 7894x8405 -> 7194x8143, kept 31680357 cells` (the run's `dem_mosaic_01_dem`
to `_10_subcatchments_*`, as many kept cells as the outlet's basin); `dem_mosaic_01_dem.tif
equals the DEM of 2026-11-01 inside the boundary: True`, after which `dem_mosaic.tif` is the
run's `01_dem` with the same mask; `dangling links 0`; `bdot_streams: 3812 lines of the cut
hydro_merged.gpkg`. About 1–2 min (65 s in the test of 2026-11-11, §11). `cut.py` stops with
`stop: …` before it writes anything when a raster in `$STG/data/nmt` did not come from the run,
the outlet has no sub-catchment, the catchment of a threshold is more than 2 km² off the
boundary or its kept units leave the window of the boundary, and before it writes the
database when `01_dem` is not the DEM of 2026-11-01: then stop and ask the author. Run again,
it gives the same result; a new `process_dem` starts the step afresh.

### 4.10 Depressions and the streams overlay

```bash
run python -m scripts.generate_depressions --dem /data/nmt/dem_mosaic_01_dem.tif \
  --filled /data/nmt/dem_mosaic_02_filled.tif --clear-existing \
  --output-png /frontend/data/depressions.png --output-meta /frontend/data/depressions.json \
  2>&1 | tee "$STG/depressions.log"
run python -m scripts.generate_streams_overlay --input /data/nmt/dem_mosaic_07_stream_order.tif \
  --output /frontend/data/streams.png --meta /frontend/data/streams.json --source-crs EPSG:2180
```

Both read the rasters cut in §4.9, as the depressions of 2026-11-01 did. The DEM itself does
not change, so `dem.png`, `dem_tiles/` and the BDOT10k GeoJSON files stay.

### 4.11 Tiles

```bash
time run python -m scripts.generate_tiles --output-dir /frontend/tiles 2>&1 | tee "$STG/tiles.log"
```

All four thresholds into the empty `$STG/frontend-tiles`: about 8 min and 2.7 GB (runbook
v0.5.0: about 6 min for 10000 and 100000, 108 s for the two coarse ones).

### 4.12 `instance.json`

```bash
run python -m scripts.write_instance_info --area-name "zlewnia Kaczawy" \
  --boundary-file /data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg
```

Expected: `Written /frontend/data/instance.json: {"name": "zlewnia Kaczawy", "area_km2": 790.6,
"boundary": "zlewnia_kaczawy_790km2_przyciecie.gpkg"}`.

### 4.13 The staging stack and the measurements after

```bash
dcs up -d
until curl -fs http://127.0.0.1:8083/health > /dev/null; do sleep 5; done
docker logs hydro_stg_api 2>&1 | grep -E "Catchment graph loaded|Threshold [0-9]+:|missing"
docker exec -i hydro_stg_db psql -U hydro_user -d hydro_db < "$STG/compare.sql" \
  | tee "$STG/compare-after.txt"
run python - < "$STG/flowacc.py" | tee "$STG/flowacc-after.txt"
run python - < "$STG/units.py" | tee "$STG/units-after.txt"
python3 "$STG/probe.py" http://127.0.0.1:8083 | tee "$STG/probe-staging.txt"
```

`flowacc.py` prints the largest cell within five cells of production's outlet: on the run of
2026-11-10 that is the junction just below the outlet (32,557,269 cells = 813.93 km²), so §5
takes the outlet from the line `outlet …` of `$STG/cut.log` (31,680,357 cells = 792.009 km²).

In a browser on `http://127.0.0.1:8083`: the welcome dialog names „zlewnia Kaczawy (ok. 791
km²)”; the layers of land cover, soil groups, streams, sub-catchments of the four thresholds
and depressions end at the boundary; „Identyfikuj” on a nameless stream says „bez nazwy”; a
watershed shows its CN and the land cover table; no JavaScript errors.

## 5. Comparison: production now against staging

Go on to §6 only when every row holds; otherwise stop and ask the author. „Stop when” bounds
are the coordinator's judgement, not measurements.

| Check | Production now (§4.4) | Expected on staging | Stop when |
|---|---|---|---|
| alembic | `004` | `006` | other |
| Outlet accumulation (`flowacc`) | 31,622,632 cells, 790.566 km² | the basin of the outlet in the run before the cut, which `cut.py` prints: about 31.68 M cells, 792.0 km² (dry run on 2026-11-10: 31,680,357 = 792.009 km²) | < 788 km² |
| `max_upstream_km2` per threshold | 790.566 | equal to the outlet accumulation, about 792.0 | < 788 km² |
| Segments per threshold 10000 / 100000 / 1 km² / 10 km² | 41,277 / 4,492 / 479 / 49 | changed only where the burned lines turn (≈ 130 km on the raster, §1) [INFERENCE: within a few %] | a change > 10 % |
| Outlets per threshold | 1 | 1 (`cut.py` keeps the catchment of the outlet and removes its downstream link) | other than 1; the Kaczawa outlet loses > 2 km² against production |
| Sum of `area_km2` per threshold | 790.566 / 790.566 / 790.564 / 790.564 | equal to the outlet accumulation at every threshold (each covers the whole basin), about 792.0 | < 788 |
| Units against the label rasters (`units.py`, §4.13) | – | at each threshold every row of `stream_catchments` holds `round(area_km2 / cell)` cells of its label in `dem_mosaic_10_subcatchments_<t>.tif`, no label lacks a row, and the labelled cells equal the outlet accumulation (31,680,357 on 2026-11-10) | any unit or label off (the rasters cut to the boundary polygon gave 108 / 43 / 29 / 14 units and 31 / 15 / 10 / 3 labels) |
| `real` streams at 1 km² / 10 km² | 437 / 49 | similar | a drop > 10 % |
| Smoothing (log of §4.9) | – | ≈ 230 lines reversed, ~130 km, a few by the mouth and down the watercourse, the rest by their own rise (§1, the whole raster) | none reversed |
| Land cover shares | `grunt_orny` 62.66, `las` 30.74, `łąka` 0.61 % … (§1) | `grunt_orny` 48.56, `las` 30.74, `łąka` 14.07, `zabudowa_przemysłowa` 0.76 % … (§1), total 790.564 km² | any share off by > 0.05 pp |
| Soil groups | B 99.87, C 0.13 % | B 99.50, C 0.14, D 0.36 % | D ≠ 2.836 km² ± 0.01 |
| Kamiennik 51.01678 N 15.88921 E, area | 134.97 km² | 134.97 ± 1 % | > 1 % |
| Kamiennik CN | 69.6 | 61.2 (± a few tenths from the new network) | outside 60.5–62.0 |
| Kamiennik `hsg_assumed_pct` | – (new field) | 0.0 | > 0 |
| Qmax 50.861 N 16.144 E, 1 h, p = 10 % | the probe of §4.4 (0.028 on 2026-11-04) | lower (0.015 on the copy, CN 73.4) | higher than production |
| `bdot_streams` | 3,812, 3,436 `'nan'` | 3,812, 0 `'nan'` (`cut.py`) | any `'nan'` |
| Depressions | 214,907 | of the same order (the filled DEM changes with the burning) | 0, or an order of magnitude off |
| API log | four thresholds, 1 outlet each | four thresholds; no `missing flow_path_head_elev_m`, no `missing outlet_flow_dist_m`, no `duplicate segment_idx` | any of them |
| `feedback`, sewer, precipitation | counts of §4.4 | equal | different |

## 6. The switch

Prepare while production keeps serving (about 3 min):

```bash
dcs stop api nginx
docker exec hydro_stg_db pg_dump -U hydro_user -d hydro_db -Fc > "$STG/hydro_db-staging.dump"
sha256sum "$STG/hydro_db-staging.dump" > "$STG/hydro_db-staging.dump.sha256"
docker exec hydro_db psql -U hydro_user -d postgres -c "CREATE DATABASE hydro_db_1110 TEMPLATE template0"
docker exec -i -e PGOPTIONS='-c statement_timeout=0' hydro_db \
  pg_restore -U hydro_user -d hydro_db_1110 --exit-on-error < "$STG/hydro_db-staging.dump"
diff -rq "$PROD/frontend/data" "$STG/frontend-data"
```

`diff` lists exactly `depressions.png`, `depressions.json`, `streams.png`, `streams.json`,
`soil_hsg.geojson` and `Only in …frontend-data: instance.json`; anything else (for example a new
result in `results/`) changed in production after §4.2 and stays production's.

Downtime starts (expected 2–4 min; the bare recreations of `hydro_api` on 2026-11-02, -03 and
-05 took 21, 9 and 10 s):

```bash
cd "$PROD"
docker compose stop api                       # before the checkout moves: the API reloads code
docker exec hydro_db psql -U hydro_user -d hydro_db_1110 -v ON_ERROR_STOP=1 \
  -c "TRUNCATE feedback, sewer_network, sewer_nodes RESTART IDENTITY"
docker exec hydro_db sh -c 'pg_dump -U hydro_user -d hydro_db --data-only --disable-triggers \
  -t feedback -t sewer_nodes -t sewer_network | psql -q -v ON_ERROR_STOP=1 -U hydro_user -d hydro_db_1110'
docker exec hydro_db psql -U hydro_user -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname IN ('hydro_db', 'hydro_db_1110') AND pid <> pg_backend_pid()" \
  -c "ALTER DATABASE hydro_db RENAME TO hydro_db_pre_2026_11_10" \
  -c "ALTER DATABASE hydro_db_1110 RENAME TO hydro_db"
mv data/nmt data/nmt.pre-2026-11-10 && mv "$STG/data/nmt" data/nmt
mv frontend/tiles frontend/tiles.pre-2026-11-10 && mv "$STG/frontend-tiles" frontend/tiles
mkdir -p "$BK/frontend-data-pre"
for f in depressions.png depressions.json streams.png streams.json soil_hsg.geojson; do
  mv "frontend/data/$f" "$BK/frontend-data-pre/" && cp "$STG/frontend-data/$f" frontend/data/
done
cp "$STG/frontend-data/instance.json" frontend/data/
(umask 022 && git merge --ff-only "$(cat "$BK/new-head.txt")")
docker compose build api                      # the cache of §4.3: about a minute
docker compose up -d --no-deps --force-recreate api
until curl -fs http://127.0.0.1:8080/health > /dev/null; do sleep 3; done
docker compose up -d --no-deps --force-recreate nginx
```

The feedback (and the empty sewer tables) of production since the copy of §3 move into the new
database while the API is stopped, so nothing users sent is lost (`pg_dump` warns about the
circular key of `sewer_nodes`; `--disable-triggers` covers it; tested on the throwaway copy).
The renames are on one filesystem and instant; the old database, `data/nmt` and
`frontend/tiles` stay beside the new ones for the rollback. `docker compose` without `-f` loads
the development override as production does today. The entrypoint's `alembic upgrade head`
finds `006` and does nothing. `nginx` is recreated once the API is healthy, because the new
compose file mounts `frontend/data` and `frontend/tiles` separately. If the build is not cached
(another prune, a changed context), it takes 5–15 min [not measured] and the downtime grows by
that.

## 7. Verification

```bash
docker exec hydro_db psql -U hydro_user -d hydro_db -c "SELECT version_num FROM alembic_version"
docker exec -i hydro_db psql -U hydro_user -d hydro_db < "$STG/compare.sql" > "$STG/compare-production.txt"
diff "$STG/compare-after.txt" "$STG/compare-production.txt"
docker logs hydro_api 2>&1 | grep -E "Catchment graph loaded|Threshold [0-9]+:|missing"
python3 "$STG/probe.py" http://127.0.0.1:8080 | diff "$STG/probe-staging.txt" -
curl -s https://hydrograf-test.debever.pl/health; echo
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/admin/dashboard
git -C "$PROD" status --short; git -C "$PROD" log --oneline -1
```

Expected: `006`; the counts equal staging except the feedback row (production's); the probe
equals staging; the log lists the four thresholds as on staging and no `missing`; `/health` 200
with the version of the new code; the admin route without a key 401; the checkout clean on
`$NEW`. In the browser on the public host: the checks of §4.13, a design hydrograph, the
SFINCS result in „Wyniki analiz”.

## 8. Rollback

The old database, the old rasters and tiles and the old image are all still there:

```bash
cd "$PROD"
docker compose stop api
docker exec hydro_db psql -U hydro_user -d hydro_db_pre_2026_11_10 -v ON_ERROR_STOP=1 \
  -c "TRUNCATE feedback RESTART IDENTITY"
docker exec hydro_db sh -c 'pg_dump -U hydro_user -d hydro_db --data-only -t feedback \
  | psql -q -v ON_ERROR_STOP=1 -U hydro_user -d hydro_db_pre_2026_11_10'
docker exec hydro_db psql -U hydro_user -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname IN ('hydro_db', 'hydro_db_pre_2026_11_10') AND pid <> pg_backend_pid()" \
  -c "ALTER DATABASE hydro_db RENAME TO hydro_db_failed_2026_11_10" \
  -c "ALTER DATABASE hydro_db_pre_2026_11_10 RENAME TO hydro_db"
mv data/nmt data/nmt.failed-2026-11-10 && mv data/nmt.pre-2026-11-10 data/nmt
mv frontend/tiles frontend/tiles.failed-2026-11-10 && mv frontend/tiles.pre-2026-11-10 frontend/tiles
cp "$BK"/frontend-data-pre/* frontend/data/ && rm frontend/data/instance.json
git checkout develop && git reset --keep "$(cat "$BK/git-head.txt")"
docker tag hydrograf-api:pre-2026-11-10 hydrograf-api:latest
docker compose up -d --no-build --no-deps --force-recreate api
until curl -fs http://127.0.0.1:8080/health > /dev/null; do sleep 3; done
docker compose up -d --no-build --no-deps --force-recreate nginx
```

The feedback sent after the switch goes back with the database. The old code starts on its own
database at `004` (its entrypoint does not migrate further). If the old database itself were
damaged: check `SHA256SUMS`, then `CREATE DATABASE hydro_db_restore TEMPLATE template0`,
`pg_restore --exit-on-error` of `$BK/hydro_db.dump` into it and rename it to `hydro_db` as above.
The `.env` is not touched by this procedure; `$BK/env` holds the copy.

## 9. After acceptance (the author's decision)

```bash
docker exec hydro_db psql -U hydro_user -d postgres -c "DROP DATABASE hydro_db_pre_2026_11_10"
rm -rf "$PROD/data/nmt.pre-2026-11-10" "$PROD/frontend/tiles.pre-2026-11-10"
dcs down -v && docker image rm hydrograf-stg1110-api
git -C "$PROD" worktree remove "$WT" && rm -rf "$STG"
```

`$BK` (dumps, env, frontend data, the replaced files, heads) stays like the earlier backups.
`docs/PROGRESS.md` records the production state (commit, alembic `006`, the values of §5).

## 10. Durations

| Part | Time | Basis |
|---|---|---|
| §3 backup | ~2 min | dump of about 100 MB, 104 MB of `frontend/data` |
| §4.1–4.2 worktree and copies | ~2 min | 1.1 GB `data`, 0.1 GB `frontend/data`, 0.8 GB packages |
| §4.3 image | 5–15 min | not measured: the builder compiles tippecanoe |
| §4.3 database copy | ~30 s | 26 s measured (§1) |
| §4.5 migrations | seconds | 2.6 s measured for 003 → 006 |
| §4.6 land cover | ~1 min | 51 s measured |
| §4.7 soil | < 1 min | 3 s measured, plus the container start |
| §4.8 clip | ~5 min | 4.4 min measured |
| §4.9 DEM before the cut, cut | ~12 min, ≤ 4 GB | extraction 2 s; the run on the cut DEM took 7 min on 2026-11-10 (58.6 M cells), this raster has 66.3 M [INFERENCE: ~10 min]; `cut.py` 29 s for six rasters (§1), here nineteen [INFERENCE: ~2 min] |
| §4.10 depressions, overlay | ~1 min | 42 s and 10 s on the staging run of 2026-11-10 |
| §4.11 tiles | ~8 min, 2.7 GB | runbook v0.5.0 |
| §4.12–4.13 | ~5 min | |
| §5 comparison | 15–30 min | |
| §6 preparation | ~3 min | dump and restore of about 100 MB |
| §6 downtime | 2–4 min | stop, renames, cached build, start and graph load |

Staging from §4.1 to §5 takes about 1.5–2 h; production is unavailable only for the downtime
of §6.

## 11. Log of the run (2026-11-10)

Times are CET. Staging: §3 at 01:25, §4.1–§4.8 by 01:34; §4.9 first ran on the cut DEM and
§5 failed on row 5 (the outlet lost 2.408 km²), so it ran again on the inputs from before the
cut (`bfdaec2`): `process_dem` 445 s, the smoothing turned 230 lines against their digitized
direction (5 to the mouth, 4 down their watercourse, 221 by their own rise); `cut.py` stopped
once on the junction cell (813.957 km²; the outlet pick was fixed in `0ac44f8`) and then cut
in 76 s to 792.009 km²; §4.10–§4.13 were done by 04:47, and all 18 rows of §5 held (`a84fa44`).
The author decided on 2026-11-09.

The switch ran `894810c`, not the `545f109` of §4.1 (the coordinator's decision).
`origin/develop` is `545f109` plus `fix/delineation-escalation`: the precomputed delineation
escalates over the thresholds of the graph, and the API reloads its graph when the network
changes. Only the runtime changes, not the data or the schema. `git merge-base --is-ancestor
545f109 894810c` held (so did `e14910f` and `94d7523`), and `$BK/new-head.txt` now holds
`894810c0209855aae87dcb671ff20f611f35faea`. Before §6 the staging worktree moved to `894810c`
(`git checkout --detach`, `dcs up -d --no-deps --force-recreate api`): graph of 46,608 nodes,
four thresholds with 1 outlet each, and the probe equal to `probe-staging.txt`. So §7
compares production with staging on the same code.

- §6 preparation, 04:56:38–04:58. Staging dump 113.8 MB, restored into `hydro_db_1110` in
  30 s with rc 0; `compare.sql` there equals `compare-after.txt`. `diff -rq` listed
  `depressions.png`, `streams.png`, `soil_hsg.geojson` and `instance.json` only.
  `depressions.json` and `streams.json` are the same on both sides (same bounds, 82.17 m,
  order 8), and nothing else changed in production.
- Downtime **05:00:08–05:00:33 CET, 25 s**. The block of §6 ran as written, from a script that
  checked the precondition of every write (`$BK/switch-2026-11-10.log`), under `umask 022`:
  the shell had `077`, with which `cp` would have written the overlays and `instance.json` as
  600, which nginx cannot read. Feedback 30 (max id 40, sequence 40) and sewer 0/0 were copied;
  the build took 11 s from the cache; the API was healthy 7 s after its start; nginx was
  recreated.
- §7, 05:00:49–05:10. Alembic `006`. `compare.sql` equals staging, the feedback row too (no
  feedback came in after §3). API log as on staging, with no `missing` and no `duplicate`. The
  probe equals staging (Kamiennik 135.3205 km², CN 61.2, `hsg_assumed_pct` 0.0; Qmax 0.015 m³/s
  at CN 73.4). `/health` returns 200 on 127.0.0.1:8080 and on the public host (`0.5.0.dev0`,
  the same string as `94d7523`). The admin route without a key returns 401. The checkout is
  at `894810c`; `git status` showed `?? .claude/` and `?? frontend/tiles.pre-2026-11-10/`
  (not ignored, removed by §9). Tiles of the four thresholds return 200 locally and on the
  public host (Cloudflare `BYPASS`/`DYNAMIC`, new `Last-Modified`).
- Browser on the public host: the welcome dialog names „zlewnia Kaczawy (ok. 791 km²)”;
  soil groups, land cover, depressions and flow lines end at the boundary; „Identyfikuj” at
  51.090606 N 16.020697 E shows „bez nazwy (rzeka)”; „Wybierz zlewnię” at Kamiennik gives
  137.03 km² (outlet 51.01917 N 15.88497 E), CN 61.2 and 8 land cover classes; the design
  hydrograph (24 h, p = 1 %, SCS) gives Qmax 151.31 m³/s; the SFINCS result loads under
  „Wyniki analiz”; no JavaScript errors.
- §9, 05:10–05:11, as written, with one exception: `frontend/tiles.pre-2026-11-10` has 5,917
  directories of uid 999 with mode 755, which `rm -rf` cannot empty as the host user. They
  were emptied in a one-off container as uid 999 (`docker run --rm --user 999:999 -v
  …:/old nginx:alpine`), then removed with `rmdir`. The logs and helper files of `$STG`
  (no data, no `stg.env`) are kept in `$BK/staging-logs.tar.zst`.

### Re-cut of the rasters to the units of the tables (2026-11-10, 23:49–23:54 CET)

The smoke of the network delineation (ADR-080, S2) found 108 of the 41,515 sub-catchments of
1 ha differing from `dem_mosaic_10_subcatchments_10000.tif`. The run of §4.9 had written both,
but `cut.py` cut them two ways: the rows by flow topology (the closure of the outlet segments),
the rasters by the boundary polygon, which is the divide of the run of 2026-10-30. So 64,321
cells of the kept units (1.608 km²) lay beyond the boundary, where the rasters had nodata (70
units whole, 38 in part), and 6,540 cells inside it (0.164 km²) kept the labels of 31 deleted
units. 72 of the 108 units form one block of 1.604 km² at 50.901 N 15.959 E: 98.4 % of it lies
in the JCWP catchment RW60000613839 „Kaczawa do Nysy Szalonej” of the aPGW geobase of
2023-09-15 (built on the MPHP divides), its lowest cell (437.9 m) opens to the Kaczawa valley,
and the run of 2026-10-30 had routed it 62.6 m uphill over a col into a flow cycle of the old
sink fix, which is why the old boundary leaves it out. Until the re-cut the precise mode
(rasters) and the precomputed mode, the hydrograph and the graph (tables) gave different areas
wherever a watershed held those cells: at the outlet cell of unit 8968 (Złotoryja,
51.1279019 N 15.9092896 E) 238.7246 against 240.3291 km²; the precise mode gave 135.3205 km² at
the probe point of §4.4, without the 64,156 cells of the block upstream (136.9244 km² since the
re-cut); 1,821 of the 41,515 watersheds of 1 ha (4.4 %) were affected, and B5 refused the
Kaczawa networks. The coordinator decided that the tables are right and the rasters follow
them.

- The run was reproduced without a database: `process_dem --dry-run --save-intermediates` on
  the inputs of §4.9 in a one-off container of `hydrograf-api:latest` (`894810c`; its
  `process_dem` differs from `545f109` in log lines only) with `--network none`, 316 s. Cut the
  way `cut.py` cut them, its 19 rasters equal production's bit for bit, and each of the 46,608
  rows holds its cell count in its labels.
- The rasters were cut again in the window of the boundary with nodata outside the kept units
  of 10000 m² (the `cut.py` of §4.2 as it stands now; `dem_mosaic.tif` is `01_dem` with the same
  mask) into `data/nmt.recut`, with the owners and modes of before (uid 999 and 644;
  `dem_mosaic.tif` uid 2001 and 666), and checked before the swap: the same 20 files and
  profiles, the cells inside both cuts bit-equal, nodata outside the kept units, every row equal
  to its labels at the four thresholds, no label without a row, `dem_mosaic.tif` equal to
  `01_dem`.
- Swap: `docker compose stop api` at 23:53:44.8, `mv data/nmt data/nmt.pre-recut && mv
  data/nmt.recut data/nmt` at 23:53:45.8, `docker compose start api` at 23:53:46.6, `/health`
  200 on 127.0.0.1:8080 at 23:53:58.6 and on the public host at 23:54:13: **14 s of downtime**.
  The API kept its address (172.18.0.4), so nginx needed nothing. Graph of 46,608 nodes, four
  thresholds with 1 outlet each. No database write, no image build.
- After: 41,515 / 4,548 / 496 / 49 rows equal to their labels, no label without a row,
  31,680,357 labelled cells at each threshold, the same as the database and as the valid cells
  of the DEM. Unit 8968 gives 240.3291 km² in the precise mode, as the graph; the precomputed
  mode escalates to unit 1022 of 10 ha (240.3559 km²), which the precise mode gives at that
  unit's outlet cell. The probe point of §4.4 gives 136.9244 km² (precise; precomputed 137.0305
  as before); the Kamiennik control (51.01538 N 15.890496 E) 37.2236 and 37.225 km² as before.
  20 random units of 1 ha (10 with cells beyond the boundary, 10 others; seed 20261110) agree to
  the cell in both modes and with the graph. Nine other outlet cells drawn lie outside their
  own stored polygon (the multi-part cleaning of `process_dem` keeps one part), so both modes
  answer 404 there, before the re-cut as after.
- `data/nmt.pre-recut` (the rasters cut to the boundary, 0.98 GB) stays for the rollback: stop
  the API, reverse the two renames, start it. Land cover, soil groups, `bdot_streams`, the
  overlays, the depressions, the DEM tiles and `instance.json` still end at the boundary, so the
  block has no land cover or soil groups (PROGRESS, Next).
- The `cut.py` of §4.2 was rewritten the same night to cut the rasters to the kept units: run on
  a throwaway copy of the tables with the reproduced rasters, it gave the rasters of 23:53 bit for
  bit in 65 s. §5 gained the row of `units.py`, which on the rasters cut to the boundary reports
  the 108 / 43 / 29 / 14 units and 31 / 15 / 10 / 3 labels.

### The review instance kaczawa2 (2026-11-11, 03:03–03:31 CET)

The runbook ran once more, beside production and only reading it, for the review copy kaczawa2
(`127.0.0.1:8082`, PROGRESS, kaczawa2 instance): the inputs of §4.9 from before the cut, the
`develop` of `c5e0bb8`, and the boundary taken from the run's kept units instead of the polygon
of 2026-11-01, so the land cover, the soil groups (ADR-079), `bdot_streams` and the presented
layers cover the 1.6 km² block above. Its steps K0–K13, their times and checks are not in the
repository: they live in `~/data/hydrograf-kaczawa2/README`, with the helpers in
`~/data/hydrograf-kaczawa2/scripts/` (`cut.py`, `compare.sql`, `probe.py`, `flowacc.py` and
`units.py` those of this runbook unchanged; `soil.py` and `clip.py` changed for the HSG raster
and the boundary; `boundary.py`, `vectors.py`, `overlays.py`, `next11.py`, `probe2.py` and
`jcwp.py` new) and one log per step in `logs/`.

### Production on kaczawa2's data (2026-11-12, 08:29–08:35 CET)

At the author's request production took kaczawa2's data instead of running K0–K13 again: the
runs are the same steps on the same inputs, and the comparison found production and kaczawa2
differing only where the rebuild was meant to change them. Equal: the 20 rasters of `data/nmt`
(sha256), `stream_network`, `stream_catchments`, `precipitation_data`, `feedback` (30 rows, max
id 40) and the empty sewer and processing tables (md5 of every row), `frontend/data/results/`.
Different: `bdot_streams`, `depressions`, `land_cover`, `soil_hsg`; in `frontend/data`
`bdot_lakes.geojson`, `bdot_streams.geojson`, `dem.json`, `dem.png`, `dem_tiles/`,
`dem_tiles.json`, `depressions.png`, `instance.json`, `soil_hsg.geojson`, `streams.png`; the
`.mbtiles` and `streams_10000/` of the tiles; `data/hydro/hydro_merged.gpkg`; the new
`data/boundary/zlewnia_kaczawy_jednostki.gpkg`. The code stayed `a1b5f86` with its image.

- Preparation 08:29–08:34, production only read, under `umask 022`: the backup of §3 in
  `/data/nmt/hydrograf-backup-2026-11-12/` (production's dump, `frontend_data.tar.zst`, `env`,
  `git-head.txt`, `tiles_metadata.json`, the old `hydro_merged.gpkg`, `SHA256SUMS`); kaczawa2's
  `hydro_db` dumped and restored as `hydro_db_1112` in `hydro_db`'s server; kaczawa2's tiles
  copied to `frontend/tiles.new`, its changed files of `frontend/data` to `frontend-data-new/`.
- Switch 08:34:29–08:35:13 from a script that checked its preconditions first (`switch-2026-11-12.log`
  in the backup): the user and empty tables of `hydro_db_1112` equal to production's, its data
  tables and both stream tables equal to kaczawa2's. **Downtime 08:34:59–08:35:13, 14.5 s:**
  `docker compose stop api`; `hydro_db` renamed `hydro_db_pre_2026_11_12` and `hydro_db_1112`
  renamed `hydro_db`; `frontend/tiles` renamed `tiles.pre-2026-11-12` and `tiles.new` into
  place; the old `frontend/data/dem_tiles` renamed `.dem_tiles.pre-2026-11-12` beside it (it
  belongs to uid 999 and cannot leave its directory), the 9 other files moved to
  `frontend-data-pre/`, the new ones copied; `hydro_merged.gpkg` and the boundary copied;
  `docker compose start api` (graph of 46,608 nodes in 1.3 s), `docker compose restart nginx`,
  which mounts the renamed tile directory again.
- Checks: `probe2.py` against 8080 gives the 8 lines of 8082 (Kaczawa outlet CN 67.8, before
  67.0; the land cover shares of the Kamiennik and Złotoryja moved by 0.1–0.2 points);
  `compare.sql` on `hydro_db` equals kaczawa2's `logs/compare-after.txt`; `next11.py` in a
  one-off container equals kaczawa2's `logs/next11.log`; the watershed of 747.92 km² at
  51.15636 N 16.07643 E at 100 000 m² has its main channel (55.36 km, Lc 48.21 km); the welcome
  dialog names „zlewnia Kaczawy (ok. 792 km²)”; the HSG layer shows the groups C of ADR-079; the
  public host answers. The HSG raster of the rebuild was copied to production's
  `cache/soil_hsg/`.
- Accepted by the author on 2026-11-12. Then removed: the database `hydro_db_pre_2026_11_12`,
  `frontend/tiles.pre-2026-11-12` and `frontend/data/.dem_tiles.pre-2026-11-12` (both partly
  uid 999, so removed by a root one-off container of `hydrograf-api:latest`), and kaczawa2
  (`./dc down -v`, its image, its worktree, `~/data/hydrograf-kaczawa2`) after its README,
  `scripts/`, `logs/`, `env.sh`, `dc`, `compose.instance.yml` and the `SHA256SUMS` of its inputs
  were copied to `/data/nmt/hydrograf-backup-2026-11-12/kaczawa2/`; the paths of
  `~/data/hydrograf-kaczawa2/` above now live there. The rollback from the backup: PROGRESS,
  Production, Backup and rollback.
