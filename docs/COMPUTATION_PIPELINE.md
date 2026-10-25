# Procedura obliczeniowa — Hydrograf

> Wersja: 1.4 | Data: 2026-10-25

Kompletny opis pipeline'u obliczeniowego backendu: od surowego NMT przez preprocessing, wyznaczanie zlewni, parametry fizjograficzne, aż po generowanie hydrogramu.

---

## Spis treści

1. [Faza 1: Preprocessing NMT](#faza-1-preprocessing-nmt)
2. [Faza 1b: Graf zlewni cząstkowych (startup API)](#faza-1b-graf-zlewni-cząstkowych-startup-api)
3. [Faza 2: Wyznaczanie zlewni (runtime)](#faza-2-wyznaczanie-zlewni-runtime)
4. [Faza 3: Parametry morfometryczne](#faza-3-parametry-morfometryczne)
5. [Faza 4: Dane opadowe](#faza-4-dane-opadowe)
6. [Faza 5: Krzywa CN](#faza-5-krzywa-cn)
7. [Faza 6: Generowanie hydrogramu](#faza-6-generowanie-hydrogramu)
8. [Schemat bazy danych](#schemat-bazy-danych)
9. [Wydajność](#wydajność)

---

## Faza 1: Preprocessing NMT

**Skrypt:** `backend/scripts/process_dem.py` (~700 linii — cienki orkiestrator)
**Moduły core:** `raster_io`, `hydrology`, `morphometry_raster`, `stream_extraction`, `db_bulk`, `zonal_stats`
**Uruchamianie:** jednorazowo per arkusz NMT, ~3-8 min

> **Uwaga:** Skrypt `process_dem.py` został zrefaktoryzowany z ~2800 linii monolitu do ~700 linii cienkiego orkiestratora, ktory deleguje logike do 7 modulow w `backend/core/` (ADR-017). Funkcje opisane ponizej naleza teraz do odpowiednich modulow core.

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

#### ~~Sieć przepływów (flow_network)~~ — USUNIETA (ADR-028, migracja 015)

> Krok pominięty — tabela `flow_network` została usunięta. Pipeline nie importuje danych per-piksel do bazy.

#### Segmenty cieków (stream_network)
**Funkcja:** `insert_stream_segments()` (linie 1591-1684)
- WKT: `LINESTRING(x1 y1, x2 y2, ...)`
- Kolumna `threshold_m2` identyfikuje próg FA

#### Zlewnie cząstkowe (stream_catchments)
**Funkcja:** `insert_catchments()` (linie 1894-1986)
- WKT: `MULTIPOLYGON(...)` po `unary_union`

---

## Faza 1b: Graf zlewni cząstkowych (startup API)

**Moduł:** `backend/core/catchment_graph.py` (ADR-021)
**Ładowanie:** automatycznie przy starcie serwera API (jednorazowo)

### Kontekst

Dane z preprocessingu (Faza 1) — tabela `stream_catchments` (~44k wierszy) — zawierają gotowe poligony zlewni cząstkowych z pre-computed statystykami. Zamiast wykonywać kosztowne operacje rastrowe na 19.7M komórkach w runtime, graf zlewni cząstkowych ładuje te dane do pamięci przy starcie API i umożliwia szybkie przejście BFS po ~44k węzłach.

### 1b.1 Struktura grafu

**Klasa:** `CatchmentGraph`

| Element | Typ | Opis |
|---------|-----|------|
| **Węzły** | ~44k | Jeden węzeł = jedna zlewnia cząstkowa (per segment cieku per próg FA) |
| **Krawędzie** | upstream adjacency | `adj[i, j] = 1` oznacza, że węzeł j spływa do węzła i |
| **Macierz sąsiedztwa** | `scipy.sparse.csr_matrix` | Rzadka macierz CSR — wydajny BFS |
| **Atrybuty węzłów** | `numpy arrays` (float32/int32) | `area_km2`, `elev_min/max/mean`, `slope_mean`, `perimeter_km`, `stream_length_km`, `strahler` |
| **Lookup** | `dict[(threshold_m2, segment_idx) → idx]` | Szybkie mapowanie klucza biznesowego na indeks wewnętrzny |
| **Histogramy wysokości** | `list[dict]` (JSONB z bazy) | Histogram ze stałym interwałem 1m — mergowalny przy agregacji |

### 1b.2 Ładowanie danych

**Metoda:** `CatchmentGraph.load(db: Session)`

1. Odczyt wszystkich wierszy z `stream_catchments` (w partiach po 50k)
2. Alokacja numpy arrays dla atrybutów (pre-allocated, ~0.5 MB łącznie)
3. Budowa macierzy sąsiedztwa CSR z kolumny `downstream_segment_idx`
4. Zapis lookup dict `(threshold_m2, segment_idx) → internal_idx`

**Czas ładowania:** ~1-2s przy starcie API
**Zużycie pamięci:** ~0.5 MB (vs ~1 GB dla rastrowego `flow_graph`)

### 1b.3 Przejście BFS (runtime)

**Metoda:** `CatchmentGraph.traverse_upstream(threshold_m2, segment_idx)`

1. Lookup węzła startowego: `(threshold_m2, segment_idx) → idx`
2. BFS po macierzy CSR: `scipy.sparse.csgraph.breadth_first_order(adj, idx)`
3. Agregacja statystyk z numpy arrays (area, elevation, slope) — wektoryzowane operacje
4. Merge histogramów wysokości dla krzywej hipsometrycznej

**Czas przejścia:** ~5-50ms (w zależności od rozmiaru zlewni)

### 1b.4 Korzyści architektoniczne

| Aspekt | Przed (raster-based) | Po (CatchmentGraph) |
|--------|----------------------|---------------------|
| **Czas traversal** | 200ms - 5s | 5 - 50ms |
| **Pamięć runtime** | ~1 GB (flow_graph) | ~0.5 MB |
| **Operacje rastrowe** | BFS po 19.7M komórkach | Zero — pre-computed stats |
| **Złożoność kodu** | Budowanie granicy z pikseli | `ST_Union` gotowych poligonów |

---

## Faza 2: Wyznaczanie zlewni (runtime)

**Moduł:** `backend/core/watershed_service.py` (ADR-022)
**Endpoint:** `POST /api/delineate-watershed`

> **Uwaga (ADR-022, ADR-028):** Od 2026-02-14 endpointy API (`watershed.py`, `hydrograph.py`, `select_stream.py`) korzystają z CatchmentGraph (~44k węzłów, ~0.5 MB) zamiast FlowGraph (~19.7M komórek, ~1 GB). Tabela `flow_network` została usunięta (migracja 015), a funkcje działające na komórkach (`FlowCell`, `build_boundary`, `build_boundary_polygonize`, `calculate_watershed_area_km2` i funkcje komórkowe `core/morphometry.py`) usunięto razem z `core/watershed.py`. Skrypt `scripts/analyze_watershed.py` wywołuje tę samą funkcję trasy co endpoint.

### 2.1 Znalezienie zlewni cząstkowej punktu

**Funkcja:** `CatchmentGraph.find_catchment_at_point()` — `ST_Contains` na `stream_catchments`, zwraca wewnętrzny indeks węzła grafu.

### 2.2 Przejście w górę (BFS)

**Funkcja:** `CatchmentGraph.traverse_upstream()` — BFS po macierzy sparse CSR, zwraca indeksy wszystkich zlewni cząstkowych powyżej punktu (patrz 1b.3).

### 2.3 Granica zlewni

**Funkcja:** `watershed_service.merge_catchment_boundaries()` — łączenie granic zlewni cząstkowych (`ST_UnaryUnion`: bezpośrednio, partiami lub z grubszym progiem), potem `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3)` (ADR-032). Dla dużych zlewni `cascade_escalate()` podnosi próg.

### 2.4 Powierzchnia

**Funkcja:** `CatchmentGraph.aggregate_stats()["area_km2"]` — suma `area_km2` zlewni cząstkowych z `traverse_upstream()`.

---

## Faza 3: Parametry morfometryczne

**Moduły:** `backend/core/watershed_service.py` (`build_morph_dict_from_graph()`), `backend/core/catchment_graph.py` (`aggregate_stats()`, `trace_main_channel()`, `aggregate_hypsometric()`), `backend/core/morphometry.py` (`calculate_shape_indices()`)

Parametry liczy `build_morph_dict_from_graph()` z wartości wstępnie policzonych w grafie zlewni cząstkowych; w runtime nie ma operacji na rastrach (poza próbkowaniem `stream_distance.tif` dla długości ścieżek spływu).

### 3.1 Parametry podstawowe

| Parametr | Źródło |
|----------|--------|
| **Powierzchnia** | `aggregate_stats()["area_km2"]` (suma zlewni cząstkowych) |
| **Obwód** | `perimeter_km = boundary.length / 1000` (granica po scaleniu i wygładzeniu) |
| **Długość zlewni** | `hydraulic_length_km` z `aggregate_stats()` (najdłuższa ścieżka spływu); gdy brak — `compute_watershed_length()` (maks. odległość od ujścia do wierzchołka granicy) |
| **Min/Max/Średnia wys.** | `aggregate_stats()`: min, max, średnia ważona powierzchnią |
| **Średnie nachylenie** | `aggregate_stats()["mean_slope_m_per_m"]` (średnia ważona powierzchnią) |

### 3.2 Ciek główny (trace wg Strahlera)

**Metoda:** `CatchmentGraph.trace_main_channel()` (ADR-029) w `core/catchment_graph.py`, wywoływana z `watershed_service.build_morph_dict_from_graph()`; geometrię składa `watershed_service.get_main_channel_feature_collection()`.

**Algorytm:**
1. Start od outlet node (wewnętrzny indeks)
2. Na każdej konfluencji wybór gałęzi: max Strahler → max stream_length → max area
3. Sumowanie `stream_length_km` wzdłuż ścieżki
4. Obliczenia:
   - `channel_length_km = Σ(stream_length_km[node])` wzdłuż głównego cieku
   - `channel_slope = (elev_max[head] - elev_min[outlet]) / (length_km * 1000)`

**Uwaga:** `aggregate_stats()["stream_length_km"]` zwraca sumę CAŁEJ sieci. Długość głównego cieku pochodzi wyłącznie z `trace_main_channel()`.

### 3.3 Wskaźniki kształtu

**Funkcja:** `morphometry.calculate_shape_indices()`

| Wskaźnik | Wzór | Interpretacja |
|----------|-------|--------------|
| **Współczynnik Graveliusa (Kc)** | `Kc = P / (2√(π·A))` | 1 = koło, >1 = wydłużona |
| **Wskaźnik kolistości Millera (Rc)** | `Rc = (4π·A) / P²` | 1 = koło, <1 = wydłużona |
| **Wskaźnik wydłużenia Schumma (Re)** | `Re = (2/L)·√(A/π)` | 1 = koło |
| **Współczynnik kształtu Hortona (Ff)** | `Ff = A / L²` | — |
| **Średnia szerokość (W)** | `W = A / L` | [km] |

Gdzie: A = area_km2, P = perimeter_km, L = length_km

### 3.4 Wskaźniki rzeźby terenu

**Funkcja:** `build_morph_dict_from_graph()`

| Wskaźnik | Wzór | Interpretacja |
|----------|-------|--------------|
| **Relief Ratio (R)** | `R = (H_max - H_min) / √A` [‰] | A w km² |
| **Spadek działu wodnego (Rp)** | `Rp = (H_max - H_min) / P` [‰] | P w km |
| **Całka hipsometryczna (HI)** | `HI = (H_mean - H_min) / (H_max - H_min)` | >0.6 młoda, 0.3-0.6 dojrzała, <0.3 stara |

### 3.5 Krzywa hipsometryczna

**Funkcja:** `CatchmentGraph.aggregate_hypsometric()`

- Histogramy wysokości zlewni cząstkowych scalane na osi wysokości bezwzględnych
- 20 punktów (`relative_height`: 0.0 → 1.0)
- Format wyjścia: `[{relative_height: ..., relative_area: ...}, ...]`

### 3.6 Wskaźniki drenażu

**Funkcja:** `CatchmentGraph.aggregate_stats()` (tylko cieki rzeczywiste, dopasowane do BDOT10k — ADR-044)

| Wskaźnik | Wzór |
|----------|-------|
| **Gęstość drenażu (Dd)** | `Dd = bdot_stream_length_km / area_km2` [km/km²] |
| **Częstość cieków (Fs)** | `Fs = bdot_stream_count / area_km2` [1/km²] |
| **Ruggedness Number (Rn)** | `Rn = ((H_max - H_min) / 1000) × Dd` |

### 3.7 Kompletny zestaw parametrów

**Funkcja:** `watershed_service.build_morph_dict_from_graph()`

Klucze wyjściowe (wybór):
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
    "relief_ratio",                 # R
    "hypsometric_integral",         # HI
    "drainage_density_km_per_km2",  # Dd
    "stream_frequency_per_km2",     # Fs
    "ruggedness_number",            # Rn
    "max_strahler_order",
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
**Tabele:** `land_cover`, `soil_hsg` (migracja 016 — grupy glebowe HSG)

### 5.1 Hierarchia wyznaczania CN

**Funkcja:** `determine_cn()` (`core/land_cover.py`)

| Priorytet | Źródło | Warunek |
|-----------|--------|---------|
| 1 | Konfiguracja (explicit CN) | `config_cn is not None` |
| 2 | Baza danych (land_cover table) | Istnieją dane pokrycia terenu |
| 3 | Kartograf (HSG + Land Cover) | `use_kartograf=True`, `boundary_wgs84` and `cache_dir` given, Kartograf importable (`calculate_cn_from_kartograf()` returns a result) |
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

**Funkcja:** `calculate_cn_from_kartograf(boundary_wgs84, cache_dir, use_default_land_cover=True, teryt=None)` (`core/cn_calculator.py`); only `scripts/analyze_watershed.py` calls it, through `determine_cn()`.

1. The boundary of the watershed is converted to a `BBox` in EPSG:2180 with a buffer of 100 m (`convert_boundary_to_bbox`).
2. The HSG of the area (`get_hsg_from_soilgrids`): `kartograf.calculate_hsg(output_dir=<temporary directory>, bbox=, depth="0-5cm", cache=False)` downloads the SoilGrids clay, sand and silt rasters, classifies the USDA texture of each cell into the groups A-D and writes the HSG raster as a plain file that exists only for this call; `kartograf.hsg_statistics` counts the cells per group. The dominant group is the one with the largest share of the cells that have data. A failure of Kartograf (`KartografError`) or an area without data gives the group B.
3. The land cover (`get_land_cover_stats`): `download_bdot10k` takes the BDOT10k package of every county that the bbox intersects from the Kartograf store `<cache_dir>/kartograf` (a package that is already local is used without a request); the area of every `PT*` layer clipped to the bbox gives the shares in percent per category, each county by its part in the bbox. Without data the default land cover is used when `use_default_land_cover` is true.
4. The CN of each category and the dominant group comes from `CN_LOOKUP_TABLE`.
5. The weighted mean: `CN = Σ(cn[i] × percentage[i] / 100)`.

> **Note (ADR-061):** `HSGCalculator` and `LandCoverManager` are no longer public in Kartograf, and `check_hsg_cache` and `HsgCacheStaleError` of `scripts/bootstrap.py` are gone together with `soil_hsg/hsg_poland.tif`. The HSG raster of the bootstrap (the `soil_hsg` table) is a version of the Kartograf store (`hsg/`): its sidecar records the Kartograf version and the source rasters with their hashes. The raster of this function is not kept, and `hsg_statistics` of a file without a sidecar counts the whole raster, so the cells at the edge of the bbox count in full, as in Kartograf 0.7.0 (ADR-061, erratum of 2026-10-25).

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
**Moduł:** `backend/api/endpoints/hydrograph.py`

### 6.1 Flow procesu

1. **Walidacja** parametrów (czas trwania, prawdopodobieństwo)
2. **Wyznaczenie zlewni** (CatchmentGraph BFS → `watershed_service`, ADR-022)
3. **Kontrola limitu**: `area_km2 ≤ 250` (ograniczenie SCS-CN)
4. **Morfometria + CN** (build_morph_dict_from_graph, get_land_cover_for_boundary)
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

### 6.7 432 scenariusze

Generowane kombinatorycznie:
- **16 duracji:** 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h
- **27 prawdopodobieństw:** 0.01%, 0.02%, 0.03%, 0.05%, 0.1%, 0.2%, 0.3%, 0.5%, 1%, 2%, 3%, 5%, 10%, 20%, 30%, 40%, 50%, 60%, 70%, 80%, 90%, 95%, 98%, 98.5%, 99%, 99.5%, 99.9%
- **Razem:** 16 × 27 = **432 scenariusze**

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

### ~~flow_network~~ — USUNIETA (ADR-028, migracja 015)

> Tabela usunięta. Przechowywała dane per-piksel DEM (~39.4M wierszy). Wszystkie endpointy API korzystają z `stream_network`, `stream_catchments` i CatchmentGraph.

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
    threshold_m2 INTEGER,            -- próg FA użyty do generacji
    segment_idx INTEGER              -- 1-based per threshold (migracja 014, ADR-026)
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
    duration TEXT,                     -- '5min'...'72h' (16 wartości)
    probability DOUBLE PRECISION,     -- 0.01...99.9 (27 wartości)
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
| Traverse upstream (CatchmentGraph BFS) | 5-50ms (~44k węzłów, ADR-021) |
| Morfometria | <0.5s |
| Opad IDW | <5ms (KNN-GIST) |
| CN z land_cover | 0.1-1s (spatial intersection) |
| **Łącznie wyznaczanie zlewni** | **2-10s** |
| Hydrogram (Hydrolog) | <0.1s (numpy) |

### Startup API
| Operacja | Czas | Pamięć |
|----------|------|--------|
| Ładowanie CatchmentGraph (~44k węzłów) | ~1-2s | ~0.5 MB |

### Pamięć
| Kontekst | Zużycie |
|----------|---------|
| Preprocessing (1000×1000 float32) | ~64 MB peak |
| CatchmentGraph (startup API) | ~0.5 MB |

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
| 7 | Granica zlewni | `ST_UnaryUnion` granic zlewni cząstkowych + wygładzanie (ADR-032) |
| 8 | Ciek główny | `CatchmentGraph.trace_main_channel()` (Strahler → długość → powierzchnia) |
| 9 | Interpolacja opadów | IDW (p=2, 4 najbliższe stacje) |
| 10 | Krzywa CN | Średnia ważona powierzchnią |
| 11 | Przejście w górę | BFS po grafie zlewni cząstkowych (`CatchmentGraph.traverse_upstream`) |
| 12 | Bulk load do bazy | PostgreSQL COPY przez temp tables |
| 13 | Odpływ SCS-CN | Metoda SCS z konwolucją |
| 14 | Czas koncentracji | Kirpich / SCS Lag / Giandotti |
| 15 | Graf zlewni cząstkowych | BFS po sparse CSR (~44k węzłów, ADR-021) |

---

## Limity bezpieczeństwa

| Parametr | Wartość | Lokalizacja |
|----------|---------|-------------|
| HYDROGRAPH_AREA_LIMIT_KM2 | 250.0 | hydrograph.py (SCS-CN) |
