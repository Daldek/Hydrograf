# Runbook: production (Kaczawa) on the integrated code of 2026-11-10

For the coordinator and the author, on the production host, with the system Docker daemon. It
moves production (`~/workspace/Hydrograf`, local `develop` at `94d7523`, alembic `004`) onto the
new `develop` (the integration `integrate/2026-11-09`, head `e14910f`) and processes the
Kaczawa data again: land cover from the BDOT10k attributes, soil group D under the wetlands,
one full DEM run with the new directions of the burned lines, new tiles. Everything is done
first on a **staging copy** (its own compose project, ports, volume and directories); the
switch then swaps the database (by renaming, inside `hydro_db`) and the data directories (by
renaming) and fast-forwards the checkout. **Nothing in sections 2–5 writes to production**;
section 6 does, only with the author's decision, at a quiet hour.

## 0. What changes, and what each change needs

| Change since `94d7523` | On production | Needs |
|---|---|---|
| Sink fixing never creates flow cycles (`3b968d0`) | the saved run has the cycles of the old fix (PROGRESS: 2,335 on the production raster, outlets understated by about 1,047 km² in total) | full `process_dem` |
| ADR-071, processing by PGW units | not used: production stays one raster | migration 005 (two empty tables) |
| ADR-072/077, the burned lines flow the way of their watercourse | about 110 km of lines, mostly `OT_SWRM_L`, digitized against the DEM (table in §1) | full `process_dem` (smoothing is on by default) |
| ADR-073, enclosed nodata filled | off: `dem.fill_enclosed_nodata` defaults to `false` and `process_dem` never sets it | nothing |
| ADR-074, land cover from the BDOT10k attributes; migration 006 drops `land_cover.cn_value` | categories change (table in §1) | migration 006, re-import of the 8 packages |
| ADR-075, CN of the soil-cover complexes; Hydrolog `4fad769` | catchment CN is computed at query time from `land_cover` × `soil_hsg` | the two tables above, the new image |
| ADR-076, bootstrap refuses uncovered NMT sheets | only bootstrap step 1, which is not run | nothing |
| ADR-078, wetlands (`OT_OIMK_A`) are group D, KU lawns are `inny` | 2.836 km² of soil becomes D inside the boundary | soil step (bootstrap step 5) with the packages; land cover re-import |
| `instance.json` (welcome dialog names the area) | file missing | `write_instance_info` |
| `bdot_streams` names `'nan'` | 3,436 of 3,812 rows | none: `process_dem` reloads `bdot_streams` from `hydro_merged.gpkg` with the fixed loader (no `UPDATE`) |
| Stream burning | production has no `config.yaml`, so `dem.stream_burning` is the default `all`; the `process_dem` CLI burns `all` as well | nothing |

Inputs of production, all reused as they are: `data/nmt/dem_mosaic.tif` (the DEM cut on
2026-11-01 to the boundary: 7,194 × 8,143 = 58.6 M cells, 31,622,576 valid, 5 m),
`data/hydro/hydro_merged.gpkg` (cut on 2026-11-01: 796 `OT_SWRS_L` + 3,016 `OT_SWRM_L` lines,
with `IDENTYFIKATORMPHP`), `data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg` (790.564 km²).
The cache of production has the Kartograf 0.7.0 layout (`cache/bdot10k/`, `cache/soil_hsg/`;
there is no `cache/kartograf/` store), which the new code does not look up: the runbook passes
the packages and the HSG raster explicitly, so **nothing is downloaded**. The BDOT10k packages
whose land cover meets the boundary are 0205, 0206, 0207, 0209, 0219, 0221, 0226 and 0262
(checked against the boundary layer by layer); the HSG raster is
`cache/soil_hsg/hsg_poland.tif` (SoilGrids 0–5 cm, 2026-10-18), the one production uses.

## 1. What was measured (2026-11-10)

Read only on the production files, and on a throwaway PostGIS 16-3.4 with the dump
`/data/nmt/hydrograf-backup-2026-11-05-v050/hydro_db.dump` (the production database before the
v0.5.0 run: alembic 003, thresholds 10000 and 100000), with the code of `e14910f` from a virtual
environment on the host. The DEM run was not repeated (section 4.9 gives the estimate).

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
  16.179380 E: 31,622,632 cells = 790.566 km² (from the run before the cut: 56 cells more than
  the valid cells of the cut DEM).
- Directions (`scripts.check_stream_directions --burning all` on the production inputs, 11 s):
  of 4,494 burned pieces (1,552 km), the rules of the smoothing reverse **211 pieces, 111.2 km**:
  7 (4.5 km) towards the MPHP mouth, 0 down their watercourse, 204 (106.7 km) by their own rise;
  957 pieces are decided by the mouth rule. The smoothing of `process_dem` counts whole lines,
  so its numbers are of the same order, not equal.

## 2. Before

- `develop` contains the integration: `git -C ~/workspace/Hydrograf fetch origin && git -C
  ~/workspace/Hydrograf merge-base --is-ancestor e14910f origin/develop && echo ok`. Staging
  and the switch use the same commit (`$NEW`, written to the backup directory in §4.1).
- Production as expected: `git -C ~/workspace/Hydrograf rev-parse --short HEAD` = `94d7523`,
  `git -C ~/workspace/Hydrograf status --short` shows only `?? .claude/`, alembic `004`
  (`docker exec hydro_db psql -U hydro_user -d hydro_db -tAc "SELECT version_num FROM
  alembic_version"`).
- Space: `df -h / /data`. `/` needs about 15 GB (staging copies 2 GB, new tiles 2.7 GB, the
  staging image 2 GB, the staging volume and the second database inside `hydro_db` about 2 GB
  each, the old `data/nmt` and `frontend/tiles` kept until §9). `/data` needs 0.3 GB.
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
the production cache or the network. Five helper files, written once:

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
```

`clip.py` repeats the cut of 2026-11-01 (the out-of-repo `clip_hydrograf.py`, phase `db`) for
the two tables the re-import fills beyond the boundary, so the land cover map layer (served
from PostGIS) still ends at the boundary.

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

### 4.9 The DEM, one raster, burned and smoothed

```bash
time run python -m scripts.process_dem --input /data/nmt/dem_mosaic.tif --output-dir /data/nmt \
  --save-intermediates --clear-existing --burn-streams /data/hydro/hydro_merged.gpkg \
  2>&1 | tee "$STG/process_dem.log"
grep -E "Monotonic smoothing|Max accumulation|Inserted .* BDOT|Stream matching|Threshold .* segments" \
  "$STG/process_dem.log"
```

The defaults are those of production's run of 2026-10-30: depth 2 m, smoothing on, burning
`all`, the four thresholds, `--waterbody-mode none`, no enclosed-nodata fill, no units. It
rewrites the rasters it saves in `$STG/data/nmt` (`dem_mosaic_01_dem` to
`_10_subcatchments_*`), `stream_network`, `stream_catchments` (with the flow path heads,
ADR-070) and `bdot_streams` (3,812 lines, names
`NULL` where BDOT10k has none). Expected log: `Monotonic smoothing: … (N against their
digitized direction: a to the mouth, 0 down their watercourse, b by their own rise; …)` with N
of the order of 200 and most of them by their own rise (§1); `Inserted 3812 BDOT stream
features`.

Estimate: 40–50 min and at most 6 GB (runbook v0.5.0 §10 for this raster of 58.6 M cells,
measured before the memory fixes F1–F7, which are merged since and lower the peak). Watch it
with `docker stats` in a second shell; an OOM kills only the one-off container.

### 4.10 Depressions and the streams overlay

```bash
run python -m scripts.generate_depressions --dem /data/nmt/dem_mosaic_01_dem.tif \
  --filled /data/nmt/dem_mosaic_02_filled.tif --clear-existing \
  --output-png /frontend/data/depressions.png --output-meta /frontend/data/depressions.json \
  2>&1 | tee "$STG/depressions.log"
run python -m scripts.generate_streams_overlay --input /data/nmt/dem_mosaic_07_stream_order.tif \
  --output /frontend/data/streams.png --meta /frontend/data/streams.json --source-crs EPSG:2180
```

The DEM itself does not change, so `dem.png`, `dem_tiles/` and the BDOT10k GeoJSON files stay.

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
python3 "$STG/probe.py" http://127.0.0.1:8083 | tee "$STG/probe-staging.txt"
```

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
| Outlet accumulation (`flowacc`) | 31,622,632 cells, 790.566 km² | at most the 31,622,576 valid cells; less by the cells of the boundary that now drain out of the cut DEM [INFERENCE: a few km² at most] | < 788 km² |
| `max_upstream_km2` per threshold | 790.566 | equal to the outlet accumulation | < 788 km² |
| Segments per threshold 10000 / 100000 / 1 km² / 10 km² | 41,277 / 4,492 / 479 / 49 | changed only where the burned lines turn (≈ 110 km) and along the boundary [INFERENCE: within a few %] | a change > 10 % |
| Outlets per threshold | 1 | 1, or a few small ones on the boundary | the Kaczawa outlet loses > 2 km² |
| Sum of `area_km2` per threshold | 790.566 / 790.566 / 790.564 / 790.564 | ≤ 790.566 | < 788 |
| `real` streams at 1 km² / 10 km² | 437 / 49 | similar | a drop > 10 % |
| Smoothing (log of §4.9) | – | ≈ 200 lines reversed, ~100 km, few by the mouth, 0 down the watercourse | none reversed |
| Land cover shares | `grunt_orny` 62.66, `las` 30.74, `łąka` 0.61 % … (§1) | `grunt_orny` 48.56, `las` 30.74, `łąka` 14.07, `zabudowa_przemysłowa` 0.76 % … (§1), total 790.564 km² | any share off by > 0.05 pp |
| Soil groups | B 99.87, C 0.13 % | B 99.50, C 0.14, D 0.36 % | D ≠ 2.836 km² ± 0.01 |
| Kamiennik 51.01678 N 15.88921 E, area | 134.97 km² | 134.97 ± 1 % | > 1 % |
| Kamiennik CN | 69.6 | 61.2 (± a few tenths from the new network) | outside 60.5–62.0 |
| Kamiennik `hsg_assumed_pct` | – (new field) | 0.0 | > 0 |
| Qmax 50.861 N 16.144 E, 1 h, p = 10 % | the probe of §4.4 (0.028 on 2026-11-04) | lower (0.015 on the copy, CN 73.4) | higher than production |
| `bdot_streams` | 3,812, 3,436 `'nan'` | 3,812, 0 `'nan'` | any `'nan'` |
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
| §4.9 DEM | 40–50 min, ≤ 6 GB | estimate of runbook v0.5.0 §10 (before F1–F7) |
| §4.10 depressions, overlay | ~2 min | not measured |
| §4.11 tiles | ~8 min, 2.7 GB | runbook v0.5.0 |
| §4.12–4.13 | ~5 min | |
| §5 comparison | 15–30 min | |
| §6 preparation | ~3 min | dump and restore of about 100 MB |
| §6 downtime | 2–4 min | stop, renames, cached build, start and graph load |

Staging from §4.1 to §5 takes about 1.5–2 h; production is unavailable only for the downtime
of §6.
