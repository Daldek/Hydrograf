# Procedura obliczeniowa — Hydrograf

Kompletny opis pipeline'u obliczeniowego backendu: od surowego NMT przez preprocessing, wyznaczanie zlewni, parametry fizjograficzne, aż po generowanie hydrogramu.

---

## Spis treści

1. [Faza 1: Preprocessing NMT](#faza-1-preprocessing-nmt)
2. [Faza 2: Wyznaczanie zlewni (runtime)](#faza-2-wyznaczanie-zlewni-runtime)
3. [Faza 3: Parametry morfometryczne](#faza-3-parametry-morfometryczne)
4. [Faza 4: Dane opadowe](#faza-4-dane-opadowe)
5. [Faza 5: Krzywa CN](#faza-5-krzywa-cn)
6. [Faza 6: Generowanie hydrogramu](#faza-6-generowanie-hydrogramu)
7. [Schemat bazy danych](#schemat-bazy-danych)
8. [Wydajność](#wydajność)

---

## Faza 1: Preprocessing NMT

**Skrypt:** `backend/scripts/process_dem.py` (~2800 linii)
**Uruchamianie:** jednorazowo per arkusz NMT, ~3-8 min

### 1.1 Wczytanie NMT

**Funkcja:** `read_raster()` (linie 153-204)
- Wejście: ASC / VRT / GeoTIFF
- Wyjście: `(data: np.ndarray, metadata: dict)` z kluczami: `ncols`, `nrows`, `xllcorner`, `yllcorner`, `cellsize`, `nodata_value`, `crs`, `bounds`, `transform`

### 1.2 Łatanie wewnętrznych luk nodata

**Funkcja:** `fill_internal_nodata_holes()` (linie 296-377)
- Algorytm: `scipy.ndimage.generic_filter` z oknem 3×3
- Warunek: komórka nodata z ≥5 prawidłowymi sąsiadami
- Wzór: `new_value = mean(valid_neighbors)`
- Maksymalnie 3 iteracje

### 1.3 Przetwarzanie hydrologiczne

**Funkcja:** `process_hydrology_pyflwdir()` (linie 684-792)

#### Krok 1: Wypełnienie zagłębień (depression filling)
- Algorytm: Wang & Liu 2006 (`pyflwdir.dem.fill_depressions()`)
- Parametry: `nodata=nodata, max_depth=-1.0, outlets="edge"`
- Wyjście: `(filled_dem, d8_fdir)` — DEM bez depresji + macierz kierunków odpływu D8

#### Krok 2: Kierunki odpływu (flow direction)
- Kodowanie D8: `1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE`
- Nodata pyflwdir (247) → int16 (0)

#### Krok 3: Akumulacja spływu (flow accumulation)
- Metoda: `pyflwdir.FlwdirRaster.upstream_area(unit="cell")`
- Wzór: `acc[cell] = 1 + Σ(acc[upstream_cells])`
- Wyjście: int32 array (liczba komórek, nie m²)

#### Krok 4: Naprawa wewnętrznych zlewów (internal sinks)
- Wykrywanie: `~is_valid_d8 & valid & ~edge_mask`
- Hierarchia naprawy:
  1. Najstromszy spadek: `slope = (elev[i,j] - elev[neighbor]) / distance`
  2. Maksymalna akumulacja: sąsiad z najwyższym `acc`
  3. Dowolny prawidłowy sąsiad
- Ponowna kalkulacja akumulacji po naprawach

### 1.4 Nachylenie i ekspozycja

**Nachylenie:** `compute_slope()` (linie 1084-1122)
- Algorytm: operator Sobla (`scipy.ndimage.sobel`)
- Wzór: `slope_percent = sqrt(dx² + dy²) × 100`
- Gradient: `dy = sobel(dem, axis=0) / (8 × cellsize)`

**Ekspozycja:** `compute_aspect()` (linie 1125-1183)
- Wzór: `aspect_deg = arctan2(-dx, dy)` (0°=N, zgodnie z zegarem)
- Tereny płaskie: `aspect = -1.0`

### 1.5 Rząd Strahlera

**Funkcja:** `compute_strahler_from_fdir()` (linie 1271-1329)
- Maska cieków: `acc >= stream_threshold`
- Algorytm: `pyflwdir.FlwdirRaster.stream_order(type="strahler", mask=stream_mask)`
- Komórki niebędące ciekiem: `strahler = 0`

### 1.6 Wektoryzacja cieków

**Funkcja:** `vectorize_streams()` (linie 1395-1588)

**Algorytm:**
1. **Znalezienie źródeł** (headwaters): komórki ciekowe bez napływu z góry
2. **Śledzenie segmentów**: od źródła w dół, dopóki `strahler_order` się nie zmieni
3. **Przerwanie** na: skrzyżowaniu, ujściu, odwiedzonej komórce, granicy cieku

**Atrybuty segmentu:**
- `coords`: lista (x, y) w EPSG:2180
- `strahler_order`: int
- `length_m`: suma odległości euklidesowych między wierzchołkami
- `upstream_area_km2`: `acc[end] × cell_area / 1e6`
- `mean_slope_percent`: średnie nachylenie na segmencie

**Label raster:** opcjonalnie maluje `label_raster[r, c] = seg_id` (1-based) — używany do delimitacji zlewni cząstkowych

### 1.7 Delimitacja zlewni cząstkowych

**Funkcja:** `delineate_subcatchments()` (linie 1687-1740)
- Algorytm: `pyflwdir.FlwdirRaster.basins(idxs=stream_idxs, ids=segment_ids)` — propagacja etykiet upstream po grafie D8 w C/Numba (ADR-016)
- Złożoność: O(n), jedno przejście downstream→upstream po posortowanej sekwencji
- Seed: komórki ciekowe z `label_raster` (1-based segment_id z `vectorize_streams()`)
- Wzór: `label[cell] = label[downstream_stream_cell]`

### 1.8 Poligonizacja zlewni cząstkowych

**Funkcja:** `polygonize_subcatchments()` (linie 1773-1891)
- `rasterio.features.shapes()` z transformacją
- Grupowanie po `segment_idx`, `unary_union()`
- Uproszczenie: `merged.simplify(cellsize/2, preserve_topology=True)`
- Statystyki strefowe:
  - `area_km2 = n_cells × cell_area_km2`
  - `mean_elevation_m = mean(dem[cell_mask])`
  - `mean_slope_percent = mean(slope[cell_mask])`

### 1.9 Wstawienie do bazy danych

Wszystkie inserty używają tego samego wzorca **COPY przez tabelę tymczasową**:

1. Tworzenie tabeli tymczasowej (`temp_flow_import` / `temp_stream_import` / `temp_catchments_import`)
2. Budowanie bufora TSV w pamięci
3. `COPY temp_table FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '')`
4. `INSERT INTO target_table (...) SELECT ST_SetSRID(ST_GeomFromText(wkt), 2180), ... FROM temp_table`

#### Sieć przepływów (flow_network)
**Funkcja:** `insert_records_batch()` (linie 2106-2289)
- Wzór na ID: `cell_id = row × ncols + col + 1` (1-based)
- Downstream ID: z macierzy D8 fdir
- Indeksy przebudowywane po insercie: GIST (geom), B-tree (downstream_id, is_stream, flow_accumulation, strahler_order)

#### Segmenty cieków (stream_network)
**Funkcja:** `insert_stream_segments()` (linie 1591-1684)
- WKT: `LINESTRING(x1 y1, x2 y2, ...)`
- Kolumna `threshold_m2` identyfikuje próg FA

#### Zlewnie cząstkowe (stream_catchments)
**Funkcja:** `insert_catchments()` (linie 1894-1986)
- WKT: `MULTIPOLYGON(...)` po `unary_union`

---

## Faza 2: Wyznaczanie zlewni (runtime)

**Moduł:** `backend/core/watershed.py` (509 linii)
**Endpoint:** `POST /api/delineate-watershed`

### 2.1 Znalezienie najbliższego cieku

**Funkcja:** `find_nearest_stream()` (linie 69-144)

```sql
SELECT id, ST_X(geom) as x, ST_Y(geom) as y,
       elevation, flow_accumulation, slope, downstream_id,
       cell_area, is_stream,
       ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as distance
FROM flow_network
WHERE is_stream = TRUE
  AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), :max_dist)
ORDER BY distance LIMIT 1
```

- `max_distance_m = 1000` — maksymalny promień szukania

### 2.2 Kontrola rozmiaru (pre-flight)

**Funkcja:** `check_watershed_size()` (linie 147-193)
- `estimated_cells = flow_accumulation + 1`
- Limit: `max_cells = 2 000 000` — zapobiega OOM
- Jedno zapytanie PK (<1ms)

### 2.3 Rekurencyjne przejście w górę (CTE)

**Funkcja:** `traverse_upstream()` (linie 196-310)

```sql
WITH RECURSIVE upstream AS (
    -- Baza: komórka ujściowa
    SELECT id, ST_X(geom) as x, ST_Y(geom) as y,
           elevation, flow_accumulation, slope,
           downstream_id, cell_area, is_stream, 1 as depth
    FROM flow_network WHERE id = :outlet_id

    UNION ALL

    -- Rekurencja: komórki gdzie downstream_id = bieżący id
    SELECT f.id, ST_X(f.geom) as x, ST_Y(f.geom) as y,
           f.elevation, f.flow_accumulation, f.slope,
           f.downstream_id, f.cell_area, f.is_stream, u.depth + 1
    FROM flow_network f
    INNER JOIN upstream u ON f.downstream_id = u.id
    WHERE u.depth < :max_depth
)
SELECT ... FROM upstream LIMIT :max_rows
```

- `max_depth = 10 000`
- Wyjście: `list[FlowCell]` — wszystkie komórki zlewni

### 2.4 Budowanie granicy zlewni

**Funkcja:** `build_boundary_polygonize()` (linie 313-411)

**Algorytm: poligonizacja rastrowa:**
1. Wyznaczenie zasięgu (min/max XY) z buforem 1 komórki
2. Tworzenie binarnego rastra (0/1) z komórek zlewni
3. `rasterio.features.shapes(raster, mask=raster==1, transform=transform)`
4. `unary_union(polygons)` — połączenie wieloczęściowych granic
5. Jeśli MultiPolygon → wybór największego poligonu

### 2.5 Obliczenie powierzchni

**Funkcja:** `calculate_watershed_area_km2()` (linie 481-508)

```python
total_area_m2 = Σ(cell.cell_area for cell in cells)
area_km2 = total_area_m2 / 1 000 000
```

---

## Faza 3: Parametry morfometryczne

**Moduł:** `backend/core/morphometry.py` (666 linii)

### 3.1 Parametry podstawowe

| Parametr | Wzór | Funkcja |
|----------|-------|---------|
| **Obwód** | `perimeter_km = boundary.length / 1000` | `calculate_perimeter_km()` (18-37) |
| **Długość zlewni** | `length_km = max(dist(cell, outlet)) / 1000` | `calculate_watershed_length_km()` (40-73) |
| **Min/Max/Średnia wys.** | `mean = np.average(elevations, weights=areas)` | `calculate_elevation_stats()` (76-112) |
| **Średnie nachylenie** | `mean_slope = np.average(slopes, weights=areas)` | `calculate_mean_slope()` (115-149) |

### 3.2 Ciek główny (reverse trace)

**Funkcja:** `find_main_stream()` (linie 152-262) — 257× szybciej niż oryginał

**Algorytm:**
1. Budowanie grafu napływu: `upstream_graph[downstream_id].append(cell_id)`
2. Śledzenie od ujścia w górę: na każdym kroku wybór sąsiada z najwyższą `flow_accumulation`
3. Obliczenia:
   - `channel_length_km = Σ(dist(pt[i], pt[i+1])) / 1000`
   - `channel_slope = (elev_highest - elev_outlet) / length_m`

### 3.3 Wskaźniki kształtu

**Funkcja:** `calculate_shape_indices()` (linie 265-329)

| Wskaźnik | Wzór | Interpretacja |
|----------|-------|--------------|
| **Współczynnik Graveliusa (Kc)** | `Kc = P / (2√(π·A))` | 1 = koło, >1 = wydłużona |
| **Wskaźnik kolistości Millera (Rc)** | `Rc = (4π·A) / P²` | 1 = koło, <1 = wydłużona |
| **Wskaźnik wydłużenia Schumma (Re)** | `Re = (2/L)·√(A/π)` | 1 = koło |
| **Współczynnik kształtu Hortona (Ff)** | `Ff = A / L²` | — |
| **Średnia szerokość (W)** | `W = A / L` | [km] |

Gdzie: A = area_km2, P = perimeter_km, L = length_km

### 3.4 Wskaźniki rzeźby terenu

**Funkcja:** `calculate_relief_indices()` (linie 332-374)

| Wskaźnik | Wzór | Interpretacja |
|----------|-------|--------------|
| **Relief Ratio (Rh)** | `Rh = (H_max - H_min) / (L × 1000)` | bezwymiarowy |
| **Całka hipsometryczna (HI)** | `HI = (H_mean - H_min) / (H_max - H_min)` | >0.6 młoda, 0.3-0.6 dojrzała, <0.3 stara |

### 3.5 Krzywa hipsometryczna

**Funkcja:** `calculate_hypsometric_curve()` (linie 377-437)

- 20 przedziałów wysokości (relative_height: 0.0 → 1.0)
- Dla każdego: `relative_area = Σ(areas[elev >= threshold]) / total_area`
- Format wyjścia: `[{relative_height: 1.0, relative_area: 0.0}, ..., {relative_height: 0.0, relative_area: 1.0}]`

### 3.6 Wskaźniki drenażu

**Funkcja:** `get_stream_stats_in_watershed()` (linie 440-491)

```sql
SELECT COALESCE(SUM(length_m), 0) AS total_length_m,
       COUNT(*) AS n_segments,
       COALESCE(MAX(strahler_order), 0) AS max_order
FROM stream_network
WHERE source = 'DEM_DERIVED'
  AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromText(:wkt), 2180))
```

| Wskaźnik | Wzór |
|----------|-------|
| **Gęstość drenażu (Dd)** | `Dd = total_stream_length_km / area_km2` [km/km²] |
| **Częstość cieków (Fs)** | `Fs = n_segments / area_km2` [1/km²] |
| **Ruggedness Number (Rn)** | `Rn = (relief_m / 1000) × Dd` |

### 3.7 Kompletny zestaw parametrów

**Funkcja:** `build_morphometric_params()` (linie 545-665)

Klucze wyjściowe:
```python
{
    "area_km2", "perimeter_km", "length_km",
    "elevation_min_m", "elevation_max_m", "elevation_mean_m",
    "mean_slope_m_per_m",
    "channel_length_km", "channel_slope_m_per_m",
    "cn",
    "compactness_coefficient",      # Kc
    "circularity_ratio",            # Rc
    "elongation_ratio",             # Re
    "form_factor",                  # Ff
    "mean_width_km",                # W
    "relief_ratio",                 # Rh
    "hypsometric_integral",         # HI
    "drainage_density_km_per_km2",  # Dd
    "stream_frequency_per_km2",     # Fs
    "ruggedness_number",            # Rn
    "max_strahler_order",
    "main_stream_coords",           # opcjonalnie
    "hypsometric_curve",            # opcjonalnie
}
```

---

## Faza 4: Dane opadowe

**Moduł:** `backend/core/precipitation.py` (321 linii)

### 4.1 Walidacja parametrów

| Parametr | Dozwolone wartości |
|----------|--------------------|
| **Czas trwania** | 15min, 30min, 1h, 2h, 6h, 12h, 24h |
| **Prawdopodobieństwo** | 1%, 2%, 5%, 10%, 20%, 50% |

### 4.2 Interpolacja IDW

**Funkcja:** `get_precipitation()` (linie 104-192)

```sql
WITH nearest AS (
    SELECT precipitation_mm,
           ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as dist
    FROM precipitation_data
    WHERE duration = :duration AND probability = :probability
    ORDER BY geom <-> ST_SetSRID(ST_Point(:x, :y), 2180)
    LIMIT 4
)
SELECT CASE
    WHEN MIN(dist) < 0.001
        THEN (SELECT precipitation_mm FROM nearest WHERE dist < 0.001 LIMIT 1)
    ELSE
        SUM(precipitation_mm / POWER(dist + 0.001, 2)) /
        SUM(1 / POWER(dist + 0.001, 2))
END FROM nearest
```

**Wzór IDW (Inverse Distance Weighting):**
- Potęga: p = 2
- 4 najbliższe stacje (KNN-GIST operator `<->`)
- `weight[i] = 1 / (distance[i] + 0.001)²`
- `precip = Σ(value[i] × weight[i]) / Σ(weight[i])`
- Jeśli `min(distance) < 0.001m` → dokładna wartość stacji

---

## Faza 5: Krzywa CN

**Moduły:** `backend/core/land_cover.py`, `cn_calculator.py`, `cn_tables.py`

### 5.1 Hierarchia wyznaczania CN

**Funkcja:** `determine_cn()` (land_cover.py, linie 256-347)

| Priorytet | Źródło | Warunek |
|-----------|--------|---------|
| 1 | Konfiguracja (explicit CN) | `config_cn is not None` |
| 2 | Baza danych (land_cover table) | Istnieją dane pokrycia terenu |
| 3 | Kartograf (HSG + Land Cover) | `use_kartograf=True` i dostępne dane |
| 4 | Wartość domyślna | `default_cn = 75` |

### 5.2 CN z pokrycia terenu w bazie

**Funkcja:** `calculate_weighted_cn()` (land_cover.py, linie 39-151)

```sql
WITH watershed AS (
    SELECT ST_SetSRID(ST_GeomFromWKB(decode(:wkb, 'hex')), 2180) AS geom
),
intersections AS (
    SELECT lc.category, lc.cn_value,
           ST_Area(ST_Intersection(lc.geom, w.geom)) AS intersection_area_m2
    FROM land_cover lc CROSS JOIN watershed w
    WHERE ST_Intersects(lc.geom, w.geom)
)
SELECT category, cn_value, SUM(intersection_area_m2) AS total_area_m2
FROM intersections GROUP BY category, cn_value ORDER BY total_area_m2 DESC
```

**Wzór:**
```
CN = round(Σ(cn_value[i] × area[i]) / Σ(area[i]))
CN = clamp(CN, 0, 100)
```

### 5.3 CN z Kartografa (HSG)

**Funkcja:** `calculate_cn_from_kartograf()` (cn_calculator.py, linie 228-334)

1. Konwersja granicy zlewni → BBox (z buforem 100m)
2. Pobranie HSG z SoilGrids (`Kartograf.HSGCalculator`): → dominujący typ gleby A/B/C/D
3. Pobranie pokrycia terenu (BDOT10k / CORINE): → statystyki procentowe
4. Lookup CN z tabeli `CN_LOOKUP_TABLE` per kategoria + HSG
5. Średnia ważona: `CN = Σ(cn[i] × percentage[i] / 100)`

### 5.4 Tabele CN

**Plik:** `cn_tables.py` (linie 32-84)

| Kategoria pokrycia | HSG A | HSG B | HSG C | HSG D |
|---------------------|-------|-------|-------|-------|
| Las / forest | 30 | 55 | 70 | 77 |
| Łąka / meadow | 30 | 58 | 71 | 78 |
| Grunt orny / arable | 72 | 81 | 88 | 91 |
| Zabudowa mieszk. | 77 | 85 | 90 | 92 |
| Zabudowa przem. | 89 | 92 | 94 | 95 |
| Droga | 98 | 98 | 98 | 98 |
| Woda | 100 | 100 | 100 | 100 |
| Inne / other | 60 | 70 | 80 | 85 |

---

## Faza 6: Generowanie hydrogramu

**Endpoint:** `POST /api/generate-hydrograph`
**Moduł:** `backend/api/endpoints/hydrograph.py` (299 linii)

### 6.1 Flow procesu

1. **Walidacja** parametrów (czas trwania, prawdopodobieństwo)
2. **Wyznaczenie zlewni** (find_nearest_stream → traverse_upstream)
3. **Kontrola limitu**: `area_km2 ≤ 250` (ograniczenie SCS-CN)
4. **Morfometria + CN** (build_morphometric_params, calculate_weighted_cn)
5. **Opad projektowy** (get_precipitation z IDW)
6. **Czas koncentracji** (calculate_tc)
7. **Hietogram** (rozkład opadu w czasie)
8. **Hydrogram** (splot z UH)

### 6.2 Czas koncentracji (tc)

**Metoda Kirpicha:**
```
tc = 0.0195 × L^0.77 × S^(-0.385)
```
Gdzie: L = długość cieku [m], S = spadek cieku [m/m]

**Metoda SCS Lag:**
```
lag = 0.057 × L^0.8 × ((1000/CN - 9)^0.7) / √S
tc = lag / 0.6
```

**Metoda Giandottiego:**
```
tc = (4√A + 1.5L) / (0.8 × √(H_mean - H_min))
```
Gdzie: A = powierzchnia [km²], L = długość [km], H = wysokość [m]

### 6.3 Hietogramy (rozkład opadu w czasie)

| Typ | Opis | Parametry |
|-----|------|-----------|
| **Beta** | Rozkład Beta | α=2.0, β=5.0 |
| **Block** | Opad równomierny | — |
| **Euler II** | Krzywa Eulera typu II | peak_position=0.33 |

Wszystkie implementują: `generate(total_mm, duration_min, timestep_min) → PrecipitationResult`

### 6.4 Metoda SCS-CN

**Maksymalna retencja (S):**
```
S = 25.4 × (1000/CN - 10)    [mm]
```

**Straty początkowe (Ia):**
```
Ia = 0.2 × S    [mm]
```

**Opad efektywny (Pe):**
```
jeśli P ≤ Ia:  Pe = 0
w.p.p.:        Pe = (P - Ia)² / (P - Ia + S)
```

### 6.5 Hydrogram jednostkowy SCS

**Czas do szczytu:**
```
tp = Δt/2 + 0.6 × tc
```

**Wydatek szczytowy:**
```
qp = C × A / tp
```
Gdzie: C = 2.08 (jednostki SI), A [km²], tp [h]

**Gałąź wstępująca (t ≤ tp):**
```
q(t) = qp × (t/tp)^2.3
```

**Gałąź opadająca (t > tp):**
```
q(t) = qp × exp(-α × (t - tp))
α = 1.67 / tp
```

### 6.6 Splot (convolution)

```
Q(t) = Σ[Pe(i) × UH(t - i×Δt) × A]    dla i = 0..len(Pe)-1
```

### 6.7 42 scenariusze

Generowane kombinatorycznie:
- **7 czasów trwania:** 15min, 30min, 1h, 2h, 6h, 12h, 24h
- **6 prawdopodobieństw:** 1%, 2%, 5%, 10%, 20%, 50%
- **Razem:** 7 × 6 = **42 scenariusze**

### 6.8 Bilans wodny (wynik)

| Parametr | Jednostka |
|----------|-----------|
| `total_precip_mm` | mm |
| `total_effective_mm` | mm |
| `runoff_coefficient` | — |
| `cn_used` | — |
| `retention_mm` | mm |
| `initial_abstraction_mm` | mm |
| `peak_discharge_m3s` | m³/s |
| `time_to_peak_min` | min |
| `total_volume_m3` | m³ |

---

## Schemat bazy danych

### flow_network
```sql
CREATE TABLE flow_network (
    id INTEGER PRIMARY KEY,          -- row × ncols + col + 1
    geom GEOMETRY(Point, 2180),      -- lokalizacja komórki
    elevation FLOAT,                 -- wysokość [m n.p.m.]
    flow_accumulation INTEGER,       -- akumulacja [komórki]
    slope FLOAT,                     -- nachylenie [%]
    downstream_id INTEGER REFERENCES flow_network(id),
    cell_area FLOAT,                 -- pole komórki [m²]
    is_stream BOOLEAN,               -- czy komórka jest ciekiem
    strahler_order SMALLINT          -- rząd Strahlera (NULL jeśli nie-ciek)
);
-- Indeksy: GIST(geom), B-tree(downstream_id, is_stream, flow_accumulation, strahler_order)
```

### stream_network
```sql
CREATE TABLE stream_network (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(LineString, 2180),  -- geometria segmentu
    strahler_order INTEGER,
    length_m FLOAT,
    upstream_area_km2 FLOAT,
    mean_slope_percent FLOAT,
    source TEXT,                      -- 'DEM_DERIVED' lub 'BDOT10k'
    threshold_m2 INTEGER             -- próg FA użyty do generacji
);
-- Indeksy: GIST(geom), B-tree(threshold_m2, strahler_order), B-tree(upstream_area_km2)
```

### stream_catchments
```sql
CREATE TABLE stream_catchments (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(MultiPolygon, 2180),
    segment_idx INTEGER,              -- powiązany segment cieku
    threshold_m2 INTEGER,
    area_km2 FLOAT,
    mean_elevation_m FLOAT,
    mean_slope_percent FLOAT,
    strahler_order INTEGER
);
-- Indeksy: GIST(geom), B-tree(threshold_m2, strahler_order), B-tree(area_km2)
```

### precipitation_data
```sql
CREATE TABLE precipitation_data (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(Point, 2180),       -- lokalizacja stacji
    duration TEXT,                     -- '15min', '1h', itd.
    probability INTEGER,              -- 1, 2, 5, 10, 20, 50
    precipitation_mm FLOAT
);
-- Indeksy: GIST(geom), B-tree(duration, probability)
```

### land_cover
```sql
CREATE TABLE land_cover (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(MultiPolygon, 2180),
    category TEXT,                    -- 'las', 'łąka', 'grunt_orny', itd.
    cn_value INTEGER,                 -- 0-100
    imperviousness FLOAT,             -- 0-1
    bdot_class TEXT
);
-- Indeks: GIST(geom)
```

---

## Wydajność

### Preprocessing (jednorazowo)
| Operacja | Czas |
|----------|------|
| Wczytanie NMT | ~0.5s (1000×1000) |
| Depresje + fdir (pyflwdir) | ~1-2s |
| Akumulacja | ~0.5-1s |
| Nachylenie | ~0.2s |
| Strahler | ~0.5s |
| Wektoryzacja cieków | ~2-5s |
| Insert do bazy (COPY) | ~15s (1M komórek) |
| **Razem per arkusz** | **~3-8 min** |

### Runtime (per żądanie)
| Operacja | Czas |
|----------|------|
| Find nearest stream | <1ms (GIST + ST_DWithin) |
| Pre-flight size check | <1ms (PK lookup) |
| Traverse upstream (CTE) | 1-5s (10k-100k komórek) |
| Build boundary (polygonize) | 0.5-2s |
| Morfometria | <0.5s |
| Opad IDW | <5ms (KNN-GIST) |
| CN z land_cover | 0.1-1s (spatial intersection) |
| **Łącznie wyznaczanie zlewni** | **2-10s** |
| Hydrogram (Hydrolog) | <0.1s (numpy) |

### Pamięć
| Kontekst | Zużycie |
|----------|---------|
| Preprocessing (1000×1000 float32) | ~64 MB peak |
| Runtime — typowa zlewnia (50k komórek) | ~5 MB |
| Runtime — duża zlewnia (1M komórek) | ~100 MB |

---

## Podsumowanie algorytmów

| Nr | Algorytm | Źródło |
|----|----------|--------|
| 1 | Wypełnianie depresji | Wang & Liu 2006 (pyflwdir) |
| 2 | Kierunki odpływu | D8 steepest descent |
| 3 | Akumulacja spływu | Sortowanie topologiczne (Kahn) + BFS |
| 4 | Rząd Strahlera | Strahler 1952 |
| 5 | Wektoryzacja cieków | Śledzenie od źródeł do skrzyżowań |
| 6 | Delimitacja zlewni cząstkowych | pyflwdir.basins() — propagacja upstream (ADR-016) |
| 7 | Budowanie granicy zlewni | Poligonizacja rastrowa (rasterio) |
| 8 | Ciek główny | Reverse trace (max akumulacja) |
| 9 | Interpolacja opadów | IDW (p=2, 4 najbliższe stacje) |
| 10 | Krzywa CN | Średnia ważona powierzchnią |
| 11 | Przejście w górę | Rekurencyjna CTE (PostgreSQL) |
| 12 | Bulk load do bazy | PostgreSQL COPY przez temp tables |
| 13 | Odpływ SCS-CN | Metoda SCS z konwolucją |
| 14 | Czas koncentracji | Kirpich / SCS Lag / Giandotti |

---

## Limity bezpieczeństwa

| Parametr | Wartość | Lokalizacja |
|----------|---------|-------------|
| MAX_WATERSHED_CELLS | 2 000 000 | watershed.py:22 |
| MAX_STREAM_DISTANCE_M | 1 000 | watershed.py:25 |
| MAX_RECURSION_DEPTH | 10 000 | watershed.py:28 |
| HYDROGRAPH_AREA_LIMIT_KM2 | 250.0 | hydrograph.py (SCS-CN) |
