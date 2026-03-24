# BDOT10k Stream Matching — Plan implementacji

> **Dla agentow:** Kazdy Task realizowany przez dedykowany zespol subagentow. Workflow: Researcher → Developer → Tester. Kroki uzywaja checkbox (`- [ ]`) do sledzenia postepu.

**Cel:** Podczas preprocessingu oznaczyc kazdy segment `stream_network` jako ciek rzeczywisty (pokryty przez BDOT10k) lub sciezke splywu (algorytmiczny), aby Kerby-Kirpich mogl fizycznie uzasadniac podzial overland/channel.

**Architektura:** (1) Nowa tabela `bdot_streams` w PostGIS z geometriami SWRS/SWKN/SWRM. (2) Import w pipeline po merge hydro GPKG. (3) Spatial join (bufor 15m + overlap ratio) po wektoryzacji flow accumulation. (4) Nowa kolumna `is_real_stream` w `stream_network`. (5) Wykorzystanie w `_calculate_tc()` i `trace_main_channel()`.

**Tech Stack:** PostGIS, Alembic, Fiona/GeoPandas, pyproj, pytest

---

## Mapa plikow

| Plik | Operacja | Odpowiedzialnosc |
|------|----------|------------------|
| `backend/migrations/versions/021_add_bdot_streams.py` | Create | Migracja: tabela `bdot_streams` + kolumna `stream_network.is_real_stream` |
| `backend/core/db_bulk.py` | Modify | Nowe funkcje: `insert_bdot_streams()`, `update_stream_real_flags()` |
| `backend/scripts/process_dem.py` | Modify | Wywolanie importu BDOT i matchingu po INSERT stream_network |
| `backend/api/endpoints/hydrograph.py` | Modify | `_calculate_tc()` korzysta z `is_real_stream` do podzialu overland/channel |
| `backend/core/watershed_service.py` | Modify | `trace_main_channel()` zwraca real/total split |
| `backend/core/catchment_graph.py` | Modify | Cache `is_real_stream` per segment w grafie |
| `backend/tests/unit/test_bdot_stream_matching.py` | Create | Testy matchingu, overlap ratio, flag update |
| `backend/tests/unit/test_tc_methods.py` | Modify | Testy _calculate_tc z is_real_stream |

---

## Task 1: Migracja — tabela bdot_streams + kolumna is_real_stream

**Pliki:**
- Create: `backend/migrations/versions/021_add_bdot_streams.py`

- [ ] **1.1: Zbadaj istniejace migracje**

Przeczytaj:
- `backend/migrations/versions/002_create_core_tables.py` — schemat `stream_network`
- `backend/migrations/versions/014_add_segment_idx.py` — wzorzec dodawania kolumny
- `backend/migrations/versions/020_full_pmaxtp_range.py` — aktualna head revision

Zapisz `down_revision` z migracji 020 — potrzebne do nowej migracji.

- [ ] **1.2: Utworz migracje 021**

Plik: `backend/migrations/versions/021_add_bdot_streams.py`

```python
"""Add bdot_streams table and is_real_stream flag to stream_network.

Revision ID: 021
Revises: <revision_id_from_020>
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

# Revision identifiers
revision = "021_bdot_streams"
down_revision = "<REVISION_ID_FROM_020>"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create bdot_streams table
    op.create_table(
        "bdot_streams",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("geom", Geometry("LINESTRING", srid=2180), nullable=False),
        sa.Column(
            "layer_type",
            sa.String(10),
            nullable=False,
            comment="SWRS=river, SWKN=canal, SWRM=ditch",
        ),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("length_m", sa.Float, nullable=True),
    )
    op.create_index("idx_bdot_streams_geom", "bdot_streams", ["geom"], postgresql_using="gist")
    op.create_index("idx_bdot_streams_type", "bdot_streams", ["layer_type"])

    # 2. Add is_real_stream to stream_network
    # NULL = not yet matched (pipeline not run with BDOT), false = overland, true = real
    op.add_column(
        "stream_network",
        sa.Column("is_real_stream", sa.Boolean, nullable=True),
    )


def downgrade():
    op.drop_column("stream_network", "is_real_stream")
    op.drop_index("idx_bdot_streams_type", table_name="bdot_streams")
    op.drop_index("idx_bdot_streams_geom", table_name="bdot_streams")
    op.drop_table("bdot_streams")
```

- [ ] **1.3: Uruchom migracje**

```bash
cd backend && .venv/bin/python -m alembic upgrade head
```

Expected: tabela `bdot_streams` utworzona, kolumna `is_real_stream` dodana.

- [ ] **1.4: Zweryfikuj schemat**

```bash
cd backend && .venv/bin/python -c "
from sqlalchemy import create_engine, inspect
from core.config import get_database_url_from_config
engine = create_engine(get_database_url_from_config())
insp = inspect(engine)
print('bdot_streams columns:', [c['name'] for c in insp.get_columns('bdot_streams')])
sn_cols = [c['name'] for c in insp.get_columns('stream_network')]
print('is_real_stream in stream_network:', 'is_real_stream' in sn_cols)
"
```

- [ ] **1.5: Commit**

```bash
git add backend/migrations/versions/021_add_bdot_streams.py
git commit -m "feat(db): add bdot_streams table and is_real_stream column (migration 021)"
```

---

## Task 2: Import BDOT10k hydro do bazy

**Pliki:**
- Modify: `backend/core/db_bulk.py`
- Create: `backend/tests/unit/test_bdot_stream_matching.py`

- [ ] **2.1: Zbadaj format danych w hydro GPKG**

```bash
cd backend && .venv/bin/python -c "
import fiona
# Adjust path to actual hydro_merged.gpkg location
import glob
gpkgs = glob.glob('**/hydro_merged.gpkg', recursive=True)
print('Found:', gpkgs)
if gpkgs:
    layers = fiona.listlayers(gpkgs[0])
    print('Layers:', layers)
    for layer in layers:
        with fiona.open(gpkgs[0], layer=layer) as src:
            print(f'{layer}: {len(src)} features, schema: {list(src.schema[\"properties\"].keys())[:5]}')
"
```

Zapisz dokladna strukture (kolumny, CRS, typy geometrii) — potrzebne do INSERT.

- [ ] **2.2: Napisz testy dla insert_bdot_streams**

Plik: `backend/tests/unit/test_bdot_stream_matching.py`

```python
"""Tests for BDOT10k stream matching pipeline."""
import pytest
from unittest.mock import MagicMock, patch
from shapely.geometry import LineString


class TestInsertBdotStreams:
    """Test BDOT stream import into PostGIS."""

    def test_insert_empty_list(self):
        """Empty input should not fail."""
        from core.db_bulk import insert_bdot_streams
        db = MagicMock()
        count = insert_bdot_streams(db, [])
        assert count == 0

    def test_insert_single_stream(self):
        """Single SWRS stream should be inserted."""
        from core.db_bulk import insert_bdot_streams
        streams = [{
            "geom_wkt": "LINESTRING(400000 500000, 400100 500100)",
            "layer_type": "SWRS",
            "name": "Warta",
            "length_m": 141.4,
        }]
        db = MagicMock()
        db.connection.return_value.connection = MagicMock()
        count = insert_bdot_streams(db, streams)
        assert count == 1

    def test_rejects_invalid_layer_type(self):
        """Only SWRS/SWKN/SWRM allowed."""
        from core.db_bulk import insert_bdot_streams
        streams = [{"geom_wkt": "LINESTRING(0 0, 1 1)", "layer_type": "PTWP", "name": None, "length_m": 1.0}]
        db = MagicMock()
        count = insert_bdot_streams(db, streams)
        assert count == 0  # PTWP is polygon, skip
```

- [ ] **2.3: Implementuj insert_bdot_streams()**

Plik: `backend/core/db_bulk.py` — dodaj na koncu pliku:

```python
VALID_BDOT_LINE_TYPES = {"SWRS", "SWKN", "SWRM"}


def insert_bdot_streams(
    db_session,
    streams: list[dict],
) -> int:
    """Insert BDOT10k linear hydro features into bdot_streams table.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy session
    streams : list[dict]
        Each dict: {"geom_wkt": str, "layer_type": str, "name": str|None, "length_m": float}

    Returns
    -------
    int
        Number of inserted rows
    """
    valid = [s for s in streams if s.get("layer_type") in VALID_BDOT_LINE_TYPES]
    if not valid:
        return 0

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    try:
        cursor.execute("DELETE FROM bdot_streams")  # full replace on each run
        cursor.execute("DROP TABLE IF EXISTS temp_bdot_import")
        cursor.execute("""
            CREATE TEMP TABLE temp_bdot_import (
                wkt TEXT,
                layer_type VARCHAR(10),
                name VARCHAR(200),
                length_m DOUBLE PRECISION
            )
        """)

        import io
        buf = io.StringIO()
        for s in valid:
            name = (s.get("name") or "").replace("\t", " ").replace("\n", " ")
            buf.write(f"{s['geom_wkt']}\t{s['layer_type']}\t{name}\t{s.get('length_m', 0)}\n")
        buf.seek(0)
        cursor.copy_expert(
            "COPY temp_bdot_import (wkt, layer_type, name, length_m) FROM STDIN WITH (FORMAT text)",
            buf,
        )

        cursor.execute("""
            INSERT INTO bdot_streams (geom, layer_type, name, length_m)
            SELECT
                ST_SetSRID(ST_GeomFromText(wkt), 2180),
                layer_type,
                NULLIF(name, ''),
                length_m
            FROM temp_bdot_import
        """)
        count = cursor.rowcount
        raw_conn.commit()
        return count
    except Exception:
        raw_conn.rollback()
        raise
```

- [ ] **2.4: Napisz funkcje ladujaca GPKG do listy dict**

**UWAGA DRY:** Istniejaca `_load_stream_geometries()` w `hydrology.py` robi podobna rzecz
(czytanie GPKG, reprojekcja, decompose multi). Roznice: tamta zwraca geometrie do rasteryzacji
(clips to DEM extent, zawiera PTWP polygony), ta zwraca dict-y do INSERT (bez clip, bez PTWP,
z name/length_m). Duplikacja jest swiadoma — rozne cele (rasteryzacja vs DB import).
Developer moze rozwazyc refaktoring do wspolnej funkcji pomocniczej jesli uzna za stosowne.

Plik: `backend/core/db_bulk.py` — dodaj:

```python
def load_bdot_streams_from_gpkg(gpkg_path: str | Path) -> list[dict]:
    """Load BDOT10k linear hydro features from merged GeoPackage.

    Reads OT_SWRS_L, OT_SWKN_L, OT_SWRM_L layers.
    Reprojects to EPSG:2180 if needed. Decomposes MultiLineString.

    Returns list of dicts ready for insert_bdot_streams().
    """
    from pathlib import Path
    import fiona
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString

    gpkg_path = Path(gpkg_path)
    if not gpkg_path.exists():
        logger.warning(f"BDOT GPKG not found: {gpkg_path}")
        return []

    LAYER_MAP = {
        "OT_SWRS_L": "SWRS",
        "OT_SWKN_L": "SWKN",
        "OT_SWRM_L": "SWRM",
    }
    available = set(fiona.listlayers(str(gpkg_path)))
    results = []

    for layer_name, layer_type in LAYER_MAP.items():
        if layer_name not in available:
            continue
        gdf = gpd.read_file(str(gpkg_path), layer=layer_name)
        if gdf.crs and gdf.crs.to_epsg() != 2180:
            gdf = gdf.to_crs(epsg=2180)

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            name = row.get("NAZWA") or row.get("nazwa") or None

            # Decompose multi to single
            lines = []
            if isinstance(geom, MultiLineString):
                lines = list(geom.geoms)
            elif isinstance(geom, LineString):
                lines = [geom]

            for line in lines:
                if line.length < 1.0:  # skip degenerate
                    continue
                results.append({
                    "geom_wkt": line.wkt,
                    "layer_type": layer_type,
                    "name": name,
                    "length_m": round(line.length, 1),
                })

    return results
```

- [ ] **2.5: Uruchom testy**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_bdot_stream_matching.py -v --tb=short
```

- [ ] **2.6: Commit**

```bash
git add backend/core/db_bulk.py backend/tests/unit/test_bdot_stream_matching.py
git commit -m "feat(core): add BDOT10k stream import to PostGIS (insert_bdot_streams)"
```

---

## Task 3: Spatial matching — overlap ratio

**Pliki:**
- Modify: `backend/core/db_bulk.py`
- Modify: `backend/tests/unit/test_bdot_stream_matching.py`

- [ ] **3.1: Napisz testy dla update_stream_real_flags**

Plik: `backend/tests/unit/test_bdot_stream_matching.py` — dodaj:

```python
class TestUpdateStreamRealFlags:
    """Test spatial matching between flow acc streams and BDOT."""

    def test_segment_fully_covered_is_real(self):
        """Stream segment fully within BDOT buffer should be marked real."""
        # This test requires DB — mark as integration or mock SQL
        pass  # Placeholder — actual test with DB fixtures below

    def test_segment_not_covered_is_not_real(self):
        """Stream segment far from any BDOT should be marked not real."""
        pass

    def test_partial_coverage_threshold(self):
        """Segment with >50% overlap should be real, <50% should not."""
        pass


class TestOverlapRatioSQL:
    """Test the SQL logic for overlap ratio calculation."""

    def test_overlap_ratio_formula(self):
        """Verify overlap ratio = intersection_length / segment_length."""
        from shapely.geometry import LineString
        from shapely.ops import unary_union

        segment = LineString([(0, 0), (100, 0)])  # 100m
        bdot = LineString([(0, 0), (70, 0)])  # covers 70%
        buffer = bdot.buffer(15)

        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length
        assert 0.6 < ratio < 0.85  # ~70% covered + buffer effect
```

- [ ] **3.2: Implementuj update_stream_real_flags()**

Plik: `backend/core/db_bulk.py` — dodaj:

```python
BDOT_BUFFER_M = 15.0  # 3 * cellsize (5m DEM)
OVERLAP_THRESHOLD = 0.5  # 50% overlap required


def update_stream_real_flags(
    db_session,
    threshold_m2: int,
    buffer_m: float = BDOT_BUFFER_M,
    overlap_threshold: float = OVERLAP_THRESHOLD,
) -> dict:
    """Mark stream_network segments as real/overland based on BDOT overlap.

    For each segment with given threshold_m2, computes what fraction
    of its length intersects the BDOT buffer. Sets is_real_stream accordingly.

    Parameters
    ----------
    db_session : Session
    threshold_m2 : int
        Stream threshold to process
    buffer_m : float
        Buffer radius around BDOT streams [m]
    overlap_threshold : float
        Minimum overlap ratio to consider segment as real stream

    Returns
    -------
    dict
        {"total": int, "real": int, "overland": int}
    """
    from core.db_bulk import override_statement_timeout

    override_statement_timeout(db_session, timeout_s=600)
    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    try:
        # Step 1: Materialize unified BDOT buffer as temp table (once, not per row)
        cursor.execute("DROP TABLE IF EXISTS temp_bdot_buffer")
        cursor.execute("""
            CREATE TEMP TABLE temp_bdot_buffer AS
            SELECT ST_Buffer(ST_Collect(geom), %s) AS geom
            FROM bdot_streams
        """, (buffer_m,))
        cursor.execute("CREATE INDEX ON temp_bdot_buffer USING GIST (geom)")

        # Step 2: Single UPDATE with pre-computed buffer (all params via %s)
        cursor.execute("""
            UPDATE stream_network sn
            SET is_real_stream = (
                COALESCE(
                    ST_Length(ST_Intersection(sn.geom, bb.geom))
                    / NULLIF(ST_Length(sn.geom), 0),
                    0
                ) >= %s
            )
            FROM temp_bdot_buffer bb
            WHERE sn.threshold_m2 = %s
        """, (overlap_threshold, threshold_m2))

        raw_conn.commit()

        # Count results
        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_real_stream = true) AS real,
                COUNT(*) FILTER (WHERE is_real_stream = false) AS overland
            FROM stream_network
            WHERE threshold_m2 = %s
        """, (threshold_m2,))
        row = cursor.fetchone()
        return {"total": row[0], "real": row[1], "overland": row[2]}

    except Exception:
        raw_conn.rollback()
        raise
```

**UWAGA:** Powyzszy SQL moze byc wolny dla duzych zbiorow. Jesli tak — Developer powinien rozwazyc:
- Utworzenie materialnego bufora BDOT jako temp table
- Uzycie `ST_Subdivide` do rozbicia duzych geometrii
- Przetwarzanie batch per 1000 segmentow

Zmierz czas i zdecyduj o optymalizacji.

- [ ] **3.3: Uruchom testy**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_bdot_stream_matching.py -v --tb=short
```

- [ ] **3.4: Commit**

```bash
git add backend/core/db_bulk.py backend/tests/unit/test_bdot_stream_matching.py
git commit -m "feat(core): add spatial matching update_stream_real_flags()"
```

---

## Task 4: Integracja w pipeline (process_dem.py + bootstrap.py)

**Pliki:**
- Modify: `backend/scripts/process_dem.py`

- [ ] **4.1: Zbadaj aktualna strukture pipeline**

Przeczytaj `backend/scripts/process_dem.py` linie 519-656 — petle thresholds.
Znajdz dokladne miejsce po `insert_stream_segments()` gdzie dodac matching.

Przeczytaj `backend/scripts/bootstrap.py` linie 474-528 — krok hydro + process_dem.
Sprawdz jak `burn_streams_path` jest przekazywany.

- [ ] **4.2: Dodaj import i wywolanie w process_dem.py**

W `process_dem.py`, po petli `insert_stream_segments()` + `insert_catchments()` dla kazdego threshold:

```python
# Import na gorze pliku:
from core.db_bulk import (
    insert_bdot_streams,
    insert_catchments,
    insert_stream_segments,
    load_bdot_streams_from_gpkg,
    update_stream_real_flags,
)

# W funkcji process_dem(), PO petli thresholds, PRZED zamknieciem sesji:

# === BDOT stream matching ===
if burn_streams_path:
    logger.info("Loading BDOT streams into database...")
    bdot_data = load_bdot_streams_from_gpkg(burn_streams_path)
    if bdot_data:
        bdot_count = insert_bdot_streams(db, bdot_data)
        logger.info(f"Inserted {bdot_count} BDOT stream features")

        for threshold_m2 in threshold_list_m2:
            stats = update_stream_real_flags(db, threshold_m2)
            logger.info(
                f"Stream matching (threshold={threshold_m2}): "
                f"{stats['real']}/{stats['total']} real, "
                f"{stats['overland']} overland"
            )
    else:
        logger.warning("No BDOT hydro data found — skipping stream matching")
```

- [ ] **4.3: Uruchom testy pelnego suite**

```bash
cd backend && .venv/bin/python -m pytest tests/ --tb=short -q 2>&1 | tail -10
```

- [ ] **4.4: Commit**

```bash
git add backend/scripts/process_dem.py
git commit -m "feat(pipeline): integrate BDOT stream matching into DEM processing"
```

---

## Task 5: Wykorzystanie is_real_stream w CatchmentGraph i Tc

**Pliki:**
- Modify: `backend/core/catchment_graph.py`
- Modify: `backend/core/watershed_service.py`
- Modify: `backend/api/endpoints/hydrograph.py`
- Modify: `backend/tests/unit/test_tc_methods.py`

- [ ] **5.1: Zbadaj CatchmentGraph._load()**

Przeczytaj `backend/core/catchment_graph.py` — znajdz metode `_load()` lub `load_from_db()`.
Sprawdz jakie kolumny z `stream_network` sa ladowane do pamieci (np. `_strahler`, `_stream_length_km`).
Tu trzeba dodac `_is_real_stream` array.

- [ ] **5.2: Dodaj is_real_stream do CatchmentGraph**

**UWAGA:** `CatchmentGraph._load()` czyta z tabeli `stream_catchments`, NIE z `stream_network`.
Kolumna `is_real_stream` jest na `stream_network`. Potrzebny LEFT JOIN lub osobne zapytanie.

**Podejscie A (rekomendowane):** Osobne zapytanie po zaladowaniu grafu:
```python
# W _load(), po zaladowaniu stream_catchments:
cursor.execute("""
    SELECT sc.segment_idx, COALESCE(sn.is_real_stream, false) AS is_real
    FROM stream_catchments sc
    LEFT JOIN stream_network sn
        ON sc.threshold_m2 = sn.threshold_m2
        AND sc.segment_idx = sn.segment_idx
    WHERE sc.threshold_m2 = %s
    ORDER BY sc.segment_idx
""", (threshold_m2,))
# Zapisz jako self._is_real_stream: np.ndarray (dtype bool)
# Mapowanie segment_idx → internal_idx tez samo co dla _strahler, _area_km2
```

**UWAGA 2:** `_stream_length_km` w grafie to `stream_catchments.stream_length_km` — suma
dlugosci CALEJ sieci w sub-catchment, nie dlugosci pojedynczego segmentu.
Dla `real_channel_length_km` potrzebna jest `stream_network.length_m` per segment.

Dodaj drugie zapytanie w _load():
```python
cursor.execute("""
    SELECT segment_idx, length_m / 1000.0 AS segment_length_km
    FROM stream_network
    WHERE threshold_m2 = %s
    ORDER BY segment_idx
""", (threshold_m2,))
# Zapisz jako self._segment_length_km: np.ndarray
```

W `trace_main_channel()` dodaj:
```python
# Suma dlugosci segmentow na glownym cieku (nie sub-catchment stream_length_km!)
segment_lengths = self._segment_length_km[path_arr]
real_flags = self._is_real_stream[path_arr]

main_length_km = float(np.nansum(segment_lengths))
real_length_km = float(np.nansum(segment_lengths[real_flags]))

return {
    "main_channel_length_km": round(main_length_km, 4),
    "real_channel_length_km": round(real_length_km, 4),
    "main_channel_slope_m_per_m": main_slope,
    "main_channel_nodes": path,
}
```

- [ ] **5.3: Zaktualizuj build_morph_dict_from_graph()**

Plik: `backend/core/watershed_service.py` — w `build_morph_dict_from_graph()`:

Dodaj do morph_dict:
```python
"real_channel_length_km": main_ch.get("real_channel_length_km"),
```

- [ ] **5.4: Zaktualizuj _calculate_tc() dla kerby_kirpich**

Plik: `backend/api/endpoints/hydrograph.py` — w `_calculate_tc()`, case `kerby_kirpich`:

```python
    if method == "kerby_kirpich":
        retardance = request.tc_retardance or 0.4
        # Prefer BDOT-based real channel length if available
        real_channel = morph_dict.get("real_channel_length_km")
        channel_length = real_channel or morph_dict.get("channel_length_km") or 1.0
        channel_slope = morph_dict.get("channel_slope_m_per_m") or 0.01
        total_length = morph_dict.get("length_km") or channel_length
        overland_length = max(total_length - channel_length, 0.1)
        overland_slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        return ConcentrationTime.kerby_kirpich(
            overland_length_km=overland_length,
            overland_slope_m_per_m=overland_slope,
            retardance=retardance,
            channel_length_km=channel_length,
            channel_slope_m_per_m=channel_slope,
        )
```

- [ ] **5.5: Dodaj real_channel_length_km do MorphometricParameters schema**

Plik: `backend/models/schemas.py` — w klasie `MorphometricParameters`:

```python
    real_channel_length_km: float | None = Field(
        None, ge=0,
        description="Main channel length covered by BDOT10k real streams [km]",
    )
```

- [ ] **5.6: Zaktualizuj testy**

Plik: `backend/tests/unit/test_tc_methods.py` — dodaj:

```python
class TestKerbyKirpichWithRealChannel:
    """Test Kerby-Kirpich uses real_channel_length_km when available."""

    def test_uses_real_channel_over_total(self):
        """When real_channel_length_km is set, it should be preferred."""
        # Verify that _calculate_tc reads real_channel_length_km
        # from morph_dict and uses it for channel component
        pass  # Developer fills in with mock-based test
```

- [ ] **5.7: Uruchom pelny suite testow**

```bash
cd backend && .venv/bin/python -m pytest tests/ --tb=short -q 2>&1 | tail -10
```

- [ ] **5.8: Commit**

```bash
git add backend/core/catchment_graph.py backend/core/watershed_service.py \
       backend/api/endpoints/hydrograph.py backend/models/schemas.py \
       backend/tests/unit/test_tc_methods.py
git commit -m "feat(api): use BDOT-based real_channel_length_km in Kerby-Kirpich"
```

---

## Task 6: Walidacja na rzeczywistych danych

**Cel:** Uruchom pipeline na istniejacych danych i zweryfikuj wyniki matchingu w kilku lokalizacjach.

- [ ] **6.1: Uruchom migracje na bazie**

```bash
cd backend && .venv/bin/python -m alembic upgrade head
```

- [ ] **6.2: Uruchom preprocessing (jesli dane dostepne)**

Jesli dane NMT i BDOT sa juz w cache:
```bash
cd backend && .venv/bin/python scripts/process_dem.py \
    --config config.yaml \
    --skip-download \
    --thresholds 1000 10000
```

Jesli brak danych — uzyj testowego bboxa z PROGRESS.md:
`16.9279,52.3729,17.3825,52.5870`

- [ ] **6.3: Sprawdz wyniki matchingu w bazie**

```sql
-- Statystyki matchingu per threshold
SELECT
    threshold_m2,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE is_real_stream = true) AS real,
    COUNT(*) FILTER (WHERE is_real_stream = false) AS overland,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_real_stream = true) / COUNT(*), 1) AS pct_real
FROM stream_network
GROUP BY threshold_m2
ORDER BY threshold_m2;
```

Oczekiwane proporcje (orientacyjne):
- threshold 1000: ~30-50% real (wiele drobnych sciezek splywu)
- threshold 10000: ~60-80% real (wieksze cieki pokryte BDOT)
- threshold 100000: ~80-95% real (glowne rzeki)

- [ ] **6.4: Weryfikacja w 3 punktach**

Wybierz 3 rozne lokalizacje (mala/srednia/duza zlewnia) i sprawdz:
1. Czy `real_channel_length_km` < `channel_length_km` (zawsze)
2. Czy roznica ma sens hydrologiczny (headwater = overland, dolina = real)
3. Czy Kerby-Kirpich daje rozne Tc niz czysta metoda Kirpich

```bash
cd backend && .venv/bin/python -c "
from sqlalchemy import create_engine, text
from core.config import get_database_url_from_config
engine = create_engine(get_database_url_from_config())
with engine.connect() as conn:
    # Example: check a specific segment
    result = conn.execute(text('''
        SELECT segment_idx, length_m, strahler_order, is_real_stream
        FROM stream_network
        WHERE threshold_m2 = 1000
        ORDER BY segment_idx
        LIMIT 20
    '''))
    for row in result:
        print(row)
"
```

- [ ] **6.5: Napisz raport z walidacji**

Zaraportuj:
- Liczba segmentow real vs overland per threshold
- Proporcje — czy zgadzaja sie z intuicja?
- Problemy: false positives (overland oznaczony jako real), false negatives
- Rekomendacje: czy buffer 15m i threshold 0.5 sa optymalne?
- Czas przetwarzania matchingu (sekundy)

- [ ] **6.6: Commit**

```bash
git commit -m "docs: validation report for BDOT stream matching"
```

---

## Task 7: Dokumentacja

**Pliki:**
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md` (nowy ADR)

- [ ] **7.1: Dodaj ADR do DECISIONS.md**

```markdown
### ADR-044: BDOT10k stream matching w preprocessingu

**Status:** Accepted
**Data:** 2026-03-23

**Kontekst:** Metoda Kerby-Kirpich wymaga rozroznienia dlugosci splywu powierzchniowego (overland) od przeplywu korytowego (channel). Dotychczas cala `channel_length_km` pochodzi z wektoryzacji flow accumulation — algorytmicznej sciezki, nie faktycznego cieku.

**Decyzja:** Podczas preprocessingu importujemy geometrie ciekow z BDOT10k (SWRS/SWKN/SWRM) do tabeli `bdot_streams` i wykonujemy spatial join z `stream_network` (bufor 15m, overlap ratio >= 50%). Wynik w kolumnie `is_real_stream`.

**Konsekwencje:**
- `real_channel_length_km` dostepny w morph_dict — fizycznie uzasadniony podzial overland/channel
- Nowa tabela `bdot_streams` (~3-10k rekordow per obszar)
- Matching jednorazowy w pipeline (~sekund)
- Wymaga BDOT10k hydro (Kartograf `LandCoverManager`)
```

- [ ] **7.2: Zaktualizuj CHANGELOG.md i PROGRESS.md**

- [ ] **7.3: Commit**

```bash
git add docs/
git commit -m "docs: ADR-044 BDOT stream matching, changelog, progress"
```

---

## Kolejnosc realizacji

```
Task 1 (Migracja) → Task 2 (Import BDOT) → Task 3 (Matching SQL) → Task 4 (Pipeline) → Task 5 (API/Graph) → Task 6 (Walidacja) → Task 7 (Docs)
```

Wszystkie taski sekwencyjne — kazdy zalezy od poprzedniego.

## Zespoly subagentow

| Task | Researcher | Developer | Tester |
|------|-----------|-----------|--------|
| 1 | Schemat migracji | Alembic migration | alembic upgrade |
| 2 | Format GPKG | insert_bdot_streams | Unit testy |
| 3 | Wydajnosc SQL | update_stream_real_flags | Unit + overlap testy |
| 4 | Pipeline flow | Integracja process_dem | Full suite |
| 5 | CatchmentGraph internals | is_real_stream w grafie + API | Tc testy |
| 6 | - | Uruchomienie pipeline | Walidacja 3 punkty |
| 7 | - | ADR + CHANGELOG | - |
