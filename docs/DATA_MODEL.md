# DATA_MODEL.md - Model Danych
## System Analizy Hydrologicznej

**Wersja:** 1.6
**Data:** 2026-03-25
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
- **Tabele:** `snake_case`, liczba mnoga (np. `stream_network`)
- **Kolumny:** `snake_case`, liczba pojedyncza (np. `elevation`)
- **Klucze obce:** `nazwa_tabeli_id` (np. `downstream_segment_idx`)
- **Geometrie:** zawsze z SRID (Spatial Reference ID)
- **Jednostki:** zawsze w metrycznych (m, km, mm, m³/s)

---

## 2. Schemat Bazy Danych

### 2.1 Entity Relationship Diagram (ERD)

```
┌─────────────────────┐
│   flow_network      │  <-- USUNIETA (ADR-028, migracja 015)
├─────────────────────┤
│ (DROP TABLE)        │
└─────────────────────┘

┌─────────────────────┐       ┌─────────────────────────┐
│ precipitation_data  │       │      land_cover          │
├─────────────────────┤       ├─────────────────────────┤
│ id (PK)             │       │ id (PK)                  │
│ geom                │       │ geom                     │
│ duration            │       │ category                 │
│ probability         │       │ cn_value                 │
│ precipitation_mm    │       │ imperviousness           │
│ source              │       │ bdot_class               │
│ updated_at          │       └─────────────────────────┘
└─────────────────────┘
                                ┌─────────────────────────┐
┌─────────────────────┐         │     soil_hsg             │
│  stream_network     │         ├─────────────────────────┤
├─────────────────────┤         │ id (PK)                  │
│ id (PK)             │         │ geom                     │
│ geom                │         │ hsg_group                │
│ name                │         │ area_m2                  │
│ length_m            │         └─────────────────────────┘
│ strahler_order      │
│ source              │         ┌─────────────────────────┐
│ upstream_area_km2   │         │     bdot_streams         │
│ mean_slope_percent  │         ├─────────────────────────┤
│ threshold_m2        │         │ id (PK)                  │
│ segment_idx         │ ──┐     │ geom                     │
│ is_real_stream      │   │     │ layer_type               │
└─────────────────────┘   │     │ name                     │
    ↑ spatial matching    │     │ length_m                 │
    (bufor 15m, ADR-044)  │     └─────────────────────────┘
                          │
                          │  (threshold_m2, segment_idx)
┌──────────────────────────┐
│    stream_catchments     │
├──────────────────────────┤
│ id (PK)                  │
│ geom                     │
│ segment_idx              │ <── lookup z stream_network
│ threshold_m2             │
│ area_km2                 │
│ mean_elevation_m         │
│ mean_slope_percent       │
│ strahler_order           │
│ downstream_segment_idx   │ --> segment_idx (graf splywu)
│ elevation_min_m          │
│ elevation_max_m          │
│ perimeter_km             │
│ stream_length_km         │
│ elev_histogram (JSONB)   │
│ hydraulic_length_km      │
│ max_flow_dist_m          │
│ longest_flow_path_geom   │
│ divide_flow_path_geom    │
└──────────────────────────┘

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

### 3.1 ~~Tabela: `flow_network`~~ — USUNIETA (ADR-028)

> **USUNIETA w migracji 015 (2026-02-17).** Tabela przechowywala dane kazdego piksela DEM (~39.4M wierszy dla 8 arkuszy). Ladowanie trwalo ~17 min (58% pipeline). Zadne API endpoint nie czytalo z niej w runtime — wszystkie endpointy korzystaja z `stream_network`, `stream_catchments` i CatchmentGraph. Patrz ADR-028.

---

### 3.2 Tabela: `precipitation_data`

**Opis:** Dane opadowe z IMGW - maksymalne opady dla różnych czasów trwania i prawdopodobieństw.

**Schemat SQL:**
```sql
CREATE TABLE precipitation_data (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(Point, 2180) NOT NULL,
    duration VARCHAR(10) NOT NULL,
    probability DOUBLE PRECISION NOT NULL,  -- migracja 020: zmiana z INT na DOUBLE PRECISION
    precipitation_mm FLOAT NOT NULL,
    source VARCHAR(50) NOT NULL,  -- IMGW_PMAXTP (atlas) lub IMGW_HISTORICAL (wlasna analiza)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_duration CHECK (duration IN (
        '5min','10min','15min','30min','45min','1h','1.5h','2h',
        '3h','6h','12h','18h','24h','36h','48h','72h'
    )),  -- migracja 019/020: rozszerzono z 7 do 16 wartości
    CONSTRAINT valid_probability CHECK (probability IN (
        0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,1,2,3,5,10,20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9
    )),  -- migracja 020: zmiana z 6 INT na 27 FLOAT
    CONSTRAINT positive_precipitation CHECK (precipitation_mm >= 0),
    CONSTRAINT unique_precipitation_scenario UNIQUE (geom, duration, probability)
);

-- Indeksy
CREATE INDEX idx_precipitation_geom ON precipitation_data USING GIST(geom);
CREATE INDEX idx_precipitation_scenario ON precipitation_data(duration, probability);
CREATE INDEX idx_precipitation_duration ON precipitation_data(duration);
CREATE INDEX idx_precipitation_probability ON precipitation_data(probability);

-- Komentarze
COMMENT ON TABLE precipitation_data IS 'Maksymalne opady projektowe';
COMMENT ON COLUMN precipitation_data.duration IS 'Czas trwania opadu: 5min..72h (16 wartości)';
COMMENT ON COLUMN precipitation_data.probability IS 'Prawdopodobieństwo przewyższenia [%]: 0.01..99.9 (27 wartości FLOAT)';
COMMENT ON COLUMN precipitation_data.precipitation_mm IS 'Wysokość opadu [mm]';
```

**Kolumny - szczegóły:**

| Kolumna | Typ | Nullable | Default | Opis | Dozwolone wartości |
|---------|-----|----------|---------|------|-------------------|
| `id` | SERIAL | NO | auto | Unikalny identyfikator | 1..∞ |
| `geom` | GEOMETRY | NO | - | Punkt siatki precipitation | EPSG:2180 |
| `duration` | VARCHAR(10) | NO | - | Czas trwania | '5min','10min','15min','30min','45min','1h','1.5h','2h','3h','6h','12h','18h','24h','36h','48h','72h' |
| `probability` | DOUBLE PRECISION | NO | - | Prawdopodobieństwo [%] | 0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,1,2,3,5,10,20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9 |
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
- Scenariusze: 16 czasów × 27 prawdopodobieństw = 432 na punkt
- Total: ~432,000 - 2,160,000 rekordów

---

### 3.3 Tabela: `land_cover`

**Opis:** Pokrycie terenu z BDOT10k z przypisanymi wartościami Curve Number.

**Schemat SQL:**
```sql
CREATE TABLE land_cover (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(MultiPolygon, 2180) NOT NULL,
    category VARCHAR(50) NOT NULL,
    cn_value INT NOT NULL,
    imperviousness FLOAT,
    bdot_class VARCHAR(20),

    CONSTRAINT valid_cn CHECK (cn_value >= 0 AND cn_value <= 100),
    CONSTRAINT valid_imperviousness CHECK (imperviousness IS NULL OR (imperviousness >= 0 AND imperviousness <= 1)),
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
    length_m FLOAT,
    strahler_order INT,
    source VARCHAR(50) DEFAULT 'MPHP',
    upstream_area_km2 FLOAT,                        -- migracja 003
    mean_slope_percent FLOAT,                       -- migracja 003
    threshold_m2 INT NOT NULL DEFAULT 1000,          -- migracja 005/017 (aktywne progi: 1000, 10000, 100000; próg 100 usunięty, migracja 017)
    segment_idx INTEGER,                            -- migracja 014 (ADR-026)
    is_real_stream BOOLEAN,                         -- migracja 021 (ADR-044)

    CONSTRAINT positive_length CHECK (length_m IS NULL OR length_m > 0),
    CONSTRAINT valid_strahler CHECK (strahler_order IS NULL OR strahler_order > 0)
);

-- Indeksy
CREATE INDEX idx_stream_geom ON stream_network USING GIST(geom);
CREATE INDEX idx_stream_name ON stream_network(name);
CREATE INDEX idx_strahler_order ON stream_network(strahler_order);
CREATE UNIQUE INDEX idx_stream_unique ON stream_network
    (COALESCE(name, ''), threshold_m2, ST_GeoHash(ST_Transform(geom, 4326), 12));
                                                    -- migracja 010: dodano threshold_m2
CREATE INDEX idx_stream_threshold ON stream_network
    (threshold_m2, strahler_order);                 -- migracja 005
CREATE INDEX idx_stream_upstream_area ON stream_network
    (upstream_area_km2);                            -- migracja 006
CREATE INDEX idx_stream_threshold_segidx ON stream_network
    (threshold_m2, segment_idx);                    -- migracja 014 (ADR-026)
CREATE INDEX idx_stream_geom_dem_derived ON stream_network
    USING GIST(geom) WHERE source = 'DEM_DERIVED'; -- migracja 009
-- Partial indexes per threshold (migracja 011, prog 100 usuniety w migracji 017):
CREATE INDEX idx_stream_geom_t1000 ON stream_network USING GIST(geom)
    WHERE threshold_m2 = 1000;
CREATE INDEX idx_stream_geom_t10000 ON stream_network USING GIST(geom)
    WHERE threshold_m2 = 10000;
CREATE INDEX idx_stream_geom_t100000 ON stream_network USING GIST(geom)
    WHERE threshold_m2 = 100000;

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
| `geom` | GEOMETRY(LineString, 2180) | NO | - | Linia reprezentujaca odcinek cieku |
| `name` | VARCHAR(100) | YES | NULL | Nazwa cieku |
| `length_m` | FLOAT | YES | NULL | Dlugosc [m] (obliczana: ST_Length(geom)) |
| `strahler_order` | INT | YES | NULL | Rzad Strahlera (1=zrodlowy, wyzsze=wieksze) |
| `source` | VARCHAR(50) | YES | 'MPHP' | Zrodlo danych ('MPHP' lub 'DEM_DERIVED') |
| `upstream_area_km2` | FLOAT | YES | NULL | Powierzchnia zlewni na koncu segmentu [km2] (migracja 003) |
| `mean_slope_percent` | FLOAT | YES | NULL | Sredni spadek wzdluz segmentu [%] (migracja 003) |
| `threshold_m2` | INT | NO | 1000 | Prog akumulacji przeplywu [m2] (migracja 005/017). Aktywne progi: 1000, 10000, 100000 (próg 100 usunięty, migracja 017) |
| `segment_idx` | INTEGER | YES | NULL | Indeks segmentu spojny z `stream_catchments.segment_idx` (migracja 014, ADR-026) |
| `is_real_stream` | BOOLEAN | YES | NULL | Czy segment pokrywa sie z ciekiem BDOT10k (spatial matching, bufor 15m, overlap >= 50%). NULL = nie matchowano, false = splywy algorytmiczne, true = ciek rzeczywisty (migracja 021, ADR-044) |

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
    elev_histogram JSONB,                        -- histogram wysokości (stały interwał 1m)
    -- Nowa kolumna (migracja 022):
    hydraulic_length_km FLOAT,                   -- max droga spływu z flow direction (pyflwdir stream_distance)
    -- Nowe kolumny (migracja 023):
    max_flow_dist_m DOUBLE PRECISION,            -- odległość najdalszej komórki do globalnego ujścia [m]
    longest_flow_path_geom GEOMETRY(LINESTRING, 2180), -- geometria najdłuższej ścieżki spływu
    -- Nowa kolumna (migracja 024):
    divide_flow_path_geom GEOMETRY(LINESTRING, 2180)   -- geometria ścieżki spływu z działu wód (granica zlewni → ujście)
);

-- Indeksy
CREATE INDEX idx_catchments_geom ON stream_catchments USING GIST(geom);
CREATE INDEX idx_catchments_threshold ON stream_catchments(threshold_m2, strahler_order);
CREATE INDEX idx_catchments_area ON stream_catchments(area_km2);
CREATE INDEX idx_catchments_downstream                   -- migracja 012
    ON stream_catchments(threshold_m2, downstream_segment_idx);
-- Partial indexes per threshold (migracja 011, prog 100 usuniety w migracji 017):
CREATE INDEX idx_catchment_geom_t1000 ON stream_catchments USING GIST(geom)
    WHERE threshold_m2 = 1000;
CREATE INDEX idx_catchment_geom_t10000 ON stream_catchments USING GIST(geom)
    WHERE threshold_m2 = 10000;
CREATE INDEX idx_catchment_geom_t100000 ON stream_catchments USING GIST(geom)
    WHERE threshold_m2 = 100000;
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
| `hydraulic_length_km` | FLOAT | YES | Maksymalna droga spływu z flow direction grid [km] (`pyflwdir.stream_distance()`). Używana przez NRCS/Kirpich tc (migracja 022) |

**Nowe kolumny (migracja 023) — ścieżki spływu:**

| Kolumna | Typ | Nullable | Opis |
|---------|-----|----------|------|
| `max_flow_dist_m` | DOUBLE PRECISION | YES | Odległość najdalszej komórki do globalnego ujścia [m] (z `pyflwdir.stream_distance`) |
| `longest_flow_path_geom` | GEOMETRY(LINESTRING, 2180) | YES | Geometria najdłuższej ścieżki spływu w zlewni cząstkowej (z batch `flw.path()`) |

**Nowa kolumna (migracja 024) — ścieżka spływu z działu wód:**

| Kolumna | Typ | Nullable | Opis |
|---------|-----|----------|------|
| `divide_flow_path_geom` | GEOMETRY(LINESTRING, 2180) | YES | Geometria ścieżki spływu z działu wód (granica zlewni → ujście) |

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

### 3.7 Tabela: `soil_hsg`

**Opis:** Grupy glebowe HSG (Hydrologic Soil Group) — poligony z klasyfikacją A/B/C/D (migracja 016).

**Schemat SQL:**
```sql
CREATE TABLE soil_hsg (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(MULTIPOLYGON, 2180) NOT NULL,
    hsg_group VARCHAR(1) NOT NULL,           -- 'A', 'B', 'C', 'D'
    area_m2 FLOAT NOT NULL,

    CONSTRAINT valid_hsg_group CHECK (hsg_group IN ('A', 'B', 'C', 'D'))
);

-- Indeksy
CREATE INDEX idx_soil_hsg_geom ON soil_hsg USING GIST(geom);
CREATE INDEX idx_soil_hsg_group ON soil_hsg(hsg_group);

-- Komentarze
COMMENT ON TABLE soil_hsg IS 'Grupy glebowe HSG z SoilGrids/Kartograf';
COMMENT ON COLUMN soil_hsg.hsg_group IS 'Grupa hydrologiczna gleby: A (piaszczyste), B (lessowe), C (gliniaste), D (ilaste)';
COMMENT ON COLUMN soil_hsg.area_m2 IS 'Powierzchnia poligonu [m²]';
```

**Kolumny - szczegóły:**

| Kolumna | Typ | Nullable | Default | Opis | Dozwolone wartości |
|---------|-----|----------|---------|------|-------------------|
| `id` | SERIAL | NO | auto | Unikalny identyfikator | 1..inf |
| `geom` | GEOMETRY | NO | - | Poligon grupy glebowej | EPSG:2180 |
| `hsg_group` | VARCHAR(1) | NO | - | Grupa HSG | 'A', 'B', 'C', 'D' |
| `area_m2` | FLOAT | NO | - | Powierzchnia [m2] | > 0 |

---

### 3.8 Tabela: `bdot_streams`

**Opis:** Cieki z BDOT10k — geometrie rzek (SWRS), kanalow (SWKN) i rowow (SWRM) zaimportowane z danych referencyjnych. Uzywane do spatial matching z `stream_network` w celu oznaczenia ciekow rzeczywistych (migracja 021, ADR-044).

**Schemat SQL:**
```sql
CREATE TABLE bdot_streams (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(LineString, 2180) NOT NULL,
    layer_type VARCHAR(10) NOT NULL,    -- SWRS=rzeka, SWKN=kanal, SWRM=row
    name VARCHAR(200),
    length_m FLOAT
);

-- Indeksy
CREATE INDEX idx_bdot_streams_geom ON bdot_streams USING GIST(geom);
CREATE INDEX idx_bdot_streams_type ON bdot_streams(layer_type);

-- Komentarze
COMMENT ON TABLE bdot_streams IS 'Cieki z BDOT10k (rzeki, kanaly, rowy) do spatial matching';
COMMENT ON COLUMN bdot_streams.layer_type IS 'Typ warstwy BDOT10k: SWRS=rzeka, SWKN=kanal, SWRM=row';
COMMENT ON COLUMN bdot_streams.name IS 'Nazwa cieku z BDOT10k';
COMMENT ON COLUMN bdot_streams.length_m IS 'Dlugosc geometrii [m]';
```

**Kolumny - szczegoly:**

| Kolumna | Typ | Nullable | Default | Opis | Dozwolone wartosci |
|---------|-----|----------|---------|------|-------------------|
| `id` | SERIAL | NO | auto | Unikalny identyfikator | 1..inf |
| `geom` | GEOMETRY(LineString, 2180) | NO | - | Linia cieku | EPSG:2180 |
| `layer_type` | VARCHAR(10) | NO | - | Typ warstwy BDOT10k | 'SWRS', 'SWKN', 'SWRM' |
| `name` | VARCHAR(200) | YES | NULL | Nazwa cieku | tekst |
| `length_m` | FLOAT | YES | NULL | Dlugosc [m] | > 0 |

**Liczba rekordow:** ~3-10k per obszar analizy (np. 4737 dla regionu Warszawy).

---

## 4. Relacje i Constraints

### 4.1 Klucze Obce (Foreign Keys)

> ~~**flow_network.downstream_id → flow_network.id**~~ — USUNIETA (ADR-028). Tabela `flow_network` zostala wyeliminowana w migracji 015.

### 4.2 Unique Constraints

**precipitation_data: unique_precipitation_scenario (geom, duration, probability)**
- Zapobiega duplikatom dla tej samej lokalizacji i scenariusza

**stream_network: unique (COALESCE(name, ''), threshold_m2, ST_GeoHash(geom, 12))**
- Zapobiega duplikatom tego samego odcinka cieku w ramach danego progu
- Migracja 010 (ADR-019): dodano `threshold_m2` do indeksu unikalnego

### 4.3 Check Constraints

**Wszystkie CHECK constraints w bazie:**
```sql
-- precipitation_data (migracja 001, aktualizacja: migracja 019/020)
CONSTRAINT valid_duration CHECK (duration IN (
    '5min','10min','15min','30min','45min','1h','1.5h','2h',
    '3h','6h','12h','18h','24h','36h','48h','72h'
))
CONSTRAINT valid_probability CHECK (probability IN (
    0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,1,2,3,5,10,20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9
))
CONSTRAINT positive_precipitation CHECK (precipitation_mm >= 0)

-- land_cover (migracja 002)
CONSTRAINT valid_cn CHECK (cn_value >= 0 AND cn_value <= 100)
CONSTRAINT valid_imperviousness CHECK (imperviousness IS NULL OR (imperviousness >= 0 AND imperviousness <= 1))
CONSTRAINT valid_category CHECK (category IN ('las', 'łąka', 'grunt_orny', 'zabudowa_mieszkaniowa',
    'zabudowa_przemysłowa', 'droga', 'woda', 'inny'))

-- stream_network (migracja 002)
CONSTRAINT positive_length CHECK (length_m IS NULL OR length_m > 0)
CONSTRAINT valid_strahler CHECK (strahler_order IS NULL OR strahler_order > 0)

-- soil_hsg (migracja 016)
CONSTRAINT valid_hsg_group CHECK (hsg_group IN ('A', 'B', 'C', 'D'))
```

---

## 5. Indeksy i Optymalizacje

### 5.1 Indeksy Przestrzenne (GIST)

**Dla wszystkich kolumn geometrycznych:**
```sql
CREATE INDEX idx_precipitation_geom ON precipitation_data USING GIST(geom);
CREATE INDEX idx_landcover_geom ON land_cover USING GIST(geom);
CREATE INDEX idx_stream_geom ON stream_network USING GIST(geom);
CREATE INDEX idx_catchments_geom ON stream_catchments USING GIST(geom);
CREATE INDEX idx_depressions_geom ON depressions USING GIST(geom);
CREATE INDEX idx_soil_hsg_geom ON soil_hsg USING GIST(geom);
CREATE INDEX idx_bdot_streams_geom ON bdot_streams USING GIST(geom);

-- stream_catchments: geometrie ścieżek spływu (migracje 023, 024)
CREATE INDEX idx_catchments_flow_path_geom ON stream_catchments USING GIST(longest_flow_path_geom);
CREATE INDEX idx_catchments_divide_flow_path_geom ON stream_catchments USING GIST(divide_flow_path_geom);
```

**Partial GIST indexes (migracja 009, 011, 017):**
```sql
-- DEM-derived streams (migracja 009)
CREATE INDEX idx_stream_geom_dem_derived ON stream_network USING GIST(geom)
    WHERE source = 'DEM_DERIVED';

-- Per-threshold indexes (migracja 011, prog 100 usuniety w migracji 017)
CREATE INDEX idx_stream_geom_t1000 ON stream_network USING GIST(geom) WHERE threshold_m2 = 1000;
CREATE INDEX idx_stream_geom_t10000 ON stream_network USING GIST(geom) WHERE threshold_m2 = 10000;
CREATE INDEX idx_stream_geom_t100000 ON stream_network USING GIST(geom) WHERE threshold_m2 = 100000;
CREATE INDEX idx_catchment_geom_t1000 ON stream_catchments USING GIST(geom) WHERE threshold_m2 = 1000;
CREATE INDEX idx_catchment_geom_t10000 ON stream_catchments USING GIST(geom) WHERE threshold_m2 = 10000;
CREATE INDEX idx_catchment_geom_t100000 ON stream_catchments USING GIST(geom) WHERE threshold_m2 = 100000;
```

**Dlaczego GIST:**
- Umozliwia szybkie spatial queries (ST_Intersects, ST_Distance, ST_Contains)
- Kluczowe dla wydajnosci systemu (< 10s dla delineacji)
- Partial indexes per threshold przyspieszaja MVT tile serving

---

### 5.2 Indeksy B-tree

**Dla czesto filtrowanych kolumn:**
```sql
-- precipitation (migracja 001)
CREATE INDEX idx_precipitation_scenario ON precipitation_data(duration, probability); -- composite
CREATE INDEX idx_precipitation_duration ON precipitation_data(duration);
CREATE INDEX idx_precipitation_probability ON precipitation_data(probability);

-- land_cover (migracja 002)
CREATE INDEX idx_category ON land_cover(category);
CREATE INDEX idx_cn_value ON land_cover(cn_value);

-- stream_network (migracje 002, 005, 006, 014)
CREATE INDEX idx_stream_name ON stream_network(name);
CREATE INDEX idx_strahler_order ON stream_network(strahler_order);
CREATE INDEX idx_stream_threshold ON stream_network(threshold_m2, strahler_order);      -- migracja 005
CREATE INDEX idx_stream_upstream_area ON stream_network(upstream_area_km2);              -- migracja 006
CREATE INDEX idx_stream_threshold_segidx ON stream_network(threshold_m2, segment_idx);  -- migracja 014

-- stream_catchments (migracje 007, 012, 018)
CREATE INDEX idx_catchments_threshold ON stream_catchments(threshold_m2, strahler_order);
CREATE INDEX idx_catchments_area ON stream_catchments(area_km2);
CREATE INDEX idx_catchments_downstream ON stream_catchments(threshold_m2, downstream_segment_idx); -- migracja 012
CREATE INDEX idx_catchments_threshold_segment ON stream_catchments(threshold_m2, segment_idx);     -- migracja 018

-- depressions (migracja 008)
CREATE INDEX idx_depressions_volume ON depressions(volume_m3);
CREATE INDEX idx_depressions_area ON depressions(area_m2);
CREATE INDEX idx_depressions_max_depth ON depressions(max_depth_m);

-- soil_hsg (migracja 016)
CREATE INDEX idx_soil_hsg_group ON soil_hsg(hsg_group);

-- bdot_streams (migracja 021)
CREATE INDEX idx_bdot_streams_type ON bdot_streams(layer_type);
```

---

### 5.3 Strategie Optymalizacji

**Composite Index dla scenariuszy:**
- `(duration, probability)` razem jako jeden indeks
- Szybsze queries `WHERE duration = X AND probability = Y`

**Vacuum i Analyze:**
```sql
-- Okresowe utrzymanie (cron job: weekly)
VACUUM ANALYZE precipitation_data;
VACUUM ANALYZE land_cover;
VACUUM ANALYZE stream_network;
VACUUM ANALYZE stream_catchments;
VACUUM ANALYZE depressions;
VACUUM ANALYZE soil_hsg;
VACUUM ANALYZE bdot_streams;
```

---

## 6. Formaty Danych API

### 6.1 Request: Delineate Watershed

**Endpoint:** `POST /api/delineate-watershed`

Tryb precomputed (z `threshold_m2` — snap-to-stream + BFS po grafie):
```json
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "threshold_m2": 10000,
  "display_threshold_m2": 10000
}
```

Tryb precise (bez `threshold_m2` — delimitacja rastrowa pyflwdir on-the-fly):
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
    threshold_m2: int | None = Field(None, description="Flow accumulation threshold [m2]. When provided, uses precomputed mode (BFS)")
    display_threshold_m2: int | None = Field(None, description="Threshold for MVT stream highlighting")
```

---

### 6.2 Response: Delineate Watershed

```json
{
  "mode": "precomputed",
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
    }
  },
  "stream": {
    "segment_idx": 42,
    "strahler_order": 3,
    "length_m": 523.4,
    "upstream_area_km2": 12.8
  },
  "upstream_segment_indices": [42, 43, 44],
  "display_threshold_m2": 10000
}
```

**Pydantic Schema:**
```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class OutletInfo(BaseModel):
    latitude: float
    longitude: float
    elevation_m: float

class WatershedResponse(BaseModel):
    boundary_geojson: Dict  # GeoJSON Feature
    outlet: OutletInfo

class StreamInfo(BaseModel):
    segment_idx: int
    strahler_order: int | None = None
    length_m: float | None = None
    upstream_area_km2: float | None = None

class DelineateResponse(BaseModel):
    mode: str  # "precomputed" | "precise"
    watershed: WatershedResponse
    stream: StreamInfo | None = None  # precomputed mode only
    upstream_segment_indices: list[int] | None = None
    display_threshold_m2: int | None = None
    info_message: str | None = None
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
    duration: str = Field(..., pattern='^(5min|10min|15min|30min|45min|1h|1\\.5h|2h|3h|6h|12h|18h|24h|36h|48h|72h)$')
    probability: float = Field(..., ge=0.01, le=99.9)

    @validator('probability')
    def validate_probability(cls, v):
        if v not in [0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,1,2,3,5,10,20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9]:
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
    "length_km": 14.2,
    "main_stream_length_km": 8.2,
    "mean_elevation_m": 125.5,
    "elevation_diff_m": 42.0,
    "mean_slope_percent": 2.3,
    "shape_coefficient": 0.67,
    "compactness_coefficient": 1.28,
    "lemniscate_ratio": 3.51,
    "divide_slope": 1.10,
    "asymmetry_coefficient": null,
    "relief_ratio": 6.24
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
class Watershed:
    """Reprezentuje wyznaczoną zlewnię."""
    boundary: Polygon
    outlet_coords: tuple  # (lon, lat)
    area_km2: float

@dataclass
class PhysicalParameters:
    """Parametry fizjograficzne zlewni."""
    area_km2: float
    perimeter_km: float
    length_km: float                    # z hydraulic_length_km (droga spływu), nie odległość euklidesowa
    main_stream_length_km: float
    mean_elevation_m: float
    elevation_diff_m: float
    mean_slope_percent: float
    shape_coefficient: float
    compactness_coefficient: float
    lemniscate_ratio: float | None      # Cl = π·L²/(4·A) — wskaźnik lemniskaty Chorleya
    divide_slope: float | None          # Rp = ΔH/P [‰] — spadek działu wodnego
    asymmetry_coefficient: float | None # α = 2·(AL-AP)/A — współczynnik asymetrii (placeholder)
    relief_ratio: float | None          # R = ΔH/√A [‰] — wskaźnik rzeźby

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
    ├── 010_fix_stream_unique_constraint.py
    ├── 011_add_tile_spatial_indexes.py
    ├── 012_extend_stream_catchments.py
    ├── 013_add_stream_partial_index.py
    ├── 014_add_segment_idx_to_stream_network.py
    ├── 015_drop_flow_network.py
    ├── 016_create_soil_hsg.py
    ├── 017_remove_threshold_100.py
    ├── 018_composite_index_threshold_segment.py
    ├── 019_update_duration_check_pmaxtp.py
    ├── 020_full_pmaxtp_range.py                    # probability INT→FLOAT, rozszerzone zakresy duration/probability
    ├── 021_add_bdot_streams.py                     # tabela bdot_streams + is_real_stream kolumna w stream_network
    ├── 022_add_hydraulic_length.py                 # hydraulic_length_km w stream_catchments
    ├── 023_add_flow_path_columns.py                # max_flow_dist_m, longest_flow_path_geom
    ├── 024_add_divide_flow_path.py                 # divide_flow_path_geom w stream_catchments
    └── d7af925de530_merge_migration.py             # merge: bdot + flow path
```

**Przykład migracji (021 — bdot_streams + is_real_stream):**
```python
# migrations/versions/021_add_bdot_streams.py
from alembic import op
import sqlalchemy as sa
import geoalchemy2

def upgrade():
    op.create_table(
        'bdot_streams',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('geom', geoalchemy2.Geometry('LINESTRING', srid=2180), nullable=False),
        sa.Column('layer_type', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200)),
        sa.Column('length_m', sa.Float),
    )
    op.create_index('idx_bdot_streams_geom', 'bdot_streams', ['geom'], postgresql_using='gist')
    op.create_index('idx_bdot_streams_type', 'bdot_streams', ['layer_type'])

    # Dodaj kolumnę is_real_stream do stream_network (ADR-044)
    op.add_column('stream_network', sa.Column('is_real_stream', sa.Boolean, nullable=True))

def downgrade():
    op.drop_column('stream_network', 'is_real_stream')
    op.drop_table('bdot_streams')
```

---

## 9. Rozmiary Danych i Storage

### 9.1 Szacunki Rozmiaru

**Dla gminy ~100 km² z NMT 1m (po eliminacji flow_network — ADR-028):**

| Tabela | Liczba rekordów | Rozmiar rekordu | Total | Z indeksami |
|--------|----------------|----------------|-------|-------------|
| `precipitation_data` | 42,000 | ~80 bytes | 3.4 MB | ~7 MB |
| `land_cover` | 10,000 | ~500 bytes | 5 MB | ~10 MB |
| `stream_network` | ~20,000 | ~200 bytes | 4 MB | ~10 MB |
| `stream_catchments` | ~20,000 | ~1 KB | 20 MB | ~50 MB |
| `depressions` | ~600,000 | ~200 bytes | 120 MB | ~250 MB |
| `soil_hsg` | ~5,000 | ~500 bytes | 2.5 MB | ~5 MB |
| **TOTAL** | | | **~155 MB** | **~335 MB** |

> **Uwaga:** Eliminacja `flow_network` (ADR-028) zmniejszyla rozmiar bazy o ~80% (z ~2.5 GB do ~330 MB dla 8 arkuszy NMT 1m).

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
pg_dump -U hydro_user -d hydro_db -t precipitation_data -t land_cover -t stream_network -t stream_catchments -t depressions -t soil_hsg -F c -f preprocessing_data.dump
```

---

## 10. Data Validation

### 10.1 Data Quality Checks

**SQL queries do weryfikacji:**
```sql
-- Sprawdź duplikaty w precipitation
SELECT geom, duration, probability, COUNT(*)
FROM precipitation_data
GROUP BY geom, duration, probability
HAVING COUNT(*) > 1;

-- Sprawdź CN poza zakresem
SELECT COUNT(*)
FROM land_cover
WHERE cn_value < 0 OR cn_value > 100;

-- Sprawdź spójność stream_network ↔ stream_catchments
SELECT sn.threshold_m2, COUNT(DISTINCT sn.segment_idx) AS streams, COUNT(DISTINCT sc.segment_idx) AS catchments
FROM stream_network sn
LEFT JOIN stream_catchments sc ON sn.threshold_m2 = sc.threshold_m2 AND sn.segment_idx = sc.segment_idx
WHERE sn.source = 'DEM_DERIVED'
GROUP BY sn.threshold_m2;
```

---

## 11. Import i Export

### 11.1 Import NMT do bazy

> **Uwaga:** Od ADR-028 pipeline DEM nie importuje danych per-piksel do bazy. Zamiast tego generuje warstwy pochodne (stream_network, stream_catchments) bezposrednio z rastrow w pamieci (pyflwdir + numpy). Patrz `scripts/process_dem.py`.

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

- **6 tabel:** precipitation_data, land_cover, stream_network, stream_catchments, depressions, soil_hsg (flow_network usunieta -- ADR-028)
- **19 migracji Alembic** (001-023, z lukami)
- **Uklad wspolrzednych:** EPSG:2180 (PL-1992)
- **Indeksy przestrzenne (GIST)** dla wszystkich geometrii + partial indexes per threshold
- **Walidacja** przez CHECK constraints
- **Aktywne progi stream_network:** 1000, 10000, 100000 (prog 100 usuniety -- ADR-030, migracja 017)

### 12.2 Najważniejsze Constraints

✅ **Walidacja wartości:** CN [0..100], precipitation_mm >= 0
✅ **Unique scenarios:** (geom, duration, probability) w precipitation_data
✅ **Unique streams:** (COALESCE(name, ''), threshold_m2, geohash) w stream_network
✅ **Spójność grafu:** downstream_segment_idx w stream_catchments → segment_idx

---

**Wersja dokumentu:** 1.5
**Data ostatniej aktualizacji:** 2026-03-24
**Status:** Approved

---

*Ten dokument definiuje pełny model danych systemu. Wszelkie zmiany w schemacie bazy wymagają migracji Alembic i aktualizacji tego dokumentu.*
