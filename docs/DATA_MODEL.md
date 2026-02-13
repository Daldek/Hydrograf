# DATA_MODEL.md - Model Danych
## System Analizy Hydrologicznej

**Wersja:** 1.2
**Data:** 2026-02-13
**Status:** Approved

---

## 1. Wprowadzenie

### 1.1 Cel Dokumentu
Ten dokument definiuje kompletny model danych systemu analizy hydrologicznej:
- Schemat bazy danych (tabele, kolumny, typy, constraints)
- Relacje między tabelami
- Indeksy i optymalizacje
- Formaty danych wejściowych i wyjściowych
- Struktury JSON/GeoJSON dla API

### 1.2 Konwencje
- **Tabele:** `snake_case`, liczba mnoga (np. `flow_network`)
- **Kolumny:** `snake_case`, liczba pojedyncza (np. `elevation`)
- **Klucze obce:** `nazwa_tabeli_id` (np. `downstream_id`)
- **Geometrie:** zawsze z SRID (Spatial Reference ID)
- **Jednostki:** zawsze w metrycznych (m, km, mm, m³/s)

---

## 2. Schemat Bazy Danych

### 2.1 Entity Relationship Diagram (ERD)

```
┌─────────────────────┐
│   flow_network      │
├─────────────────────┤
│ id (PK)             │
│ geom                │◄──────┐
│ elevation           │       │
│ flow_accumulation   │       │ downstream_id (FK)
│ slope               │       │ (rekurencyjna relacja)
│ downstream_id (FK)  ├───────┘
│ cell_area           │
│ is_stream           │
└─────────────────────┘

┌─────────────────────┐
│ precipitation_data  │
├─────────────────────┤
│ id (PK)             │
│ geom                │
│ duration            │
│ probability         │
│ precipitation_mm    │
│ source              │
│ updated_at          │
└─────────────────────┘

┌─────────────────────┐
│    land_cover       │
├─────────────────────┤
│ id (PK)             │
│ geom                │
│ category            │
│ cn_value            │
│ imperviousness      │
└─────────────────────┘

┌─────────────────────┐
│  stream_network     │
├─────────────────────┤
│ id (PK)             │
│ geom                │
│ name                │
│ length_m            │
│ strahler_order      │
│ threshold_m2        │
│ upstream_area_km2   │
│ mean_slope_percent  │
└─────────────────────┘

┌─────────────────────┐
│ stream_catchments   │
├─────────────────────┤
│ id (PK)             │
│ geom                │
│ segment_idx         │
│ threshold_m2        │
│ area_km2            │
│ mean_elevation_m    │
│ mean_slope_percent  │
│ strahler_order      │
└─────────────────────┘

┌─────────────────────┐
│    depressions      │
├─────────────────────┤
│ id (PK)             │
│ geom                │
│ volume_m3           │
│ area_m2             │
│ max_depth_m         │
│ mean_depth_m        │
└─────────────────────┘
```

---

## 3. Definicje Tabel

### 3.1 Tabela: `flow_network`

**Opis:** Graf odpływu wody - każda komórka terenu jako punkt z informacją o kierunku spływu.

**Schemat SQL:**
```sql
CREATE TABLE flow_network (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(Point, 2180) NOT NULL,
    elevation FLOAT NOT NULL,
    flow_accumulation INT NOT NULL DEFAULT 0,
    slope FLOAT CHECK (slope >= 0),
    downstream_id INT REFERENCES flow_network(id),
    cell_area FLOAT NOT NULL CHECK (cell_area > 0),
    is_stream BOOLEAN NOT NULL DEFAULT FALSE,
    strahler_order SMALLINT,                        -- migracja 003

    CONSTRAINT valid_elevation CHECK (elevation >= -50 AND elevation <= 3000),
    CONSTRAINT valid_accumulation CHECK (flow_accumulation >= 0)
);

-- Indeksy
CREATE INDEX idx_flow_geom ON flow_network USING GIST(geom);
CREATE INDEX idx_downstream ON flow_network(downstream_id);
CREATE INDEX idx_is_stream ON flow_network(is_stream) WHERE is_stream = TRUE;
CREATE INDEX idx_accumulation ON flow_network(flow_accumulation);
CREATE INDEX idx_strahler ON flow_network(strahler_order)
    WHERE strahler_order IS NOT NULL;               -- migracja 003

-- Komentarze
COMMENT ON TABLE flow_network IS 'Graf kierunków spływu wody z NMT';
COMMENT ON COLUMN flow_network.geom IS 'Lokalizacja komórki (centroid), EPSG:2180';
COMMENT ON COLUMN flow_network.elevation IS 'Wysokość n.p.m. [m]';
COMMENT ON COLUMN flow_network.flow_accumulation IS 'Liczba komórek spływających do tej komórki';
COMMENT ON COLUMN flow_network.slope IS 'Spadek terenu [%]';
COMMENT ON COLUMN flow_network.downstream_id IS 'ID komórki do której spływa woda (NULL dla outletów)';
COMMENT ON COLUMN flow_network.cell_area IS 'Powierzchnia komórki [m²]';
COMMENT ON COLUMN flow_network.is_stream IS 'Czy komórka należy do sieci rzecznej (flow_accumulation > threshold)';
COMMENT ON COLUMN flow_network.strahler_order IS 'Rząd Strahlera (NULL dla nie-cieków)';
```

**Kolumny - szczegóły:**

| Kolumna | Typ | Nullable | Default | Opis | Zakres wartości |
|---------|-----|----------|---------|------|-----------------|
| `id` | SERIAL | NO | auto | Unikalny identyfikator | 1..∞ |
| `geom` | GEOMETRY | NO | - | Punkt (centroid komórki) | EPSG:2180 |
| `elevation` | FLOAT | NO | - | Wysokość [m n.p.m.] | -50..3000 |
| `flow_accumulation` | INT | NO | 0 | Akumulacja przepływu | 0..∞ |
| `slope` | FLOAT | YES | NULL | Spadek [%] | 0..100+ |
| `downstream_id` | INT | YES | NULL | FK do flow_network(id) | NULL lub valid ID |
| `cell_area` | FLOAT | NO | - | Powierzchnia [m²] | > 0 |
| `is_stream` | BOOLEAN | NO | FALSE | Czy to ciek | TRUE/FALSE |
| `strahler_order` | SMALLINT | YES | NULL | Rząd Strahlera | 1..8+ (NULL = nie-ciek) |

**Typowe wartości:**
- Komórka NMT 1m: `cell_area = 1.0` m²
- Komórka NMT 5m: `cell_area = 25.0` m²
- Próg `is_stream`: `flow_accumulation > 100` (do konfiguracji)

**Przykładowe rekordy:**
```sql
INSERT INTO flow_network (id, geom, elevation, flow_accumulation, slope, downstream_id, cell_area, is_stream) VALUES
(1, ST_SetSRID(ST_Point(500000, 600000), 2180), 150.5, 0, 2.3, 2, 25.0, FALSE),
(2, ST_SetSRID(ST_Point(500005, 600000), 2180), 148.2, 1, 1.8, 3, 25.0, FALSE),
(3, ST_SetSRID(ST_Point(500010, 600000), 2180), 145.7, 150, 2.5, NULL, 25.0, TRUE);
```

---

### 3.2 Tabela: `precipitation_data`

**Opis:** Dane opadowe z IMGW - maksymalne opady dla różnych czasów trwania i prawdopodobieństw.

**Schemat SQL:**
```sql
CREATE TABLE precipitation_data (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(Point, 2180) NOT NULL,
    duration VARCHAR(10) NOT NULL,
    probability INT NOT NULL,
    precipitation_mm FLOAT NOT NULL CHECK (precipitation_mm >= 0),
    source VARCHAR(50) NOT NULL,  -- IMGW_PMAXTP (atlas) lub IMGW_HISTORICAL (własna analiza)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_duration CHECK (duration IN ('15min', '30min', '1h', '2h', '6h', '12h', '24h')),
    CONSTRAINT valid_probability CHECK (probability IN (1, 2, 5, 10, 20, 50)),
    CONSTRAINT unique_scenario UNIQUE (geom, duration, probability)
);

-- Indeksy
CREATE INDEX idx_precipitation_geom ON precipitation_data USING GIST(geom);
CREATE INDEX idx_precipitation_scenario ON precipitation_data(duration, probability);
CREATE INDEX idx_precipitation_duration ON precipitation_data(duration);
CREATE INDEX idx_precipitation_probability ON precipitation_data(probability);

-- Komentarze
COMMENT ON TABLE precipitation_data IS 'Maksymalne opady projektowe';
COMMENT ON COLUMN precipitation_data.duration IS 'Czas trwania opadu: 15min, 30min, 1h, 2h, 6h, 12h, 24h';
COMMENT ON COLUMN precipitation_data.probability IS 'Prawdopodobieństwo przewyższenia [%]: 1, 2, 5, 10, 20, 50';
COMMENT ON COLUMN precipitation_data.precipitation_mm IS 'Wysokość opadu [mm]';
```

**Kolumny - szczegóły:**

| Kolumna | Typ | Nullable | Default | Opis | Dozwolone wartości |
|---------|-----|----------|---------|------|-------------------|
| `id` | SERIAL | NO | auto | Unikalny identyfikator | 1..∞ |
| `geom` | GEOMETRY | NO | - | Punkt siatki precipitation | EPSG:2180 |
| `duration` | VARCHAR(10) | NO | - | Czas trwania | '15min', '30min', '1h', '2h', '6h', '12h', '24h' |
| `probability` | INT | NO | - | Prawdopodobieństwo [%] | 1, 2, 5, 10, 20, 50 |
| `precipitation_mm` | FLOAT | NO | - | Opad [mm] | ≥ 0 |
| `source` | VARCHAR(50) | NO | - | Źródło danych | IMGW_PMAXTP (atlas), IMGW_HISTORICAL (własna analiza) |
| `updated_at` | TIMESTAMP | YES | NOW() | Data aktualizacji | timestamp |

**Przykładowe rekordy:**
```sql
INSERT INTO precipitation_data (geom, duration, probability, precipitation_mm, source) VALUES
(ST_SetSRID(ST_Point(520000, 610000), 2180), '1h', 10, 38.5, 'IMGW_PMAXTP'),
(ST_SetSRID(ST_Point(520000, 610000), 2180), '24h', 10, 65.2, 'IMGW_PMAXTP'),
(ST_SetSRID(ST_Point(525000, 615000), 2180), '1h', 10, 40.1, 'IMGW_PMAXTP');
```

**Liczba rekordów:**
- Scenariusze: 7 czasów × 6 prawdopodobieństw = 42 na punkt
- Total: ~42,000 - 210,000 rekordów

---

### 3.3 Tabela: `land_cover`

**Opis:** Pokrycie terenu z BDOT10k z przypisanymi wartościami Curve Number.

**Schemat SQL:**
```sql
CREATE TABLE land_cover (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(MultiPolygon, 2180) NOT NULL,
    category VARCHAR(50) NOT NULL,
    cn_value INT NOT NULL CHECK (cn_value BETWEEN 0 AND 100),
    imperviousness FLOAT CHECK (imperviousness BETWEEN 0 AND 1),
    bdot_class VARCHAR(20),
    
    CONSTRAINT valid_category CHECK (category IN (
        'las', 'łąka', 'grunt_orny', 'zabudowa_mieszkaniowa', 
        'zabudowa_przemysłowa', 'droga', 'woda', 'inny'
    ))
);

-- Indeksy
CREATE INDEX idx_landcover_geom ON land_cover USING GIST(geom);
CREATE INDEX idx_category ON land_cover(category);
CREATE INDEX idx_cn_value ON land_cover(cn_value);

-- Komentarze
COMMENT ON TABLE land_cover IS 'Pokrycie terenu z BDOT10k z wartościami CN';
COMMENT ON COLUMN land_cover.category IS 'Kategoria uproszczona: las, łąka, grunt_orny, etc.';
COMMENT ON COLUMN land_cover.cn_value IS 'Curve Number (0-100) dla warunków AMC-II';
COMMENT ON COLUMN land_cover.imperviousness IS 'Stopień uszczelnienia (0=przepuszczalne, 1=nieprzepuszczalne)';
COMMENT ON COLUMN land_cover.bdot_class IS 'Oryginalna klasa z BDOT10k (np. PTLZ, PTGN)';
```

**Mapowanie CN (warunki AMC-II):**

| Kategoria | CN | Imperviousness | Opis |
|-----------|-----|----------------|------|
| `las` | 60 | 0.0 | Lasy liściaste/iglaste |
| `łąka` | 70 | 0.0 | Łąki, pastwiska |
| `grunt_orny` | 78 | 0.1 | Pola uprawne |
| `zabudowa_mieszkaniowa` | 85 | 0.5 | Zabudowa niska (domy jednorodzinne) |
| `zabudowa_przemysłowa` | 92 | 0.8 | Zabudowa zwarta, przemysł |
| `droga` | 98 | 0.95 | Drogi asfaltowe, betonowe |
| `woda` | 100 | 1.0 | Wody powierzchniowe |
| `inny` | 75 | 0.2 | Inne tereny |

**Przykładowe rekordy:**
```sql
INSERT INTO land_cover (geom, category, cn_value, imperviousness, bdot_class) VALUES
(ST_SetSRID(ST_GeomFromText('MULTIPOLYGON(((500000 600000, 500100 600000, 500100 600100, 500000 600100, 500000 600000)))'), 2180),
 'las', 60, 0.0, 'PTLZ'),
(ST_SetSRID(ST_GeomFromText('MULTIPOLYGON(((500100 600000, 500200 600000, 500200 600100, 500100 600100, 500100 600000)))'), 2180),
 'grunt_orny', 78, 0.1, 'PTGN');
```

---

### 3.4 Tabela: `stream_network`

**Opis:** Sieć rzeczna - osie cieków jako linie.

**Schemat SQL:**
```sql
CREATE TABLE stream_network (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(LineString, 2180) NOT NULL,
    name VARCHAR(100),
    length_m FLOAT CHECK (length_m > 0),
    strahler_order INT CHECK (strahler_order > 0),
    source VARCHAR(50) DEFAULT 'MPHP',
    upstream_area_km2 FLOAT,                        -- migracja 003
    mean_slope_percent FLOAT,                       -- migracja 003
    threshold_m2 INT NOT NULL DEFAULT 100,          -- migracja 005

    CONSTRAINT valid_strahler CHECK (strahler_order IS NULL OR strahler_order > 0)
);

-- Indeksy
CREATE INDEX idx_stream_geom ON stream_network USING GIST(geom);
CREATE INDEX idx_stream_name ON stream_network(name);
CREATE INDEX idx_strahler_order ON stream_network(strahler_order);
CREATE UNIQUE INDEX idx_stream_unique ON stream_network
    (COALESCE(name, ''), ST_GeoHash(ST_Transform(geom, 4326), 12), threshold_m2);
                                                    -- migracja 010: dodano threshold_m2
CREATE INDEX idx_stream_threshold ON stream_network
    (threshold_m2, strahler_order);                 -- migracja 005
CREATE INDEX idx_stream_upstream_area ON stream_network
    (upstream_area_km2);                            -- migracja 006
CREATE INDEX idx_stream_dem_derived_geom ON stream_network
    USING GIST(geom) WHERE source = 'DEM_DERIVED'; -- migracja 009

-- Komentarze
COMMENT ON TABLE stream_network IS 'Sieć rzeczna - osie cieków';
COMMENT ON COLUMN stream_network.name IS 'Nazwa cieku (może być NULL dla bezimiennych)';
COMMENT ON COLUMN stream_network.length_m IS 'Długość odcinka [m]';
COMMENT ON COLUMN stream_network.strahler_order IS 'Rząd Strahlera (hierarchia sieci)';
```

**Kolumny - szczegóły:**

| Kolumna | Typ | Nullable | Default | Opis |
|---------|-----|----------|---------|------|
| `id` | SERIAL | NO | auto | Unikalny identyfikator |
| `geom` | GEOMETRY | NO | - | Linia reprezentująca odcinek cieku |
| `name` | VARCHAR(100) | YES | NULL | Nazwa cieku |
| `length_m` | FLOAT | YES | NULL | Długość [m] (obliczana: ST_Length(geom)) |
| `strahler_order` | INT | YES | NULL | Rząd Strahlera (1=źródłowy, wyższe=większe) |
| `source` | VARCHAR(50) | YES | 'MPHP' | Źródło danych ('MPHP' lub 'DEM_DERIVED') |
| `upstream_area_km2` | FLOAT | YES | NULL | Powierzchnia zlewni na końcu segmentu [km²] |
| `mean_slope_percent` | FLOAT | YES | NULL | Średni spadek wzdłuż segmentu [%] |

**Przykładowe rekordy:**
```sql
INSERT INTO stream_network (geom, name, length_m, strahler_order) VALUES
(ST_SetSRID(ST_GeomFromText('LINESTRING(500000 600000, 500050 600010, 500100 600005)'), 2180),
 'Ciek Bezimienni', 111.8, 1),
(ST_SetSRID(ST_GeomFromText('LINESTRING(500100 600005, 500200 600020, 500300 600015)'), 2180),
 'Rzeka Przykładowa', 223.6, 2);
```

---

### 3.5 Tabela: `stream_catchments`

**Opis:** Zlewnie czastkowe — poligony odpowiadajace segmentom sieci cieków (migracja 007, rozszerzenie migracja 012).

**Schemat SQL:**
```sql
CREATE TABLE stream_catchments (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(MULTIPOLYGON, 2180) NOT NULL,
    segment_idx INTEGER NOT NULL,
    threshold_m2 INTEGER NOT NULL,
    area_km2 DOUBLE PRECISION NOT NULL,
    mean_elevation_m DOUBLE PRECISION,
    mean_slope_percent DOUBLE PRECISION,
    strahler_order INTEGER,
    -- Nowe kolumny (migracja 012):
    downstream_segment_idx INTEGER,              -- graf: do którego segmentu spływa
    elevation_min_m DOUBLE PRECISION,            -- min wys. w zlewni
    elevation_max_m DOUBLE PRECISION,            -- max wys. w zlewni
    perimeter_km DOUBLE PRECISION,               -- obwód poligonu [km]
    stream_length_km DOUBLE PRECISION,           -- długość cieku w zlewni [km]
    elev_histogram JSONB                         -- histogram wysokości (stały interwał 1m)
);

-- Indeksy
CREATE INDEX idx_catchments_geom ON stream_catchments USING GIST(geom);
CREATE INDEX idx_catchments_threshold ON stream_catchments(threshold_m2, strahler_order);
CREATE INDEX idx_catchments_area ON stream_catchments(area_km2);
CREATE INDEX idx_catchments_downstream                   -- migracja 012
    ON stream_catchments(threshold_m2, downstream_segment_idx);
```

**Nowe kolumny (migracja 012) — szczegóły:**

| Kolumna | Typ | Nullable | Opis |
|---------|-----|----------|------|
| `downstream_segment_idx` | INTEGER | YES | Segment do którego spływa (NULL = outlet) |
| `elevation_min_m` | DOUBLE PRECISION | YES | Minimalna wysokość w zlewni [m n.p.m.] |
| `elevation_max_m` | DOUBLE PRECISION | YES | Maksymalna wysokość w zlewni [m n.p.m.] |
| `perimeter_km` | DOUBLE PRECISION | YES | Obwód poligonu zlewni [km] |
| `stream_length_km` | DOUBLE PRECISION | YES | Długość cieku w zlewni [km] |
| `elev_histogram` | JSONB | YES | Histogram wysokości: `{"base_m": 120, "interval_m": 1, "counts": [45, 82, ...]}` |

**Format `elev_histogram`:** stały interwał 1m, klucze: `base_m` (dolna granica najniższego binu), `interval_m` (zawsze 1), `counts` (tablica liczności per bin). Mergowalny — histogramy na wspólnej osi bezwzględnej, agregacja = suma z offset.

---

### 3.6 Tabela: `depressions`

**Opis:** Zaglbienia terenowe (blue spots) — poligony z metrykami (migracja 004, indeksy migracja 008).

**Schemat SQL:**
```sql
CREATE TABLE depressions (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(POLYGON, 2180) NOT NULL,
    volume_m3 FLOAT NOT NULL,
    area_m2 FLOAT NOT NULL,
    max_depth_m FLOAT NOT NULL,
    mean_depth_m FLOAT
);

-- Indeksy
CREATE INDEX idx_depressions_geom ON depressions USING GIST(geom);
CREATE INDEX idx_depressions_volume ON depressions(volume_m3);      -- migracja 008
CREATE INDEX idx_depressions_area ON depressions(area_m2);          -- migracja 008
CREATE INDEX idx_depressions_max_depth ON depressions(max_depth_m); -- migracja 008
```

---

## 4. Relacje i Constraints

### 4.1 Klucze Obce (Foreign Keys)

**flow_network.downstream_id → flow_network.id**
- Relacja rekurencyjna (self-referencing)
- Reprezentuje kierunek spływu wody
- NULL dla komórek wylotowych (outletów do większego cieku lub morza)

```sql
ALTER TABLE flow_network 
ADD CONSTRAINT fk_downstream 
FOREIGN KEY (downstream_id) 
REFERENCES flow_network(id) 
ON DELETE SET NULL;
```

### 4.2 Unique Constraints

**precipitation_data: unique (geom, duration, probability)**
- Zapobiega duplikatom dla tej samej lokalizacji i scenariusza

**stream_network: unique (name, geom)**
- Zapobiega duplikatom tego samego odcinka cieku

### 4.3 Check Constraints

**Walidacja wartości fizycznych:**
```sql
-- Wysokość w rozsądnym zakresie
CHECK (elevation >= -50 AND elevation <= 3000)

-- CN między 0 a 100
CHECK (cn_value BETWEEN 0 AND 100)

-- Powierzchnia dodatnia
CHECK (cell_area > 0)

-- Opad nieujemny
CHECK (precipitation_mm >= 0)
```

---

## 5. Indeksy i Optymalizacje

### 5.1 Indeksy Przestrzenne (GIST)

**Dla wszystkich kolumn geometrycznych:**
```sql
CREATE INDEX idx_flow_geom ON flow_network USING GIST(geom);
CREATE INDEX idx_precipitation_geom ON precipitation_data USING GIST(geom);
CREATE INDEX idx_landcover_geom ON land_cover USING GIST(geom);
CREATE INDEX idx_stream_geom ON stream_network USING GIST(geom);
CREATE INDEX idx_catchments_geom ON stream_catchments USING GIST(geom);
CREATE INDEX idx_depressions_geom ON depressions USING GIST(geom);
```

**Dlaczego GIST:**
- Umożliwia szybkie spatial queries (ST_Intersects, ST_Distance, ST_Contains)
- Kluczowe dla wydajności systemu (< 10s dla delineacji)

---

### 5.2 Indeksy B-tree

**Dla często filtrowanych kolumn:**
```sql
-- flow_network
CREATE INDEX idx_downstream ON flow_network(downstream_id);
CREATE INDEX idx_is_stream ON flow_network(is_stream) WHERE is_stream = TRUE; -- partial index
CREATE INDEX idx_accumulation ON flow_network(flow_accumulation);

-- precipitation
CREATE INDEX idx_precipitation_scenario ON precipitation_data(duration, probability); -- composite
CREATE INDEX idx_precipitation_duration ON precipitation_data(duration);
CREATE INDEX idx_precipitation_probability ON precipitation_data(probability);

-- land_cover
CREATE INDEX idx_category ON land_cover(category);

-- stream_network
CREATE INDEX idx_stream_name ON stream_network(name);
CREATE INDEX idx_strahler_order ON stream_network(strahler_order);
```

---

### 5.3 Strategie Optymalizacji

**Partial Index dla is_stream:**
- Tylko komórki cieku (is_stream = TRUE) w indeksie
- Redukuje rozmiar indeksu o ~99%
- Większość queries filtruje WHERE is_stream = TRUE

**Composite Index dla scenariuszy:**
- `(duration, probability)` razem jako jeden indeks
- Szybsze queries WHERE duration = X AND probability = Y

**Vacuum i Analyze:**
```sql
-- Okresowe utrzymanie (cron job: weekly)
VACUUM ANALYZE flow_network;
VACUUM ANALYZE precipitation_data;
VACUUM ANALYZE land_cover;
VACUUM ANALYZE stream_network;
```

---

## 6. Formaty Danych API

### 6.1 Request: Delineate Watershed

**Endpoint:** `POST /api/delineate-watershed`

```json
{
  "latitude": 52.123456,
  "longitude": 21.123456
}
```

**Pydantic Schema:**
```python
from pydantic import BaseModel, Field

class DelineateRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
```

---

### 6.2 Response: Delineate Watershed

```json
{
  "watershed": {
    "boundary_geojson": {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [21.123, 52.123],
            [21.125, 52.123],
            [21.125, 52.125],
            [21.123, 52.125],
            [21.123, 52.123]
          ]
        ]
      },
      "properties": {
        "area_km2": 45.3
      }
    },
    "outlet": {
      "latitude": 52.123456,
      "longitude": 21.123456,
      "elevation_m": 145.5
    },
    "cell_count": 1812000
  }
}
```

**Pydantic Schema:**
```python
from pydantic import BaseModel
from typing import Dict, List

class OutletInfo(BaseModel):
    latitude: float
    longitude: float
    elevation_m: float

class WatershedResponse(BaseModel):
    boundary_geojson: Dict  # GeoJSON Feature
    outlet: OutletInfo
    cell_count: int

class DelineateResponse(BaseModel):
    watershed: WatershedResponse
```

---

### 6.3 Request: Generate Hydrograph

**Endpoint:** `POST /api/generate-hydrograph`

```json
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "duration": "1h",
  "probability": 10
}
```

**Pydantic Schema:**
```python
class HydrographRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    duration: str = Field(..., regex='^(15min|30min|1h|2h|6h|12h|24h)$')
    probability: int = Field(..., ge=1, le=100)
    
    @validator('probability')
    def validate_probability(cls, v):
        if v not in [1, 2, 5, 10, 20, 50]:
            raise ValueError('Probability must be 1, 2, 5, 10, 20, or 50')
        return v
```

---

### 6.4 Response: Generate Hydrograph

**Pełna struktura:**
```json
{
  "watershed": {
    "boundary_geojson": { "type": "Feature", "geometry": {...}, "properties": {...} },
    "area_km2": 45.3,
    "outlet_coords": [21.123, 52.123]
  },
  "parameters": {
    "perimeter_km": 38.5,
    "main_stream_length_km": 8.2,
    "mean_elevation_m": 125.5,
    "elevation_diff_m": 42.0,
    "mean_slope_percent": 2.3,
    "shape_coefficient": 0.67,
    "compactness_coefficient": 1.28
  },
  "land_cover": {
    "cn": 72.4,
    "land_cover_percent": {
      "las": 35.2,
      "grunt_orny": 42.1,
      "łąka": 18.3,
      "zabudowa": 4.4
    }
  },
  "precipitation": {
    "total_mm": 38.5,
    "duration_min": 60,
    "probability_percent": 10,
    "hietogram": {
      "time_min": [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
      "intensity_mm_per_min": [0.2, 0.5, 1.2, 1.8, 2.1, 1.5, 1.0, 0.7, 0.5, 0.3, 0.2, 0.1, 0.0],
      "cumulative_mm": [1.0, 3.5, 9.5, 18.5, 29.0, 36.5, 38.5, 38.5, 38.5, 38.5, 38.5, 38.5, 38.5]
    }
  },
  "hydrograph": {
    "time_min": [0, 5, 10, ..., 240],
    "discharge_m3s": [0, 2.3, 15.8, ..., 0.5],
    "peak_discharge_m3s": 42.3,
    "time_to_peak_min": 75,
    "total_volume_m3": 156780
  },
  "metadata": {
    "tc_min": 68.5,
    "cn": 72.4,
    "method": "SCS_CN + Beta_hyetograph + SCS_UH",
    "computed_at": "2026-01-14T10:30:45Z"
  }
}
```

---

## 7. Typy Danych Wewnętrznych (Python)

### 7.1 Data Classes

```python
from dataclasses import dataclass
from typing import List, Optional
from shapely.geometry import Point, Polygon

@dataclass
class Cell:
    """Reprezentuje pojedynczą komórkę w grafie flow_network."""
    id: int
    geom: Point
    elevation: float
    flow_accumulation: int
    slope: float
    downstream_id: Optional[int]
    cell_area: float
    is_stream: bool

@dataclass
class Watershed:
    """Reprezentuje wyznaczoną zlewnię."""
    boundary: Polygon
    outlet: Cell
    cells: List[Cell]
    area_km2: float

@dataclass
class PhysicalParameters:
    """Parametry fizjograficzne zlewni."""
    area_km2: float
    perimeter_km: float
    main_stream_length_km: float
    mean_elevation_m: float
    elevation_diff_m: float
    mean_slope_percent: float
    shape_coefficient: float
    compactness_coefficient: float

@dataclass
class LandCoverAnalysis:
    """Analiza pokrycia terenu."""
    cn: float
    land_cover_percent: dict  # {'las': 35.2, 'pola': 42.1, ...}
    total_area_m2: float

@dataclass
class Hyetograph:
    """Hietogram - rozkład opadu w czasie."""
    time_min: List[float]
    intensity_mm_per_min: List[float]
    cumulative_mm: List[float]
    total_mm: float
    duration_min: int

@dataclass
class Hydrograph:
    """Hydrogram - przepływ w czasie."""
    time_min: List[float]
    discharge_m3s: List[float]
    peak_discharge_m3s: float
    time_to_peak_min: float
    total_volume_m3: float
```

---

## 8. Migracje Bazy Danych

### 8.1 Alembic Migrations

**Struktura:**
```
migrations/
├── alembic.ini
├── env.py
└── versions/
    ├── 001_create_precipitation_data.py
    ├── 002_create_core_tables.py
    ├── 003_extend_stream_network.py
    ├── 004_create_depressions_table.py
    ├── 005_add_threshold_to_stream_network.py
    ├── 006_add_upstream_area_index.py
    ├── 007_create_stream_catchments.py
    ├── 008_add_depressions_filter_indexes.py
    ├── 009_add_stream_source_partial_index.py
    ├── 010_fix_stream_unique_index.py
    ├── 011_add_tile_spatial_indexes.py
    └── 012_extend_stream_catchments.py
```

**Przykład migracji:**
```python
# migrations/versions/001_initial_schema.py
from alembic import op
import sqlalchemy as sa
import geoalchemy2

def upgrade():
    op.create_table(
        'flow_network',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('geom', geoalchemy2.Geometry('POINT', srid=2180), nullable=False),
        sa.Column('elevation', sa.Float, nullable=False),
        sa.Column('flow_accumulation', sa.Integer, nullable=False, default=0),
        sa.Column('slope', sa.Float),
        sa.Column('downstream_id', sa.Integer, sa.ForeignKey('flow_network.id')),
        sa.Column('cell_area', sa.Float, nullable=False),
        sa.Column('is_stream', sa.Boolean, nullable=False, default=False),
        sa.CheckConstraint('elevation >= -50 AND elevation <= 3000', name='valid_elevation'),
        sa.CheckConstraint('flow_accumulation >= 0', name='valid_accumulation'),
        sa.CheckConstraint('cell_area > 0', name='positive_area')
    )
    
    op.create_index('idx_flow_geom', 'flow_network', ['geom'], postgresql_using='gist')
    op.create_index('idx_downstream', 'flow_network', ['downstream_id'])

def downgrade():
    op.drop_table('flow_network')
```

---

## 9. Rozmiary Danych i Storage

### 9.1 Szacunki Rozmiaru

**Dla gminy ~100 km² z NMT 5m:**

| Tabela | Liczba rekordów | Rozmiar rekordu | Total | Z indeksami |
|--------|----------------|----------------|-------|-------------|
| `flow_network` | 4,000,000 | ~100 bytes | 400 MB | ~800 MB |
| `precipitation_data` | 42,000 | ~80 bytes | 3.4 MB | ~7 MB |
| `land_cover` | 10,000 | ~500 bytes | 5 MB | ~10 MB |
| `stream_network` | 1,000 | ~200 bytes | 0.2 MB | ~0.5 MB |
| **TOTAL** | | | **~410 MB** | **~820 MB** |

**Dla gminy ~100 km² z NMT 1m:**
- `flow_network`: ~100,000,000 rekordów → ~10 GB (20 GB z indeksami)

---

### 9.2 Backup Strategy

**Full backup (pg_dump):**
```bash
pg_dump -U hydro_user -d hydro_db -F c -f hydro_db_backup.dump
```

**Restore:**
```bash
pg_restore -U hydro_user -d hydro_db -c hydro_db_backup.dump
```

**Selective backup (tylko dane preprocessing):**
```bash
pg_dump -U hydro_user -d hydro_db -t flow_network -t precipitation_data -t land_cover -t stream_network -F c -f preprocessing_data.dump
```

---

## 10. Data Validation

### 10.1 Validation Triggers

**Przykład: Walidacja downstream_id (nie może tworzyć cyklu):**
```sql
CREATE OR REPLACE FUNCTION check_no_cycle()
RETURNS TRIGGER AS $$
DECLARE
    current_id INT;
    visited_ids INT[];
BEGIN
    current_id := NEW.downstream_id;
    visited_ids := ARRAY[NEW.id];
    
    WHILE current_id IS NOT NULL LOOP
        IF current_id = ANY(visited_ids) THEN
            RAISE EXCEPTION 'Cycle detected in flow network';
        END IF;
        
        visited_ids := array_append(visited_ids, current_id);
        
        SELECT downstream_id INTO current_id
        FROM flow_network
        WHERE id = current_id;
    END LOOP;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_check_no_cycle
BEFORE INSERT OR UPDATE ON flow_network
FOR EACH ROW
EXECUTE FUNCTION check_no_cycle();
```

---

### 10.2 Data Quality Checks

**SQL queries do weryfikacji:**
```sql
-- Sprawdź orphaned cells (brak downstream oprócz outletów)
SELECT COUNT(*) 
FROM flow_network 
WHERE downstream_id IS NOT NULL 
  AND downstream_id NOT IN (SELECT id FROM flow_network);

-- Sprawdź geometrie poza bounding box
SELECT COUNT(*)
FROM flow_network
WHERE NOT ST_Within(geom, ST_MakeEnvelope(400000, 500000, 600000, 700000, 2180));

-- Sprawdź duplikaty w precipitation
SELECT geom, duration, probability, COUNT(*)
FROM precipitation_data
GROUP BY geom, duration, probability
HAVING COUNT(*) > 1;

-- Sprawdź CN poza zakresem
SELECT COUNT(*)
FROM land_cover
WHERE cn_value < 0 OR cn_value > 100;
```

---

## 11. Import i Export

### 11.1 Import NMT do flow_network

**Python script (używa WhiteboxTools + SQLAlchemy):**
```python
import whitebox
import geopandas as gpd
from sqlalchemy import create_engine

wbt = whitebox.WhiteboxTools()

# 1. Fill depressions
wbt.fill_depressions('input_dem.tif', 'filled_dem.tif')

# 2. D8 flow direction
wbt.d8_pointer('filled_dem.tif', 'flow_dir.tif')

# 3. D8 flow accumulation
wbt.d8_flow_accumulation('flow_dir.tif', 'flow_acc.tif')

# 4. Wektoryzacja do punktów (własny kod)
# ... konwersja rastrów do GeoDataFrame
# ... zapis do PostGIS

gdf.to_postgis('flow_network', engine, if_exists='append')
```

---

### 11.2 Export GeoJSON

```python
import geopandas as gpd

# Read from PostGIS
gdf = gpd.read_postgis(
    "SELECT * FROM land_cover WHERE category = 'las'",
    engine,
    geom_col='geom'
)

# Export to GeoJSON
gdf.to_file('lasy.geojson', driver='GeoJSON')
```

---

## 12. Podsumowanie

### 12.1 Kluczowe Punkty

- **6 tabel:** flow_network, precipitation_data, land_cover, stream_network, stream_catchments, depressions
- **Układ współrzędnych:** EPSG:2180 (PL-1992)
- **Indeksy przestrzenne (GIST)** dla wszystkich geometrii
- **Walidacja** przez CHECK constraints i triggers
- **Rozmiar:** ~1-20 GB w zależności od rozdzielczości NMT

### 12.2 Najważniejsze Constraints

✅ **Integralność referencyjna:** downstream_id → flow_network(id)  
✅ **Walidacja wartości:** elevation [-50..3000], CN [0..100], precipitation_mm ≥ 0  
✅ **Unique scenarios:** (geom, duration, probability) w precipitation_data  
✅ **No cycles:** Trigger zapobiega cyklom w grafie  

---

**Wersja dokumentu:** 1.2
**Data ostatniej aktualizacji:** 2026-02-13
**Status:** Approved  

---

*Ten dokument definiuje pełny model danych systemu. Wszelkie zmiany w schemacie bazy wymagają migracji Alembic i aktualizacji tego dokumentu.*
