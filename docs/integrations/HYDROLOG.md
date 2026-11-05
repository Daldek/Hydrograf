# Integracja Hydrograf ↔ Hydrolog

**Data utworzenia:** 2026-01-20
**Ostatnia aktualizacja:** 2026-11-05 (Hydrolog `1ffcd6b` of `develop`, the official inputs of tc; was `2eb8bd0`)
**Status:** ✅ Zaimplementowane (CP3+)

---

## Cel

Umożliwić łatwą wymianę danych między Hydrografem (analizy przestrzenne GIS) a Hydrologiem (obliczenia hydrologiczne), z możliwością integracji z innymi systemami.

---

## Podział odpowiedzialności

```
┌─────────────────────────────────────────────────────────────────┐
│                         HYDROGRAF                               │
│  Odpowiedzialność: ANALIZY PRZESTRZENNE (GIS)                   │
│                                                                 │
│  - Wyznaczanie zlewni z NMT (CatchmentGraph BFS)                │
│  - Obliczanie parametrów geometrycznych z boundary/cells        │
│  - Obliczanie statystyk wysokości z DEM (zonal_stats)           │
│  - Obliczanie CN z pokrycia terenu (cn_calculator + cn_tables)  │
│  - Interpolacja opadów (IDW/Thiessen, Obserwator PMAXTP)        │
│  - Śledzenie głównego cieku (trace_main_channel)                │
│                                                                 │
│  OUTPUT: JSON zgodny ze schematem WatershedParameters           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  STANDARYZOWANY FORMAT JSON   │
              │  (WatershedParameters schema) │
              └───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         HYDROLOG                                │
│  Odpowiedzialność: OBLICZENIA HYDROLOGICZNE                     │
│                                                                 │
│  - Czas koncentracji (Kirpich, NRCS, Giandotti,                 │
│      FAA, Kerby, Kerby-Kirpich)                                 │
│  - Hydrogramy jednostkowe (SCS, Nash, Clark, Snyder)            │
│  - Transformacja opad→odpływ (splot)                            │
│  - Wskaźniki kształtu zlewni                                    │
│  - Krzywa hipsograficzna                                        │
│  - Hietogramy (Beta, Block, Euler II)                           │
│                                                                 │
│  INPUT: WatershedParameters.from_dict(json_data)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Format wymiany danych

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WatershedParameters",
  "description": "Standaryzowany format parametrów zlewni dla integracji GIS ↔ Hydrolog",
  "type": "object",
  "required": ["area_km2", "perimeter_km", "length_km", "elevation_min_m", "elevation_max_m"],
  "properties": {
    "name": {"type": "string", "description": "Nazwa zlewni"},
    "area_km2": {"type": "number", "minimum": 0, "description": "Powierzchnia [km²]"},
    "perimeter_km": {"type": "number", "minimum": 0, "description": "Obwód [km]"},
    "length_km": {"type": "number", "minimum": 0, "description": "Długość zlewni [km]"},
    "elevation_min_m": {"type": "number", "description": "Min wysokość [m n.p.m.]"},
    "elevation_max_m": {"type": "number", "description": "Max wysokość [m n.p.m.]"},
    "elevation_mean_m": {"type": "number", "description": "Średnia wysokość [m n.p.m.]"},
    "mean_slope_m_per_m": {"type": "number", "minimum": 0, "description": "Średni spadek [m/m]"},
    "channel_length_km": {"type": "number", "minimum": 0, "description": "Długość cieku [km]"},
    "channel_slope_m_per_m": {"type": "number", "minimum": 0, "description": "Spadek cieku [m/m]"},
    "longest_flow_path_km": {"type": "number", "minimum": 0, "description": "Najdłuższa ścieżka spływu [km]"},
    "divide_flow_path_km": {"type": "number", "minimum": 0, "description": "Droga spływu z działu wodnego [km]"},
    "centroid_flow_path_km": {"type": "number", "minimum": 0, "description": "Droga spływu z centroidu [km] (dla modeli izochron)"},
    "cn": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Curve Number"},
    "source": {"type": "string", "description": "Źródło danych"},
    "crs": {"type": "string", "description": "Układ współrzędnych"}
  }
}
```

### Przykład JSON (output z Hydrografa)

```json
{
  "name": "Zlewnia potoku X",
  "area_km2": 45.3,
  "perimeter_km": 32.1,
  "length_km": 12.5,
  "elevation_min_m": 150.0,
  "elevation_max_m": 520.0,
  "elevation_mean_m": 340.0,
  "mean_slope_m_per_m": 0.025,
  "channel_length_km": 8.2,
  "channel_slope_m_per_m": 0.045,
  "longest_flow_path_km": 14.2,
  "divide_flow_path_km": 13.8,
  "centroid_flow_path_km": 9.1,
  "cn": 72,
  "source": "Hydrograf",
  "crs": "EPSG:2180"
}
```

---

## Przekazanie do GUI Hydrologa (`nogat-handoff/1`, ADR-068)

GUI Hydrologa („Wczytaj z Hydrografa” w „Hydrogramie zlewni”) czyta kopertę Nogata
`nogat-handoff/1` (kopia: `schemas/nogat/handoff-1.schema.json`) z dokumentem
`hydrolog-network/1`: jedna zlewnia cząstkowa `Z1` (pola `WatershedParameters`,
`length_to_centroid_km` jako `Lc_km`) i wylot `OUT`. Buduje je `backend/core/handoff.py`:

- `POST /api/delineate-watershed` → `handoff`: sama zlewnia, bez opadu i wyniku;
- `POST /api/generate-hydrograph` → `handoff`: zlewnia z `runoff` (SCS-CN z użytym
  `tc_min`, n i K Nasha albo L, Lc, Ct, Cp Snydera; AMC), `rainfall` (opad projektowy
  PMAXTP z kształtem hietogramu albo własny szereg), `timestep_min` i `result` (Qmax,
  czas do szczytu, objętość, `computed_with` z wersją Hydrologa). Wartości są te, których
  użyło obliczenie, bez zaokrągleń: `hydrograph generate` Hydrologa daje z nich ten sam
  wynik (`backend/tests/unit/test_handoff.py`).

Pochodzenie (`provenance`): zlewnia z Hydrografa z ujściem i polami zmienionymi w trybie
zaawansowanym (pole żądania `morphometry_origin`; bez niego `user`), opad `pmaxtp`
(POT, prawdopodobieństwo, czas trwania, punkt żądania, `interpolation: idw`) albo `user`,
parametry odpływu (metoda tc, estymacja Nasha). W interfejsie: „Kopiuj do Hydrologa” i
„Plik przekazania” pod sekcjami panelu „Zlewnia” (`frontend/js/handoff.js`).

Nash by Lutz travels as Lutz (ADR-068, erratum 2026-11-05): the watershed carries Lutz's
inputs `manning_n` (0.035), `forest_pct` and `urban_pct` (the land cover shares the
computation used) and the provenance of `runoff` is Hydrolog's own record `{"source":
"hydrograf", "method": "lutz"}`, so Hydrolog opens Nash in Lutz mode and its `uh nash`
gives Hydrograf's n and K; `runoff` keeps them for the recomputation.

---

## Zaimplementowane komponenty

### 1. Moduł: `backend/core/morphometry.py`

**Status:** ✅ Zaimplementowane

Funkcje:
- `calculate_shape_indices(area_km2, perimeter_km, length_km)` - wskaźniki kształtu (Kc, Rc, Re, Ff, Cl, W)

Pozostałe parametry (powierzchnia, obwód, długość, wysokości, spadek, ciek główny, wskaźniki rzeźby i drenażu) liczy `build_morph_dict_from_graph()` w `core/watershed_service.py` z grafu zlewni cząstkowych; ciek główny wyznacza `CatchmentGraph.trace_main_channel()`.

### 2. Moduł: `backend/core/morphometry_raster.py`

**Status:** ✅ Zaimplementowane (CP4+)

Obliczenia rastrowe na numpy arrays:
- `compute_slope(dem, cellsize, nodata)` - spadek terenu (Sobel)
- `compute_aspect(dem, cellsize, nodata)` - ekspozycja
- `compute_twi(dem, fac, cellsize, nodata)` - Topographic Wetness Index
- `compute_strahler_order(fdir, fac, threshold)` - rząd Strahlera

### 3. Moduł: `backend/core/catchment_graph.py`

**Status:** ✅ Zaimplementowane (CP4+)

In-memory graf zlewni (~44k nodes, ~0.5 MB):
- `traverse_upstream(node_idx)` - BFS w górę sieci
- `aggregate_stats(indices)` - agregacja parametrów (area, elevation, slope)
- `trace_main_channel(segment_idx, threshold)` - śledzenie głównego cieku (do channel_slope)
- `find_catchment_at_point(x, y, threshold, db)` - lokalizacja zlewni cząstkowej (ST_Contains)

### 4. Moduł: `backend/core/watershed_service.py`

**Status:** ✅ Zaimplementowane (CP4+)

Wspólna logika serwisowa:
- `build_morph_dict_from_graph(cg, indices, boundary, ...)` - buduje dict morfometryczny z CatchmentGraph
- `get_stream_info_by_segment_idx(segment_idx, threshold, db)` - info o segmencie po indeksie (ADR-026)
- `merge_catchment_boundaries(segment_idxs, threshold, db)` - łączenie granic z wygładzaniem (Chaikin, ADR-032)

### 5. Schematy Pydantic: `backend/models/schemas.py`

**Status:** ✅ Zaimplementowane

Dodane klasy:
- `MorphometricParameters` - parametry morfometryczne zgodne z Hydrolog
- `HydrographRequest` - request do generowania hydrogramu
- `HydrographResponse` - pełna odpowiedź z hydrogramem
- `PrecipitationInfo` - informacje o opadzie i hietogramie
- `HydrographInfo` - dane hydrogramu (times, discharge, peak, volume)
- `WaterBalance` - bilans wodny (CN, retention, effective rainfall)
- `HydrographMetadata` - metadane obliczeń (tc, metoda, model UH)

### 6. Endpoint: `POST /api/generate-hydrograph`

**Status:** ✅ Zaimplementowane

**Plik:** `backend/api/endpoints/hydrograph.py`

**Importy Hydrologa:**
```python
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram, BlockHietogram, EulerIIHietogram
from hydrolog.runoff import HydrographGenerator, NashIUH
from hydrolog.time.concentration import ConcentrationTime
```

**Przepływ danych:**
1. Walidacja parametrów (duration, probability)
2. Transformacja współrzędnych WGS84 → PL-1992
3. Lokalizacja zlewni cząstkowej (CatchmentGraph + ST_Contains)
4. BFS w górę sieci (traverse_upstream)
5. Agregacja statystyk + sprawdzenie limitu 250 km²
6. Budowa granicy zlewni (merge + Chaikin smoothing)
7. Obliczenie CN z pokrycia terenu (land_cover + cn_tables)
8. Budowa dict morfometrycznego (build_morph_dict_from_graph)
9. Pobranie opadu: the watershed mean of `precipitation_data` by Thiessen polygons (**Hydrolog:** `thiessen_polygons`, ADR-069); without a boundary IDW at the point (**Hydrolog:** `inverse_distance_weighting`)
10. **Hydrolog:** `WatershedParameters.from_dict()` → `calculate_tc()`
11. **Hydrolog:** Hietogram (Beta/Block/Euler II) → `generate()`
12. **Hydrolog:** `HydrographGenerator` → `generate()`
13. Budowa odpowiedzi JSON

**Parametry wejściowe:**
- `latitude`, `longitude` - współrzędne WGS84
- `duration` - czas trwania opadu: 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h
- `probability` - prawdopodobieństwo: 1%, 2%, 5%, 10%, 20%, 50%
- `timestep_min` - krok czasowy (default: 5 min)
- `tc_method` - metoda tc: kirpich, nrcs, giandotti, faa, kerby, kerby_kirpich
- `hietogram_type` - typ hietogramu: beta, block, euler_ii
- `uh_model` - model hydrogramu jednostkowego: scs, snyder, nash
- `nash_estimation` - metoda estymacji Nash IUH: from_lutz, from_urban_regression
- `snyder_ct` - współczynnik opóźnienia Snydera (default: 1.5)
- `snyder_cp` - współczynnik szczytu Snydera (default: 0.6)
- `tc_runoff_coeff` - współczynnik spływu C metody FAA (0 < C ≤ 1, z tab. I FAA 1970, AC 150/5320-5B); wymagany dla `faa`, nigdy nie liczony z CN
- `tc_retardance` - współczynnik oporu N Kerby'ego (0,02–0,8, tabela Kerby'ego / TxDOT HDM); wymagany dla `kerby` i `kerby_kirpich`, bez wartości domyślnej
- `morphometry` - morfometria (tryb zaawansowany), w tym `flow_path_length_km`, `flow_path_slope_m_per_m`, `overland_length_km`, `overland_slope_m_per_m`

**Ograniczenia:**
- Maksymalna powierzchnia zlewni: 250 km² (limit metody SCS-CN)

### 7. Endpoint: `GET /api/scenarios`

**Status:** ✅ Zaimplementowane

Zwraca dostępne kombinacje parametrów hydrogramu (durations, probabilities, tc_methods, hietogram_types, area_limit_km2).

### 8. Rozszerzenie endpointu watershed

**Status:** ✅ Zaimplementowane

Endpoint `/api/delineate-watershed` zwraca teraz `morphometry` w odpowiedzi.

### 9. Skrypt: `scripts/analyze_watershed.py`

**Status:** ✅ Zaimplementowane

Skrypt CLI do pełnej analizy zlewni (offline). Używa rozszerzonych importów Hydrologa:
```python
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram
from hydrolog.runoff import SCSCN, HydrographGenerator, SCSUnitHydrograph
```

---

## Moduły Hydrografa korzystające z Hydrologa

| Moduł | Importy z Hydrologa | Zastosowanie |
|-------|---------------------|--------------|
| `api/endpoints/hydrograph.py` | `WatershedParameters`, `BetaHietogram`, `BlockHietogram`, `EulerIIHietogram`, `HydrographGenerator`, `NashIUH`, `ConcentrationTime` | Endpoint API generowania hydrogramu |
| `core/precipitation.py` | `Station`, `thiessen_polygons`, `inverse_distance_weighting` | The PMAXTP design depth: the watershed mean, IDW at a point (ADR-069) |
| `scripts/analyze_watershed.py` | `WatershedParameters`, `BetaHietogram`, `SCSCN`, `HydrographGenerator`, `SCSUnitHydrograph` | Skrypt CLI pełnej analizy |
| `core/morphometry.py` | `WatershedParameters` (w docstring/example) | Dokumentacja formatu wymiany |

---

## Lista zmian - podsumowanie

### Hydrograf (CP3+)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/pyproject.toml` | + hydrolog (commit `1ffcd6b`, 1.0.0.dev0; was v0.6.3, ADR-060) | ✅ |
| `backend/core/morphometry.py` | `calculate_shape_indices` (wskaźniki kształtu) | ✅ |
| `backend/core/morphometry_raster.py` | Obliczenia rastrowe (slope, aspect, TWI, Strahler) | ✅ |
| `backend/core/catchment_graph.py` | In-memory graf, BFS, trace_main_channel | ✅ |
| `backend/core/watershed_service.py` | build_morph_dict_from_graph, boundary smoothing | ✅ |
| `backend/core/cn_calculator.py` | Obliczanie CN z Kartografa (HSG + land cover) | ✅ |
| `backend/core/cn_tables.py` | Tablice CN dla BDOT10k + BUBD | ✅ |
| `backend/core/land_cover.py` | CN z tabeli land_cover (spatial intersection) | ✅ |
| `backend/models/schemas.py` | 7 klas Pydantic (MorphometricParameters, etc.) | ✅ |
| `backend/api/endpoints/watershed.py` | Unified endpoint — tryb precomputed (snap-to-stream + BFS) i precise (pyflwdir on-the-fly), morphometry w response (ADR-050) | ✅ |
| `backend/api/endpoints/hydrograph.py` | Endpoint hydrogramu (CatchmentGraph BFS) | ✅ |
| `backend/api/main.py` | + router hydrograph | ✅ |
| `backend/scripts/analyze_watershed.py` | Skrypt CLI pełnej analizy z Hydrologiem | ✅ |
| `backend/tests/unit/test_morphometry.py` | Testy wskaźników kształtu | ✅ |
| `backend/tests/integration/test_hydrograph.py` | 16 testów integracyjnych | ✅ |

### Hydrolog

| Plik | Zmiana | Status |
|------|--------|--------|
| `hydrolog/morphometry/watershed_params.py` | WatershedParameters | ✅ |
| `hydrolog/morphometry/geometric.py` | + `from_dict()` | ✅ |
| `hydrolog/morphometry/terrain.py` | + `from_dict()` | ✅ |

---

## Uwaga: channel_slope vs stream_length vs flow_path

Od ADR-029 rozróżniamy dwa pomiary długości cieków:

- **`aggregate_stats()["stream_length_km"]`** = suma długości CAŁEJ sieci cieków (do drainage density)
- **`trace_main_channel()`** = długość GŁÓWNEGO cieku (do channel_slope i tc)

Różnica może wynosić 2-10x. Channel slope MUSI być obliczany z głównego cieku.

### Ścieżki spływu (flow path tracing)

Od migracji 023 dostępne są dodatkowe parametry długościowe oparte na ścieżkach spływu:

- **`longest_flow_path_km`** — najdłuższa ścieżka spływu w zlewni (hydraulic length). Agregacja `max_flow_dist_m` z subcatchments przez CatchmentGraph. Geometria dostępna jako `longest_flow_path_geojson`
- **`divide_flow_path_km`** — odległość spływu z punktu na dziale wodnym (boundary) do ujścia. Point sampling `stream_distance.tif` na granicy zlewni
- **`centroid_flow_path_km`** — odległość spływu z centroidu zlewni do ujścia. Point sampling `stream_distance.tif` na centroidzie. Dostępny dla modeli izochron (wewnętrzny, ukryty w GUI)

---

## Metody czasu koncentracji (Tc)

Tc liczy wyłącznie Hydrolog: `_calculate_tc` (`api/endpoints/hydrograph.py`) buduje `WatershedParameters.from_dict` z morfometrii (obszar użyty w obliczeniu, CN użyty w obliczeniu) i współczynnika metody z żądania i woła `calculate_tc(tc_method)` (Nogat plan `2026-11-05-official-tc-inputs`, D5). Każda metoda bierze pola, które definiuje jej źródło, bez zastępników:

| Metoda | Klucz API | Pola zlewni (Hydrolog) | Z żądania | Źródło |
|--------|-----------|------------------------|-----------|--------|
| Kirpich | `kirpich` | `flow_path_length_km`, `flow_path_slope_m_per_m` | — | Kirpich 1940 (za Fang i in. 2005) |
| NRCS (lag) | `nrcs` | `flow_path_length_km`, `mean_slope_m_per_m`, `cn` | — | NEH 630 rozdz. 15 |
| Giandotti | `giandotti` | `channel_length_km`, `elevation_min_m`, `elevation_mean_m`, `area_km2` | — | Giandotti 1934 (za Grimaldi i in. 2012) |
| FAA | `faa` | `overland_length_km`, `overland_slope_m_per_m`, `runoff_coeff` | `tc_runoff_coeff` → `runoff_coeff` | FAA 1970, AC 150/5320-5B, rys. 7 i tab. I |
| Kerby | `kerby` | `overland_length_km`, `overland_slope_m_per_m`, `retardance` | `tc_retardance` → `retardance` | Kerby 1959; TxDOT HDM |
| Kerby-Kirpich | `kerby_kirpich` | `retardance`, `overland_*`, `flow_path_*` (koryto = `flow_path_length_km − overland_length_km`) | `tc_retardance` → `retardance` | Roussel i in. 2005; Cleveland i in. 2012 (TxDOT 0-6382-P1) |

**Pola zlewni** mierzy preprocessing (ADR-070): `flow_path_length_km` (= `hydraulic_length_km`, najdłuższa droga spływu od działu wodnego do ujścia), `flow_path_slope_m_per_m` ((wysokość jej początku − wysokość ujścia) / długość), `overland_length_km` i `overland_slope_m_per_m` (odcinek od jej początku do pierwszej komórki sieci cieków progu wyznaczenia). Pole, którego nie da się zmierzyć, jest puste, nie 0 ani wartością domyślną; tryb zaawansowany może je podać.

**Brak danych:** Hydrologowy `InvalidParameterError` z `details.reason` `missing_field` staje się 400 `validation_error` z `details` `{"reason": "missing_field", "method": …, "missing": […]}` (nazwy pól morfometrii albo opcji żądania `tc_runoff_coeff`, `tc_retardance`) i komunikatem „Czas koncentracji metodą … wymaga: …” (`tc_inputs_missing`). Usunięte: wybór pól po stronie Hydrografu (długość hydrauliczna podstawiana pod `length_km`, spadek cieku dla Kirpicha, średni spadek terenu dla FAA i Kerby'ego, C z CN, N 0,4, długość BDOT10k i „L_max − L_k” w Kerby-Kirpich) oraz opcja żądania `tc_overland_length_km` (odcinek powierzchniowy podaje się razem ze spadkiem w `morphometry`).

**Przekazanie (ADR-068):** zlewnia niesie `flow_path_*` i `overland_*` (gdy niepuste) oraz `runoff_coeff`/`retardance` metody, która ich użyła; `runoff` niesie `tc_method` bez `tc_min`, więc Hydrolog liczy tc ponownie; `provenance.runoff.tc_min` zostaje do porównania.

---

## Typy hietogramów

| Typ | Klucz API | Parametry | Opis |
|-----|-----------|-----------|------|
| Beta | `beta` | `alpha` (default: 2.0), `beta` (default: 5.0) | Rozkład beta — elastyczny kształt, peak zależny od alpha/beta |
| Block | `block` | brak | Opad jednostajny (stała intensywność) |
| Euler II | `euler_ii` | `peak_position=0.33` (hardcoded) | Rozkład Euler typu II — peak w 1/3 czasu trwania |

---

## Estymacja parametrów Nash IUH

| Metoda | Klucz API | Parametry wymagane | Uwagi |
|--------|-----------|---------------------|-------|
| Lutz (domyślna) | `from_lutz` | `channel_length_km`, `length_to_centroid_km`, `channel_slope_m_per_m`; `forest_pct`, `urban_pct` | Lutz (1984) after KZGW 2017, eq. 6.17: Manning's n 0.035 (`LUTZ_MANNING_N`), W = share of forest (`las`), U = share of urbanised land (`zabudowa_mieszkaniowa`, `zabudowa_przemysłowa`, `droga`) from the land cover of the delineation, 0 without it; `area_km2` passed too. The hand-off carries `manning_n`, `forest_pct` and `urban_pct` in the watershed and `{"source": "hydrograf", "method": "lutz"}` as the provenance of `runoff`, so Hydrolog reopens Nash by Lutz (ADR-068, erratum 2026-11-05) |
| Regresja zurbanizowana | `from_urban_regression` | `nash_urban_fraction` | Rao et al. (1972), wymaga wskaźnika urbanizacji |

**Removed 2026-11-05:** the estimation from the time of concentration (`nash_estimation: "from_tc"`, `NashIUH.from_tc()`, deprecated in Hydrolog since 0.6.2 and announced for removal in 1.0.0) and the request field `nash_n` it used. The relation $t_{lag} = 0.6·T_c$ of the SCS hydrograph has no ground in the Nash cascade, so Hydrograf no longer offers it: a request with `from_tc` gets 400 `validation_error` at `/body/nash_estimation` with the allowed values, `GET /api/scenarios` lists only `from_lutz` and `from_urban_regression`, and no Nash estimation computes Tc.

---

## Snyder Unit Hydrograph

**Model:** `uh_model: 'snyder'`

**Parametry:**
- `snyder_ct` — współczynnik opóźnienia (default: 1.5). Zależy od charakterystyki retencji zlewni
- `snyder_cp` — współczynnik szczytu (default: 0.6). Wpływa na wysokość szczytu hydrogramu

**Wymagane dane morfometryczne (z `morph_dict`):**
- `channel_length_km` — długość głównego cieku
- `length_to_centroid_km` — odległość od ujścia do centroidu zlewni wzdłuż cieku

**Implementacja:** `backend/api/endpoints/hydrograph.py`

**Hydrolog 1.0.0.dev0 (ADR-060):** `HydrographGenerator` builds the Snyder unit hydrograph for a duration equal to the time step (the duration correction of Snyder: `tLR = tL + 0.25 (D - tD)`, `tpR = tLR + D/2`, `qpR = qp tL / tLR`), not for the standard duration `tD = tL/5.5` as 0.6.3 did. Measured on the endpoint at a time step of 5 minutes (three catchments, six concentration-time methods, three hyetograph types): the peak is 11 to 12% higher, comes 25 to 70 minutes earlier, and the volume is the same. The SCS and Nash unit hydrographs give the numbers they gave before.

**Dostępne modele hydrogramu jednostkowego:**
- `scs` — SCS Unit Hydrograph (domyślny)
- `snyder` — Snyder Unit Hydrograph
- `nash` — Nash IUH (Instantaneous Unit Hydrograph)

---

## TODO / Przyszłe rozszerzenia

1. ~~Obliczanie CN z pokrycia terenu~~ ✅ Zaimplementowane (cn_tables + cn_calculator + land_cover)

2. ~~Dodatkowe metody tc~~ ✅ Zaimplementowane (FAA, Kerby, Kerby-Kirpich — Hydrolog v0.6.3)

3. **Eksport wyników** - eksport hydrogramu do CSV/Excel

4. **Podwójna analiza NMT** - analiza z/bez obszarów bezodpływowych (backlog)

---

## Przykład użycia API

### Generowanie hydrogramu

```bash
curl -X POST http://localhost:8000/api/generate-hydrograph \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 52.23,
    "longitude": 21.01,
    "duration": "1h",
    "probability": 10,
    "tc_method": "kirpich",
    "hietogram_type": "beta"
  }'
```

### Przykładowa odpowiedź

```json
{
  "watershed": {
    "boundary_geojson": {...},
    "outlet": {"latitude": 52.23, "longitude": 21.01, "elevation_m": 150.0},
    "area_km2": 45.3,
    "hydrograph_available": true,
    "morphometry": {
      "area_km2": 45.3,
      "perimeter_km": 32.1,
      "length_km": 12.5,
      "elevation_min_m": 150.0,
      "elevation_max_m": 520.0,
      "elevation_mean_m": 340.0,
      "mean_slope_m_per_m": 0.025,
      "channel_length_km": 8.2,
      "channel_slope_m_per_m": 0.045,
      "longest_flow_path_km": 14.2,
      "divide_flow_path_km": 13.8,
      "centroid_flow_path_km": 9.1,
      "cn": 72,
      "source": "Hydrograf",
      "crs": "EPSG:2180"
    },
    "longest_flow_path_geojson": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": ["..."]}}
  },
  "precipitation": {
    "total_mm": 45.0,
    "duration_min": 60.0,
    "probability_percent": 10,
    "timestep_min": 5.0,
    "times_min": [0, 5, 10, "..."],
    "intensities_mm": [0.5, 1.2, 2.1, "..."]
  },
  "hydrograph": {
    "times_min": [0, 5, 10, "..."],
    "discharge_m3s": [0, 0.1, 0.5, "..."],
    "peak_discharge_m3s": 12.5,
    "time_to_peak_min": 45.0,
    "total_volume_m3": 125000
  },
  "water_balance": {
    "total_precip_mm": 45.0,
    "total_effective_mm": 28.5,
    "runoff_coefficient": 0.63,
    "cn_used": 72,
    "retention_mm": 84.7,
    "initial_abstraction_mm": 16.9
  },
  "metadata": {
    "tc_min": 32.5,
    "tc_method": "kirpich",
    "hietogram_type": "beta",
    "uh_model": "scs"
  }
}
```

---

## Repozytorium Hydrologa

- **GitHub:** https://github.com/Daldek/Hydrolog.git
- **Branch:** `feature/routing-schematic` (the head of the stack `chore/nogat-2.1` and `feature/routing-*`; on GitHub)
- **Wersja:** 1.0.0.dev0, commit `1ffcd6b6badcd75e7ace9f2d59d4640830e176ff` (`develop` with the official inputs of tc, Nogat plan `2026-11-05-official-tc-inputs`)
- **Dokumentacja:** `docs/INTEGRATION.md`
- **Instalacja:** zaleznosc w `backend/pyproject.toml` (`[tool.uv.sources]`: `hydrolog = { git = "https://github.com/Daldek/Hydrolog.git", rev = "1ffcd6b6badcd75e7ace9f2d59d4640830e176ff" }`), instalowana przez `uv sync --locked`; the commit is on GitHub, so every machine resolves it; the release replaces it with a tag (REL-5.3)

---

**Ostatnia aktualizacja:** 2026-10-25
