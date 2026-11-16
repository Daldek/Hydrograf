# Runbook: the v0.5.0 data on production (migration 004, backfill, thresholds 1 and 10 km²)

For the author, on the production host, in the production checkout `~/workspace/Hydrograf`
(the system Docker daemon, `DOCKER_HOST` unset). It brings the database of production to the
v0.5.0 code: migration 004, the four new columns of `stream_catchments` for the thresholds
10000 and 100000 m² (ADR-070), the stream networks and sub-catchments of 1 km² and 10 km²
(report #27) and their tiles. **No step runs the DEM again** (section 9 says when that would be
needed). Steps 4–6 write to the production database and `data/`, `frontend/tiles/`: run them
only with the author's decision, at a quiet hour.

## 0. What was measured

The whole procedure ran on 2026-11-05 on a copy: the production database (`pg_dump`, alembic
003) restored into a separate PostGIS 16-3.4, the rasters of `data/nmt` copied, the rasters
from before the cut extracted from the backup, the code of `feature/v050-preprocessing` run
from a virtual environment on the host.

| Step | Time | Peak memory (RSS) | Result on the copy |
|---|---|---|---|
| 4a. migration 004 | 2 s | 60 MiB | 4 columns, 4 partial indexes |
| 4b. backfill, thresholds 10000 and 100000 | 26 s | 1.8 GiB | 41 277 + 4 492 rows; heads and stream heads 100%; overland not measurable: 103 + 1 (the head is a stream cell or drains into a pit) |
| 5. thresholds 1 and 10 km² | 143 s | 4.7 GiB | 479 + 49 segments and sub-catchments, 790.56 km² each, one outlet; BDOT10k: 437/479 and 49/49 real |
| 6. tiles of the two thresholds | 108 s | 0.25 GiB | 1.1 GB on `/` (`frontend/tiles`) |

Checks on the copy afterwards (the API of the branch on the copy):

- `GET /api/tiles/thresholds` → `{"streams":[10000,100000,1000000,10000000],"catchments":[…same…]}`;
  the graph loads 41 277 / 4 492 / 479 / 49 nodes, one outlet per threshold.
- Precise delineation at 51.01678 N, 15.88921 E (134.97 km², the worked example of the plan):
  `flow_path_length_km` 22.2789, `flow_path_slope_m_per_m` 0.016038 (the plan computed 0.016038
  by hand from the head elevation 614.07 m), `overland_length_km` 0.2563 at 0.163324 (the plan
  estimated ≈ 0.221 km at ≈ 0.17 from a terrain profile), `channel_slope_m_per_m` 0.014959
  (production today 0.016222); the other fields equal production.
- Report #13: threshold 100000 at 50.948543 N, 15.962945 E: `channel_slope_m_per_m` 0.008002
  (production today 13.022). Among the head sub-catchments of the threshold 100000, 231 had a
  channel slope above 90% (up to 1648%); after the change none (largest 28.7%).

## 1. Before

- The v0.5.0 commit merged to `develop` (the author) and the checkout on it; nothing else is
  needed from the branch.
- `df -h /` shows at least 3 GB free (the image about 2 GB was built before; the tiles of step 6
  take 1.1 GB on `/`). `df -h /data` for the backup and the extracted rasters (1 GB).
- `free -g`: step 5 needs 5 GB; the one-off containers carry the 8G limit of the `api` service,
  so a failure there cannot touch `hydro_api` (the OOM of 2026-10-30 came from a run inside
  `hydro_api`).

## 2. Backup

```bash
cd ~/workspace/Hydrograf
BK=/data/nmt/hydrograf-backup-$(date +%F)-v050
mkdir -p "$BK"
docker exec hydro_db pg_dump -U hydro_user -d hydro_db -Fc > "$BK/hydro_db.dump"
sha256sum "$BK/hydro_db.dump" > "$BK/SHA256SUMS"
docker exec -i hydro_db pg_restore -l < "$BK/hydro_db.dump" | grep -c "TABLE DATA"
cp frontend/tiles/tiles_metadata.json "$BK/"
git rev-parse HEAD > "$BK/git-head.txt"
docker tag hydrograf-api:latest hydrograf-api:pre-v050
```

## 3. The rasters from before the cut, and the new image

The data of `data/nmt` were cut on 2026-11-01 to the Kaczawa catchment: 62 cells of the
divide became nodata, and the heads of 19 sub-catchments of 10000 m² and 11 of 100000 m² lie
on them (ADR-070). The backfill therefore reads the rasters of the run itself, from the
backup made before the cut:

```bash
PRE=/data/nmt/hydrograf-v050/precut
mkdir -p "$PRE"
zstd -dc /data/nmt/hydrograf-backup-2026-11-01/data.tar.zst \
  | tar -xf - -C "$PRE" --strip-components=2 \
      data/nmt/dem_mosaic_02_filled.tif data/nmt/dem_mosaic_03_flowdir.tif \
      data/nmt/dem_mosaic_04_flowacc.tif data/nmt/dem_mosaic_04b_stream_distance.tif \
      data/nmt/dem_mosaic_10_subcatchments_10000.tif \
      data/nmt/dem_mosaic_10_subcatchments_100000.tif
chmod -R a+rX /data/nmt/hydrograf-v050
docker builder prune -f
docker compose build api        # hydrograf-api:latest; hydro_api keeps its old container
```

## 4. Migration and backfill

The entrypoint of the image runs `alembic upgrade head` (003 → 004) before the command.
004 only adds nullable columns and indexes, so the running API (old code) is not affected.
First a dry run, which checks every head against the rasters and writes nothing:

```bash
docker compose run --rm --no-deps -T -v /data/nmt/hydrograf-v050/precut:/precut:ro api \
  python -m scripts.backfill_flow_path_heads --input /precut/dem_mosaic.tif --dry-run
docker compose run --rm --no-deps -T -v /data/nmt/hydrograf-v050/precut:/precut:ro api \
  python -m scripts.backfill_flow_path_heads --input /precut/dem_mosaic.tif
```

Expected log: `threshold 10000 m²: 41277 rows, 41277 heads, 41174 overland segments, 41277
stream heads`, `threshold 100000 m²: 4492 rows, 4492 heads, 4491 overland segments, 4492
stream heads`. An error `… sub-catchments do not match the rasters` means the rasters are not
those of the data: stop and do not continue (nothing was written).

## 5. The thresholds of 1 km² and 10 km²

From the cut rasters of `data/nmt` (the ones the API reads), so the new networks end at the
boundary of the data; the existing thresholds stay as they are. `--save-intermediates` keeps
their Strahler and label rasters next to the others for later backfills.

```bash
docker compose run --rm --no-deps -T api \
  python -m scripts.process_dem --input /data/nmt/dem_mosaic.tif \
    --from-intermediates --thresholds 1000000,10000000 --save-intermediates
```

Expected at the end: `Stream matching (threshold=1000000): 437/479 real`, `… (threshold=10000000):
49/49 real`, `Threshold 1000000 m²: 479 segments, 479 sub-catchments`, `Threshold 10000000 m²:
49 segments, 49 sub-catchments`. From here until step 7 the old API already lists the new
thresholds in `/api/tiles/thresholds` but cannot delineate at them (404), so do steps 6 and 7
right after.

## 6. Tiles

Only the two new thresholds are built; the tiles of 10000 and 100000 m² stay, and
`tiles_metadata.json` lists all four.

```bash
df -h /
docker compose run --rm --no-deps -T api \
  python -m scripts.generate_tiles --output-dir /frontend/tiles --thresholds 1000000,10000000
```

## 7. The new API

```bash
docker compose up -d --no-deps --force-recreate api
docker logs hydro_api 2>&1 | grep -E "Threshold (10000|100000|1000000|10000000):|missing"
```

The log lists the four thresholds with 1 outlet each and no `missing flow_path_head_elev_m`
warning. Then the usual checks of a deployment (`/health`, the admin key, the public host).

## 8. Verification

```bash
docker exec hydro_db psql -U hydro_user -d hydro_db -c "SELECT version_num FROM alembic_version"
docker exec hydro_db psql -U hydro_user -d hydro_db -c "
SELECT threshold_m2, count(*) AS rows, count(flow_path_head_elev_m) AS heads,
       count(overland_length_m) AS overland, count(stream_head_elev_m) AS stream_heads,
       round(sum(area_km2)::numeric, 3) AS area_km2
FROM stream_catchments GROUP BY 1 ORDER BY 1"
docker exec hydro_db psql -U hydro_user -d hydro_db -c "
SELECT threshold_m2, count(*), count(*) FILTER (WHERE is_real_stream) AS real
FROM stream_network GROUP BY 1 ORDER BY 1"
```

Expected (the copy): `004`; rows / heads / overland / stream heads / area: 10000:
41277 / 41277 / 41174 / 41277 / 790.566; 100000: 4492 / 4492 / 4491 / 4492 / 790.566;
1000000: 479 / 479 / 479 / 479 / 790.564; 10000000: 49 / 49 / 49 / 49 / 790.564.
`stream_network`: 41277, 4492, 479 (437 real), 49 (49 real).

```bash
curl -s http://127.0.0.1:8080/api/tiles/thresholds; echo
curl -s -X POST http://127.0.0.1:8080/api/delineate-watershed -H 'Content-Type: application/json' \
  -d '{"latitude": 51.01678, "longitude": 15.88921}' | python3 -c "import json,sys; \
m=json.load(sys.stdin)['watershed']['morphometry']; print({k: m[k] for k in ('flow_path_length_km', \
'flow_path_slope_m_per_m','overland_length_km','overland_slope_m_per_m','channel_slope_m_per_m')})"
curl -s -X POST http://127.0.0.1:8080/api/delineate-watershed -H 'Content-Type: application/json' \
  -d '{"latitude": 50.948543, "longitude": 15.962945, "threshold_m2": 100000}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['watershed']['morphometry']['channel_slope_m_per_m'])"
```

Expected: the four thresholds; `{'flow_path_length_km': 22.2789, 'flow_path_slope_m_per_m':
0.016038, 'overland_length_km': 0.2563, 'overland_slope_m_per_m': 0.163324,
'channel_slope_m_per_m': 0.014959}`; `0.008002`. In the browser: „Próg akumulacji spływu”
offers 1 ha, 10 ha, 1 km² and 10 km², and a watershed shows „Najdłuższa droga spływu (od działu
wodnego)”, „Długość cieku wg BDOT10k” and the overland rows.

## 9. Rollback

The old code cannot start on a database at 004 (its entrypoint does not know the revision), so
the database goes back first, with the new image:

```bash
docker exec hydro_db psql -U hydro_user -d hydro_db -c "
DELETE FROM stream_network WHERE threshold_m2 IN (1000000, 10000000);
DELETE FROM stream_catchments WHERE threshold_m2 IN (1000000, 10000000)"
docker compose run --rm --no-deps -T api alembic downgrade 003
rm -rf frontend/tiles/streams_1000000* frontend/tiles/catchments_1000000* \
       frontend/tiles/streams_10000000* frontend/tiles/catchments_10000000*
cp "$BK/tiles_metadata.json" frontend/tiles/
git checkout --detach "$(cat "$BK/git-head.txt")"
docker tag hydrograf-api:pre-v050 hydrograf-api:latest
docker compose up -d --no-build --no-deps --force-recreate api
```

If the database itself is damaged: `docker exec -i hydro_db pg_restore -U hydro_user -d hydro_db
--clean --if-exists < "$BK/hydro_db.dump"` (check `SHA256SUMS` first), then the commands above
from `rm -rf`. The rasters written in step 5 (`data/nmt/dem_mosaic_07_stream_order_1000000.tif`,
`…_10000000.tif`, `dem_mosaic_10_subcatchments_1000000.tif`, `…_10000000.tif`) can stay.

## 10. When a full DEM run would be needed, and how to avoid the OOM

None of the above needs one. A full run of `process_dem` (or step 3 of the bootstrap) is needed
only when the saved rasters are lost, or the DEM, the BDOT10k burning or the code of the
hydrology change. It is not the way to add these columns on production: on the cut
`dem_mosaic.tif` the boundary becomes a ring of outlets (the cells of the divide drain out of the
area, so the heads of the flow paths and the areas along the divide change), every
`segment_idx` is numbered anew, and every tile must be built again (about 6 min and 1.7 GB for
the two old thresholds).

Expected cost: the run of 2026-10-30 (raster of 66.3 million cells, 42 million valid) took
43.5 min for the processing step (37 min of it the hydrology) at a peak of about 7.0 GB; the
peak scales with the cells of the raster (~103 B per cell, `docs/TECHNICAL_DEBT.md`), so the cut
raster of 58.6 million cells needs about 6 GB and 40–50 min, plus about 2.5 min for the two new
thresholds. To stay clear of the OOM:

- only in a one-off container (`docker compose run --rm --no-deps -T api …`, limit 8G), never
  with `docker compose exec` in `hydro_api`;
- rasters above ~80 million cells need the swap of the host (8G + 8G fits ~160 million) or the
  fixes F1–F7 of `docs/TECHNICAL_DEBT.md` (about 9 GB at 183 million); `--hydro-resolution`
  coarsens the grid and changes the data;
- cutting the DEM into tiles is not an option: the flow directions and accumulation need the
  whole catchment;
- with `--save-intermediates` (the bootstrap sets it) the next columns and thresholds come from
  the saved rasters again, without a full run.
