# Storage benchmark: PostGIS vs files in memory

`backend/scripts/benchmark_storage.py` answers one design question for the
planned shared GUI of the ecosystem (Archiwista and Hydrograf; plan in Nogat
`docs/plans/2026-10-20-unified-gui.md`): can the source of truth be **files**
(GeoPackage or GeoParquet) instead of PostGIS without making Hydrograf
slower?

## What it measures

1. **Export**: reads `stream_catchments`, `stream_network` and `land_cover`
   from the running Hydrograf database into one GeoPackage and into
   GeoParquet files. The database is only read, never changed.
2. **Load**: time to read each format and build in-memory spatial indexes,
   each format in a fresh process so timings and memory do not mix. This is
   the cost of switching to a new version of a layer.
3. **Queries Q1–Q8** from [`BENCHMARK_QUERIES.md`](BENCHMARK_QUERIES.md) (the
   same SQL as Hydrograf's code) and their shapely/GEOS equivalents, on the
   same random inputs, plus:
   - **Q3r / Q4r**: merging real catchments (segment sets taken from the
     `downstream_segment_idx` graph), not consecutive ids;
   - **Q9**: land cover overlay on a catchment (CN calculation,
     `core/land_cover.py`).
4. **Correctness**: whether both engines return the same results; timings
   prove nothing if they do not.
5. **Throughput** with several threads, approximating many users.
6. Writes `raport.md` (readable) and `wyniki.json` (all numbers).

## Running

On the machine with the Hydrograf database, in the backend environment:

```bash
cd backend
.venv/bin/pip install pyogrio pyarrow psutil   # the script reports what is missing
export DATABASE_URL=postgresql://hydro_user:<password>@localhost:5432/hydro_db
.venv/bin/python scripts/benchmark_storage.py --out-dir ~/storage_benchmark
```

The script accepts the `psycopg2` driver used by Hydrograf and `psycopg`
(v3), which SQLAlchemy 2.1 selects for `postgresql://` URLs.

| Option | Meaning | Default |
|---|---|---|
| `--threshold` | catchment threshold in m² | smallest in the database |
| `--samples` | number of random points | 50 |
| `--iterations` | repetitions of fast queries | 200 |
| `--merge-iterations` | repetitions of boundary merges | 30 |
| `--threads` | threads in the throughput test (`0` skips it) | 4 |
| `--skip-export` | reuse files from a previous run | off |

With data for one voivodeship the run takes a few minutes; export and merges
of large catchments take longest.

## Reading the result

The **ratio** column in the query table is the median in-memory time divided
by the PostGIS median: `0.5×` means files are twice as fast, `3.0×` three
times slower.

For the decision, look at:

1. **Correctness**: every item identical or within tolerance. Boundary merges
   may differ slightly (Chaikin smoothing is reimplemented in Python, and
   large catchments are merged with a plain union, without snapping to the
   10 m grid that PostGIS uses); the tolerance is 0.5 % of area and IoU ≥ 0.99.
2. **Q8 and Q3r/Q4r**: the response times users see.
3. **Load**: how long a user waits the first time a new layer version is used.
4. **Throughput**: how both approaches handle parallel queries.

## Limits

- One Python process is measured; a production API with several processes
  would hold one copy of the data per process.
- Map tiles (MVT/PMTiles) are not measured.
- PostGIS runs on the same machine (no network between servers), which
  favours it.
- Without `psutil`, memory growth is approximate (peak process usage).
