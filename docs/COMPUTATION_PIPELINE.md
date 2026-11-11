# Procedura obliczeniowa — Hydrograf

> Wersja: 1.7 | Data: 2026-11-11

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
8. [Phase 7: Network delineation at control points (runtime)](#phase-7-network-delineation-at-control-points-runtime)
9. [Schemat bazy danych](#schemat-bazy-danych)
10. [Wydajność](#wydajność)

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
- Algorithm: a numba pass per iteration over the 3×3 window of every nodata cell, the neighbour values from the DEM before the pass (results as the earlier `scipy.ndimage.generic_filter`)
- Warunek: komórka nodata z ≥5 prawidłowymi sąsiadami
- Wzór: `new_value = mean(valid_neighbors)`
- Maksymalnie 3 iteracje
- Enclosed nodata (ADR-073, opt-in: `dem.fill_enclosed_nodata` of `config.yaml`, default `false`): with `true` every nodata area that does not reach the frame of the raster (a sheet missing from the mosaic) is first interpolated from the data around it (GDAL's inverse distance weighting, `interpolate_enclosed_nodata()`), so the depression fill fills it like ground and every cell drains to the outer edge of the data; with `false` such an area stays nodata and is an outlet of the fill (Krok 4)

### 1.2a Burning and smoothing the streams, endorheic lakes

**Functions:** `burn_streams_into_dem()`, `smooth_streams_monotonic()`, `classify_endorheic_lakes()` (`core/hydrology.py`; with `--burn-streams`)
- Burning: the BDOT10k lines of `dem.stream_burning` (`all`: OT_SWRS_L, OT_SWKN_L, OT_SWRM_L; `main`: the main watercourses) and the water bodies (OT_PTWP_A) are lowered by `burn_depth_m` (2 m).
- Direction of a burned line (ADR-077, `_line_directions`), on the burned DEM; the first rule that decides it:
  1. the mouth: along the lines of its MPHP watercourse K, towards the nearest node where a line whose MPHP identifier is a proper prefix of K (its receiver) begins or ends;
  2. the DEM of the whole watercourse (the lines of one MPHP identifier, else of one name, joined where exactly two of them meet), for a watercourse digitized both ways: when the DEM along it, without its artificial connectors, rises or falls by more than 0.5 m between the lowest values of its first and last quarter, its lower end is downstream and every block (run of lines digitized the same way) digitized the other way is reversed, unless the DEM along the block falls more than 2 m the way it is digitized (the guard);
  3. the DEM of the line (ADR-072): reversed when the DEM rises along it by more than 2 m over at least 200 m;
  4. the digitized direction.
  An artificial connector through a lake (`CECHAGEOMETRII = 'sztuczny łącznik'`) never takes its direction from the DEM along it.
- Smoothing (ADR-072): the lines in the order of the flow, each beginning below the lowest value reached at its first node and descending strictly (a higher cell is cut, an equal one lowered by one float32 step); gaps up to 50 m between two features of a watercourse are bridged. The diagnostics count the reversed lines by rule (`segments_reversed_by_mouth`, `_by_watercourse`, `_by_rise`) and the blocks kept by the guard.
- Endorheic lakes (`--waterbody-mode auto`): a water body that any watercourse line of the three layers leaves is exorheic, else endorheic and gets a drain point. A burned line flows the way the smoothing takes it (`flow_lines`, the one source of the directions); any other line the way it is digitized unless the DEM along it rises by more than 2 m on at least 200 m.

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
- Method: `pyflwdir.FlwdirRaster.upstream_area(unit="cell")` on the one FlwdirRaster of the run, its cells ordered by `order_cells(method="sort")` (pyflwdir's default walk builds a matrix of 7–8 upstream cells per cell)
- Wzór: `acc[cell] = 1 + Σ(acc[upstream_cells])`
- Wyjście: int32 array (liczba komórek, nie m²)

#### Krok 4: Naprawa wewnętrznych zlewów (internal sinks)
- Definition: an internal sink is a cell without a D8 direction (0, -1, any other value) whose 8 neighbours all have data (a numba pass, `_internal_sinks`). A pit on the frame of the raster or next to nodata (the border of the data, an internal nodata area, a drain point of a lake) is an **outlet**: `fill_depressions(outlets="edge")` drains the area through such cells, and it leaves no other pit. The old definition (every valid cell off the frame without a direction) took these outlets for sinks, and the `max_acc` strategy pointed each at a neighbour that drains back into it: a pair of cells draining into each other
- On pyflwdir's output no cell is an internal sink, so nothing is fixed, `fdir` is pyflwdir's grid (the grid of `flw`, of the flow distance, Strahler and the sub-catchments) and `acc` is pyflwdir's `upstream_area`. The step stays a safety net for flow directions from elsewhere
- Hierarchia naprawy; each strategy looks only at the neighbours whose flow does not come back to the sink (a numba walk down the flow of the neighbour, `_drains_into`, with the fixes made so far), so no fix closes a cycle:
  1. Najstromszy spadek: `slope = (elev[i,j] - elev[neighbor]) / distance`
  2. Maksymalna akumulacja: sąsiad z najwyższym `acc`
  3. Dowolny prawidłowy sąsiad
  A sink with no such neighbour (every neighbour drains into it) stays a pit
- Recomputation of the accumulation after the fixes (only when there were any): Kahn's order in numba (`recompute_flow_accumulation`); the cells of a cycle never pass their accumulation on, which no fix creates now. The accumulation is conserved: the sum of the accumulations of the pits (outlets) is the number of the cells of the network

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
- Algorithm: `pyflwdir.streams.strahler_order(flw.idxs_ds, flw.idxs_seq, mask=stream_mask)` on the FlwdirRaster of the run; `FlwdirRaster.stream_order` caches the orders of its first call and would ignore the mask of the next threshold
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
**Loading:** at the start of the API, and by each worker again at its first request after the network in the database changed (`loaded_catchment_graph()` compares `network_version()`, the write counters of `stream_catchments` and `stream_network`; a run published from the command line needs no restart of the API)

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

**Funkcja:** `watershed_service.merge_catchment_boundaries()` — łączenie granic zlewni cząstkowych (`ST_UnaryUnion`: bezpośrednio, partiami lub z grubszym progiem), potem `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3)` (ADR-032). Above 300 sub-catchments `cascade_escalate()` merges at the first coarser threshold of the graph whose BFS selects at most 300 (10000 → 100000 → 1000000 → 10000000 m²), else at the coarsest.

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

### 4.2 The design depth: the watershed mean by Thiessen polygons (ADR-069)

**Functions:** `thiessen_cells()`, `areal_depth()`, `point_depth()` in
`core/precipitation.py`.

The design depth of a watershed is the mean of the PMAXTP grid points weighted by
the areas of their Thiessen (Voronoi) polygons inside it, the method of equal-rainfall
polygons of KZGW 2017 (ch. II, eq. 2.1: P = (1/A) Σ Pᵢ·Aᵢ).

- `thiessen_cells(boundary, db)`: the distinct grid points within 5 km
  (`THIESSEN_SEARCH_M`) of the watershed's bounding box, their Voronoi polygons
  (`shapely.voronoi_polygons`, ordered by point) clipped to the watershed; the cells
  with an area > 0 (easting, northing, `area_km2`). Run by the delineation, which
  returns them as `watershed.pmaxtp_grid`, and by the full path of the hydrograph.
- `areal_depth(cells, duration, probability, db)`: the scenario's depth at each cell
  (a point of the table within 1 m), averaged by Hydrolog's `thiessen_polygons`; a cell
  off the grid raises `UnknownGridPointError` (400 `pmaxtp_grid_point_unknown` for a
  request's `pmaxtp_grid`).
- `point_depth(point, duration, probability, db)`: without a boundary (own
  `morphometry` without `pmaxtp_grid`), Hydrolog's `inverse_distance_weighting` of the
  4 nearest points (KNN `<->`), power 2; a point on the grid takes its value.

The response gives the method (`precipitation.interpolation`: `thiessen` or `idw`) and
the points with depth, weight and area or distance (`precipitation.pmaxtp_points`).
Point depths are not reduced to areal ones unless the request gives the user's own
`areal_reduction_factor` (0 < ARF ≤ 1, none by default); the depth used is then the
PMAXTP depth × ARF, and the response reports `pmaxtp_depth_mm`, `areal_reduction_factor`
and `total_mm` (ADR-069).

---

## Faza 5: Krzywa CN

**Modules:** `backend/core/land_cover.py` (the CN of a watershed), `core/cn_tables.py`
(the TR-55 cover of each land cover category; the numbers are Hydrolog's table),
`core/cn_calculator.py` (the Kartograf path of `scripts/analyze_watershed.py`)
**Tables:** `land_cover`, `soil_hsg`

The CN is that of the hydrologic soil-cover complexes (USDA-NRCS 2004, NEH 630 chapter 9;
ADR-075): a complex is a land cover on a hydrologic soil group (HSG), and its CN for
AMC II is the TR-55 value of the cover it stands for on that group (USDA-SCS 1986,
tables 2-2a to 2-2c), read from Hydrolog (`hydrolog.runoff.get_cn`). The soil groups of
`soil_hsg` (bootstrap step 5) are those of the SoilGrids texture of the least permeable
layer of 0–100 cm: Kartograf's `calculate_hsg(depth_rule="least-permeable")` classifies the
clay, sand and silt of the layers 0–5, 5–15, 15–30, 30–60 and 60–100 cm and takes in every
cell the layer with the lowest Ksat (Rawls et al. 1982), the layer that limits infiltration
in NEH 630 chapter 7 (ADR-079; `soil.hsg_depth_rule: topsoil` takes the 0–5 cm layer). Under
the wetlands of BDOT10k (`OT_OIMK_A`) the soil is group D after that: an undrained wet soil
is group D (NEH 630 chapter 7; ADR-078).

### 5.1 Hierarchy of the sources of the CN

**Function:** `determine_cn()` (`core/land_cover.py`), used by `scripts/analyze_watershed.py`

| Priority | Source | Condition |
|----------|--------|-----------|
| 1 | Configuration (explicit CN) | `config_cn is not None` |
| 2 | Database (`land_cover` with `soil_hsg`, §5.2) | the watershed has land cover |
| 3 | Kartograf (HSG + land cover, §5.5) | `use_kartograf=True`, `boundary_wgs84` and `cache_dir` given, Kartograf importable (`calculate_cn_from_kartograf()` returns a result) |
| 4 | Default | `default_cn = 75` |

The panel (`land_cover_stats.weighted_cn`, `morphometry.cn`), the hydrograph, the
export of catchment parameters and source 2 all take the CN of §5.2; without land cover
the hydrograph uses `DEFAULT_CN = 75` (`core/constants.py`).

### 5.2 CN of the soil-cover complexes of a watershed

**Function:** `get_land_cover_for_boundary()` (`core/land_cover.py`, SQL `_COMPLEXES_SQL`;
the arithmetic in `summarize_complexes()`)

One query returns the land cover of the watershed twice: whole, by category, source
(`bdot_class`) and imperviousness (`ST_Area(ST_Intersection(lc.geom, w.geom))`, `w` the
pieces of the watershed of at most 256 vertices, `ST_Subdivide(…, 256)`), and in
its pieces on each soil group. For the pieces the soil polygons are clipped to the
watershed and subdivided the same way, then joined to `land_cover` through its spatial
index, so no land cover row is intersected with the whole boundary or a large soil polygon.

```
CN = round( Σ A_i · CN_i / Σ A_i , 1 )     # i: complex (category, source, soil group)
CN_i = get_cn(group, TR-55 cover of (category, source))     # Hydrolog, §5.3
```

- **Land cover outside `soil_hsg`** (an area without soil data, slivers left by the
  polygonization of the HSG raster): its soil groups follow the shares of the groups of
  the land cover of the watershed that lies on `soil_hsg`; with no soil data in the
  watershed it is group B (`DEFAULT_HSG`, the fallback of §5.5). The share of such land
  cover is `hsg_assumed_pct` (panel) and `lc_without_hsg_pct` (export).
- Soil pieces that sum to more than their land cover (overlapping soil polygons) are
  scaled to it.
- The CN of a category (`land_cover_stats.categories[].cn_value`, the export's
  `lc_<class>_cn`) is the area-weighted CN of its complexes, to 0.1. The weighted means
  are Hydrolog's `calculate_weighted_cn`.
- The weighted CN, not the weighted runoff, is the method (NEH 630 ch. 10, p. 10-10:
  WinTR-55 and WinTR-20 use it); the difference is in ADR-075.

### 5.3 TR-55 covers of the land cover categories

**File:** `core/cn_tables.py` (`COVER_BY_CATEGORY`, `COVER_BY_SOURCE`). A source of
`COVER_BY_SOURCE` overrides the cover of its category; plain layer codes (`PTZB`,
`PTTR`, the data imported before the land cover split) take the category's cover.

| Category | Source (`bdot_class`) | TR-55 cover (table) | A | B | C | D |
|---|---|---|---|---|---|---|
| `las` | any | woods, good (2-2c) | 30 | 55 | 70 | 77 |
| `łąka` | any | meadow (2-2c) | 30 | 58 | 71 | 78 |
| `grunt_orny` | any | small grain, straight row, good (2-2b) | 63 | 75 | 83 | 87 |
| `zabudowa_mieszkaniowa` | any | residential, 1/3 acre, 30% impervious (2-2a) | 57 | 72 | 81 | 86 |
| `zabudowa_mieszkaniowa` | `PTZB:wielorodzinna` | residential, 1/8 acre, 65% impervious (2-2a) | 77 | 85 | 90 | 92 |
| `zabudowa_przemysłowa` | any | industrial, 72% impervious (2-2a) | 81 | 88 | 91 | 93 |
| `zabudowa_przemysłowa` | `PTZB:handl.-usług.` | commercial and business, 85% impervious (2-2a) | 89 | 92 | 94 | 95 |
| `droga` | any | paved (2-2a) | 98 | 98 | 98 | 98 |
| `droga` | `PTKM` | paved road; open ditches, including right-of-way (2-2a; ADR-075, amendment of 2026-11-09) | 83 | 89 | 92 | 93 |
| `woda` | any | water surfaces (Hydrolog's water row; NEH 630 ch. 9, p. 9-1) | 98 | 98 | 98 | 98 |
| `inny` | any | open space, fair (2-2a) | 49 | 69 | 79 | 84 |
| `inny` | `PTPL:nieutwardzony` | dirt road, including right-of-way (2-2a) | 72 | 82 | 87 | 89 |
| `inny` | `PTWZ` | newly graded area, no vegetation (2-2a) | 77 | 86 | 91 | 94 |
| `inny` | `KUSK:<kind>`, `KUKO:lotnisko` | open space, good: the lawns of parks, sports grounds and airports (2-2a; ADR-078) | 39 | 61 | 74 | 80 |

### 5.4 CN for AMC I, II and III

The panel and the CN columns are for AMC II. The hydrograph converts the CN of the
watershed to the requested AMC with Hydrolog (`SCSCN.adjust_cn_for_amc`, Hawkins et al.
1985, approximating NEH 630 ch. 10 table 10-1; integer). The export names the CN of the
three conditions: `cn_amc_i` (dry) and `cn_amc_iii` (wet), the same conversion of its `cn`
(`core/cn_tables.cn_for_amc`), and `cn_amc_ii` (average), equal to `cn`. The conversion is
of the area-weighted composite CN of the watershed, as in the hydrograph (ADR-075).
Hydrolog warns for a CN outside 55–95. As a control of the composite CN the export adds
the SCS-CN runoff depth of `cn` (`q_cn_mm_p25`, `q_cn_mm_p50`) and the area-weighted runoff
depth of the complexes, each from its own CN (`q_weighted_mm_p25`, `q_weighted_mm_p50`;
NEH 630 ch. 10, p. 10-10), for P = 25 and 50 mm, AMC II, Ia = 0.2 S
(`core/cn_tables.runoff_mm`, `weighted_runoff_mm`; ADR-075, amendment of 2026-11-09).

### 5.5 CN from Kartograf (HSG)

**Function:** `calculate_cn_from_kartograf(boundary_wgs84, cache_dir, use_default_land_cover=True, teryt=None)` (`core/cn_calculator.py`); only `scripts/analyze_watershed.py` calls it, through `determine_cn()`.

1. The boundary of the watershed is converted to a `BBox` in EPSG:2180 with a buffer of 100 m (`convert_boundary_to_bbox`).
2. The HSG of the area (`get_hsg_from_soilgrids`): `kartograf.calculate_hsg(output_dir=<temporary directory>, bbox=, depth_rule="least-permeable", cache=False)` (the default rule of ADR-079; this path reads no `config.yaml`) downloads the SoilGrids clay, sand and silt rasters of the five layers of 0–100 cm, classifies the USDA texture of each layer and gives each cell the group of its least permeable layer, and writes the HSG raster as a plain file that exists only for this call; `kartograf.hsg_statistics` counts the cells per group. A failure of Kartograf (`KartografError`) or an area without data gives the group B.
3. The land cover (`get_land_cover_stats`): `download_bdot10k` takes the BDOT10k package of every county that the bbox intersects from the Kartograf store `<cache_dir>/kartograf` (a package that is already local is used without a request); the area of every `PT*` layer clipped to the bbox gives the shares in percent per category of `land_cover` (`BDOT10K_CATEGORY_MAP`, the category the import gives a layer without its kind), each county by its part in the bbox. Without data the default land cover is used when `use_default_land_cover` is true.
4. Without an overlay of the two, every category is taken to lie on the soil groups in their shares of the bbox: the CN is the weighted mean of the complexes category × group with the products of the two shares as weights (`weighted_cn_of_shares`).

> **Note (ADR-061):** `HSGCalculator` and `LandCoverManager` are no longer public in Kartograf, and `check_hsg_cache` and `HsgCacheStaleError` of `scripts/bootstrap.py` are gone together with `soil_hsg/hsg_poland.tif`. The HSG raster of the bootstrap (the `soil_hsg` table) is a version of the Kartograf store (`hsg/`): its sidecar records the Kartograf version and the source rasters with their hashes. The raster of this function is not kept, and `hsg_statistics` of a file without a sidecar counts the whole raster, so the cells at the edge of the bbox count in full, as in Kartograf 0.7.0 (ADR-061, erratum of 2026-10-25).

### 5.6 CN at a point

`GET /api/identify-point` (`core/point_info.land_cover_at`) gives the CN of the complex
of the land cover polygon and the soil group at the point (group B where `soil_hsg` has
none), converted to AMC I and III as for the hydrograph.

---

## Faza 6: Generowanie hydrogramu

**Endpoint:** `POST /api/generate-hydrograph`
**Moduł:** `backend/api/endpoints/hydrograph.py`

### 6.1 Flow procesu

1. **Walidacja** parametrów (czas trwania, prawdopodobieństwo — wymagane tylko bez `custom_precipitation`; `amc` I/II/III, domyślnie II)
2. **Wyznaczenie zlewni** (CatchmentGraph BFS → `watershed_service`, ADR-022) albo szybka ścieżka z `morphometry` (tryb zaawansowany, CN ułamkowe)
3. **Kontrola limitu**: `area_km2 ≤ 250` (ograniczenie SCS-CN)
4. **Morfometria + CN** (build_morph_dict_from_graph, get_land_cover_for_boundary)
5. **Opad**: projektowy PMAXTP (the watershed mean by Thiessen polygons, `areal_depth`; IDW at the point without a boundary, §4.2) albo własna seria `custom_precipitation` (`timestep_min` > 0 i ≤ 1440, `depths_mm` ≥ 0, 1–2000 wartości, suma > 0); czas trwania = liczba kroków × krok
6. **Czas koncentracji** (`_calculate_tc` → Hydrolog `WatershedParameters.calculate_tc`, §6.2)
7. **Hietogram**: dla PMAXTP rozkład opadu w czasie (§6.3); dla własnej serii `_custom_hietogram()` opakowuje serię w `HietogramResult` Hydrologa (czasy końca kroków k·Δt), bez hietogramu syntetycznego (`metadata.hietogram_type = null`, `precipitation.source = "custom"`, `probability_percent = null`)
8. **Hydrogram** (splot z UH; CN przeliczony wg AMC — także w regresji Nasha dla zlewni zurbanizowanych)

### 6.2 Czas koncentracji (tc)

Hydrograf nie wybiera danych metod sam: `_calculate_tc` buduje Hydrologowe `WatershedParameters` z morfometrii (obszar grafu bez zaokrąglenia, CN użyty w obliczeniu) i współczynników żądania i woła `calculate_tc(tc_method)` (Nogat plan `2026-11-05-official-tc-inputs`, D5). Każda metoda bierze pola, które definiuje jej źródło, bez zastępników (bez spadku cieku zamiast spadku drogi spływu, bez C z CN, bez domyślnego N 0,4, bez długości BDOT10k i bez „L_max − L_k”):

| Metoda | Pola `WatershedParameters` | Źródło |
|---|---|---|
| `kirpich` | `flow_path_length_km`, `flow_path_slope_m_per_m` | Kirpich 1940 (za Fang i in. 2005, TxDOT 0-4696-1) |
| `nrcs` | `flow_path_length_km`, `mean_slope_m_per_m` (Y), `cn` | NEH 630 rozdz. 15, wz. 15-4 |
| `giandotti` | `channel_length_km`, `elevation_mean_m − elevation_min_m`, `area_km2` | Giandotti 1934 (za Grimaldi i in. 2012) |
| `faa` | `overland_length_km`, `overland_slope_m_per_m`, `runoff_coeff` (= `tc_runoff_coeff`) | FAA 1970, AC 150/5320-5B, rys. 7, C z tab. I |
| `kerby` | `overland_length_km`, `overland_slope_m_per_m`, `retardance` (= `tc_retardance`) | Kerby 1959; TxDOT HDM, tab. N |
| `kerby_kirpich` | `retardance`, `overland_length_km`, `overland_slope_m_per_m`, `flow_path_length_km`, `flow_path_slope_m_per_m` (koryto: `flow_path_length_km − overland_length_km` przy spadku drogi spływu, musi być > 0) | Roussel i in. 2005; Cleveland i in. 2012 (TxDOT 0-6382-P1) |

`flow_path_*` i `overland_*` mierzy preprocessing (ADR-070): najdłuższa droga spływu od punktu zlewni najdalszego hydraulicznie (zwykle na dziale wodnym, ale może leżeć na grzbiecie wewnątrz zlewni) do ujścia, jej spadek (wysokość początku − wysokość ujścia) / długość, odcinek powierzchniowy od jej początku do pierwszej komórki sieci cieków progu wyznaczenia. Tryb zaawansowany może je zmienić (`morphometry`). C metody FAA i N metody Kerby'ego podaje tylko użytkownik (`tc_runoff_coeff`, `tc_retardance`); każda metoda dostaje tylko swój współczynnik. Brak pola → 400 `validation_error`, `details.reason` `missing_field`, `details.missing` (pola morfometrii albo opcje żądania), komunikat „Czas koncentracji metodą … wymaga: …”. Wzory: `hydrolog/time/concentration.py` przypiętego Hydrologu.

Przekazanie do Hydrologa (ADR-068) niesie w zlewni te same pola (z `runoff_coeff`/`retardance`, gdy metoda ich użyła), a `runoff` — `tc_method` bez `tc_min`: GUI Hydrologa liczy tc ponownie tą samą metodą; tc Hydrografu jest w `provenance.runoff.tc_min` do porównania.

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

**Uwilgotnienie początkowe (AMC):** CN zlewni odpowiada AMC II. Dla AMC I i III Hydrolog (`SCSCN.adjust_cn_for_amc`) przelicza CN i zaokrągla wynik do liczby całkowitej; AMC II zostawia CN ułamkowe. Tak przeliczony CN wchodzi do S, Ia i Pe.

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
| `cn_used` | — (float; CN po przeliczeniu wg AMC, klasa w `metadata.amc`) |
| `retention_mm` | mm |
| `initial_abstraction_mm` | mm |
| `peak_discharge_m3s` | m³/s |
| `time_to_peak_min` | min |
| `total_volume_m3` | m³ |

---

## Phase 7: Network delineation at control points (runtime)

**Endpoint:** `POST /api/delineate-network` (`backend/api/endpoints/network.py`)
**Modules:** `core/network_tree.py` (the tree on the catchment graph), `core/network_delineation.py` (the rasters), `core/cell_parameters.py` (the measures), `core/handoff.py` (`build_network_handoff`)
**Decision:** ADR-080; the details and their reasons: plan `docs/plans/2026-11-10-network-delineation.md` (D1–D15)

A closing section A and up to 30 control points above it become a network of HEC-HMS elements: subcatchments (`headwater`, `tributary`, `intermediate`, the last the przyrzecze of a reach), reaches and junctions, with A's junction flowing into `OUT`. The elements are made of the units, the sub-catchments of the graph at `DEFAULT_THRESHOLD_M2` (1 ha), so every confluence is a unit boundary and needs no raster.

### 7.1 Snapping (D1–D3)

Each point, A included, moves to the centre of the nearest cell within `NETWORK_SNAP_M` (100 m) whose accumulation reaches the request's `threshold_m2` (the streams of the map), the larger accumulation on a tie; none → 404 `network_point_off_stream`. A point at most `MOUTH_TOLERANCE_M` (50 m) along the flow above a junction where its path meets another branch of the network moves to the outlet cell of the last unit above that junction on its branch (`at_mouth`) and enters it with no reach: a point off its parent's trunk takes the lowest such junction on its way to the trunk (its junction there, or a confluence where its path merges with another point's), a point on the trunk (a gauge) the first confluence below it where a point's path enters the trunk. Two points moved to one cell → 400 `network_points_coincide`; a point whose path runs down the trunk into the point below it with no such confluence between keeps its place.

### 7.2 The tree (D4, D15)

The parent of a point is the first control point on its flow path downstream (A at the latest; a path that misses A → 400 `network_point_outside`). The trunk of a control point is its main river by `trace_main_channel` (ADR-046); a point joins its parent's trunk at itself when it lies on it, else at the confluence where its path enters it. The nodes of a trunk bound its edges, each a reach with its przyrzecze; the trunk above its uppermost junction is a headwater; a point with no point above it is a subcatchment. Points on one cell → 400 `network_points_coincide`. The ids `Z…`, `R…`, `J…` follow a walk from A in which every node comes after the nodes it receives (the trunk first, then the branches by accumulation), the order of the hand-off; the same points in any order give the same network.

### 7.3 The cells of the elements (D5–D7)

An element holds the cells whose first element outlet downstream is its own. A whole unit takes its element from the graph in one pass from A upward (`CatchmentGraph.upstream_tree`); a unit with a control point inside is split by `pyflwdir` basins with an outlet at each of its points and at its outlet cell. One window of the six saved rasters covers A's catchment (grown as the precise mode grows its window, at most `NETWORK_MAX_WINDOW_CELLS` = 60 M cells, else 422 `network_window_too_large`), and the element raster (int16) is built in it from the unit labels. The window is read without the slope, which is read for the one `zonal_summary` of all elements and dropped; the labels are dropped once the element raster holds them, keeping those of the stream cells of the units for the main channels: a network holds 17 bytes a cell, 21 while the labels or the slope are held.

### 7.4 The area check, B5 (D11)

The cells of the element raster must equal the cells of A's catchment counted from the graph (the units' `area_km2` in cells, less the cells of A's unit below A). Any difference is a defect: 500 `internal_error`, reason `network_area_mismatch`; the response gives both sums (`area_check`).

### 7.5 The measures of an element (D8, D9)

Every element is measured from its cells by the functions of `core/cell_parameters.py`, those of `scripts/export_catchment_parameters.py`: the terrain by `zonal_summary` (area exact to the cell, elevations, slope, hypsometry), the outlet, the flow paths closed downstream (Phases 3 and 6.2), the main channel up the element's own stream cells, the drainage indices of its units, the shape indices, the land cover and CN, the soil groups and the PMAXTP Thiessen weights of its boundary (Phases 4 and 5). The result is a `WatershedResponse` per element, the panel's parameters at 1 ha; `hydrograph_available` is false above 250 km² (notice `over_scs_cn_limit`), and the network is not refused. The boundaries are vectorized once, noded into one coverage and simplified together at `COVERAGE_TOLERANCE_M` (5 m, `shapely.coverage_simplify`), so they tile A without gaps or overlaps.

### 7.6 Reaches (D10)

| Value | Source |
|---|---|
| `length_km` | (fd(upper end) − fd(lower end)) / 1000, fd from `04b_stream_distance` (the graph's `outlet_flow_dist_m` at junctions) |
| `slope_m_per_m` | fall of the NMT (`01_dem`) between the two end cells / length; `MIN_REACH_SLOPE_M_PER_M` = 0.0001 where it is not positive (`slope_method` `minimum`) |
| `vector_length_km` | check length: the reach's D8 line sampled every `REACH_SAMPLE_M` (10 m), each sample on its nearest `bdot_streams` line within `BDOT_BUFFER_M` (25 m); null when a sample has none |

No cross-section: Hydrolog's Muskingum–Cunge needs Manning's n and a width, which the person gives in Hydrolog.

A reach shorter than `SHORT_REACH_M` (200 m) or of the minimum slope is a notice `reach_short_or_flat` (D10a), in the preview too (its slope from the NMT at the same end cells): Muskingum–Cunge may find no division of it that keeps its weights non-negative at a usable time step (Hydrolog's `unstable_timestep`). A reach from a point into a confluence carries `move_to`, the outlet cell of the last unit above the confluence on its branch (the end of its przyrzecze; in the preview the cell of the largest accumulation of that unit within two cells of the junction): the point placed there is at the mouth (D3). A reach of the minimum slope is handed off as a lag of `lag_min` = max(1, round(1000 · `length_km` / 0.5 / 60)) min.

### 7.7 The hand-off (D14)

`build_network_handoff` writes one `nogat-handoff/1` around one `hydrolog-network/1`: the nodes in the order of 7.2, each with a Polish `description`; subcatchments with the `watershed` of their morphometry (the area exact to the cell, so they sum to A) and the `curve-number` runoff with Hydrolog's defaults; Muskingum–Cunge reaches with length and slope and no section, a reach of the minimum slope a `lag` (`node_provenance`: its length and slope, `method_reason` `flat`); junctions; `OUT`. No rainfall, time step or result. `provenance.watershed` names A's snapped place and `threshold_m2`, `node_provenance` the origin of every subcatchment, reach and junction (`docs/integrations/HYDROLOG.md`).

### 7.8 The preview on the catchment graph (ADR-081)

`POST /api/delineate-network/preview` (`core/network_preview.py`, plan `docs/plans/2026-11-11-network-preview.md`) composes the same network while the person places the points, without the window of 7.3: the snapping of 7.1 (the windows around the clicks) and the tree of 7.2, so the ids, the places and the errors of the composition are those of the full run.

| Value | Source |
|---|---|
| `area_km2` of an element | the cells of its units (`area_km2` in cells, as 7.4 counts them); in a unit split by a point the accumulation at the uppermost point less the cells of the units above the unit (they enter at its head), the next point the difference of the accumulations, the unit's outlet the rest; A's part of its unit ends at A. Exact to the cell, the full run's |
| `length_km` of a reach | as in 7.6; its line the stream lines of its units (`stream_network`) cut at its control points, simplified at 1 m |
| outline of an element | the union, on a grid of 10 m (`ST_Simplify`, `ST_ReducePrecision`, `ST_Union`), of the largest sub-catchment of any threshold that the element holds whole (matched to the unit of 1 ha that ends at its outlet cell by `outlet_flow_dist_m` and `upstream_area_km2`, taken when its units add up to its cells and share the element), else of the units; a unit split by a point goes whole to the element with most of its cells (`outline_approximate`), holes and parts narrower than 30 m dropped |

No measure of 7.5, no check of 7.4 (the areas add up by construction), no hand-off: those come with „Oblicz charakterystyki”, the full run.

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
| PMAXTP depth (Thiessen weights at delineation) | ~0.25 s for 240 km² (86 cells), a few ms per hydrograph |
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
| 3 | Akumulacja spływu | `pyflwdir` `upstream_area`; after the fixes of the internal sinks Kahn's topological order in numba |
| 4 | Rząd Strahlera | Strahler 1952 |
| 5 | Wektoryzacja cieków | Śledzenie od źródeł do skrzyżowań |
| 6 | Delimitacja zlewni cząstkowych | pyflwdir.basins() — propagacja upstream (ADR-016) |
| 7 | Granica zlewni | `ST_UnaryUnion` granic zlewni cząstkowych + wygładzanie (ADR-032) |
| 8 | Ciek główny | `CatchmentGraph.trace_main_channel()` (Strahler → długość → powierzchnia) |
| 9 | Interpolacja opadów | Thiessen polygons of the PMAXTP grid inside the watershed (ADR-069); IDW (p=2, 4 nearest points) without a boundary |
| 10 | Krzywa CN | Średnia ważona powierzchnią |
| 11 | Przejście w górę | BFS po grafie zlewni cząstkowych (`CatchmentGraph.traverse_upstream`) |
| 12 | Bulk load do bazy | PostgreSQL COPY przez temp tables |
| 13 | Odpływ SCS-CN | Metoda SCS z konwolucją |
| 14 | Czas koncentracji | Hydrolog `WatershedParameters.calculate_tc`: Kirpich / NRCS (lag) / Giandotti / FAA / Kerby / Kerby-Kirpich z pól źródła metody |
| 15 | Graf zlewni cząstkowych | BFS po sparse CSR (~44k węzłów, ADR-021) |

---

## Limity bezpieczeństwa

| Parametr | Wartość | Lokalizacja |
|----------|---------|-------------|
| HYDROGRAPH_AREA_LIMIT_KM2 | 250.0 | hydrograph.py (SCS-CN) |
| NETWORK_MAX_POINTS | 30 | models/schemas.py (points besides A) |
| NETWORK_SNAP_M | 100.0 | core/network_delineation.py |
| NETWORK_MAX_WINDOW_CELLS | 60 000 000 | core/network_delineation.py |
| NETWORK_LOCK_WAIT_S | 15.0 | api/endpoints/network.py (one network at a time per worker) |
