# Integracja Hydrograf ↔ Hydrolog

**Data utworzenia:** 2026-01-20
**Ostatnia aktualizacja:** 2026-03-01
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
│  - Interpolacja opadów (IDW/Thiessen, IMGWTools PMAXTP)         │
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
│  - Czas koncentracji (Kirpich, SCS Lag, Giandotti)              │
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
  "cn": 72,
  "source": "Hydrograf",
  "crs": "EPSG:2180"
}
```

---

## Zaimplementowane komponenty

### 1. Moduł: `backend/core/morphometry.py`

**Status:** ✅ Zaimplementowane

Funkcje:
- `calculate_perimeter_km(boundary)` - obwód zlewni z boundary.length
- `calculate_watershed_length_km(cells, outlet)` - max odległość od ujścia
- `calculate_elevation_stats(cells)` - min/max/mean wysokości (ważona po area)
- `calculate_mean_slope(cells)` - średni spadek ważony po area (% → m/m)
- `find_main_stream(cells, outlet)` - długość i spadek głównego cieku (algorytm najdłuższej ścieżki)
- `build_morphometric_params(cells, boundary, outlet, cn)` - kompletny dict dla Hydrologa

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
from hydrolog.runoff import HydrographGenerator
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
9. Pobranie opadu (interpolacja IDW z tabeli precipitation_data)
10. **Hydrolog:** `WatershedParameters.from_dict()` → `calculate_tc()`
11. **Hydrolog:** Hietogram (Beta/Block/Euler II) → `generate()`
12. **Hydrolog:** `HydrographGenerator` → `generate()`
13. Budowa odpowiedzi JSON

**Parametry wejściowe:**
- `latitude`, `longitude` - współrzędne WGS84
- `duration` - czas trwania opadu: 15min, 30min, 1h, 2h, 6h, 12h, 24h
- `probability` - prawdopodobieństwo: 1%, 2%, 5%, 10%, 20%, 50%
- `timestep_min` - krok czasowy (default: 5 min)
- `tc_method` - metoda tc: kirpich, scs_lag, giandotti
- `hietogram_type` - typ hietogramu: beta, block, euler_ii

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
| `api/endpoints/hydrograph.py` | `WatershedParameters`, `BetaHietogram`, `BlockHietogram`, `EulerIIHietogram`, `HydrographGenerator` | Endpoint API generowania hydrogramu |
| `scripts/analyze_watershed.py` | `WatershedParameters`, `BetaHietogram`, `SCSCN`, `HydrographGenerator`, `SCSUnitHydrograph` | Skrypt CLI pełnej analizy |
| `core/morphometry.py` | `WatershedParameters` (w docstring/example) | Dokumentacja formatu wymiany |
| `tests/unit/test_morphometry.py` | `WatershedParameters` | Test kompatybilności formatu |

---

## Lista zmian - podsumowanie

### Hydrograf (CP3+)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/requirements.txt` | + hydrolog (v0.5.2) | ✅ |
| `backend/core/morphometry.py` | 6 funkcji obliczeniowych | ✅ |
| `backend/core/morphometry_raster.py` | Obliczenia rastrowe (slope, aspect, TWI, Strahler) | ✅ |
| `backend/core/catchment_graph.py` | In-memory graf, BFS, trace_main_channel | ✅ |
| `backend/core/watershed_service.py` | build_morph_dict_from_graph, boundary smoothing | ✅ |
| `backend/core/cn_calculator.py` | Obliczanie CN z Kartografa (HSG + land cover) | ✅ |
| `backend/core/cn_tables.py` | Tablice CN dla BDOT10k + BUBD | ✅ |
| `backend/core/land_cover.py` | CN z tabeli land_cover (spatial intersection) | ✅ |
| `backend/models/schemas.py` | 7 klas Pydantic (MorphometricParameters, etc.) | ✅ |
| `backend/api/endpoints/watershed.py` | + morphometry w response | ✅ |
| `backend/api/endpoints/hydrograph.py` | Endpoint hydrogramu (CatchmentGraph BFS) | ✅ |
| `backend/api/endpoints/select_stream.py` | Wybór cieku (snap-to-stream + BFS) | ✅ |
| `backend/api/main.py` | + router hydrograph | ✅ |
| `backend/scripts/analyze_watershed.py` | Skrypt CLI pełnej analizy z Hydrologiem | ✅ |
| `backend/tests/unit/test_morphometry.py` | 24+ testy jednostkowe | ✅ |
| `backend/tests/integration/test_hydrograph.py` | 16 testów integracyjnych | ✅ |

### Hydrolog

| Plik | Zmiana | Status |
|------|--------|--------|
| `hydrolog/morphometry/watershed_params.py` | WatershedParameters | ✅ |
| `hydrolog/morphometry/geometric.py` | + `from_dict()` | ✅ |
| `hydrolog/morphometry/terrain.py` | + `from_dict()` | ✅ |

---

## Uwaga: channel_slope vs stream_length

Od ADR-029 rozróżniamy dwa pomiary długości cieków:

- **`aggregate_stats()["stream_length_km"]`** = suma długości CAŁEJ sieci cieków (do drainage density)
- **`trace_main_channel()`** = długość GŁÓWNEGO cieku (do channel_slope i tc)

Różnica może wynosić 2-10x. Channel slope MUSI być obliczany z głównego cieku.

---

## TODO / Przyszłe rozszerzenia

1. ~~Obliczanie CN z pokrycia terenu~~ ✅ Zaimplementowane (cn_tables + cn_calculator + land_cover)

2. **Dodatkowe metody tc** - rozszerzenie o inne metody czasu koncentracji

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
      "cn": 72,
      "source": "Hydrograf",
      "crs": "EPSG:2180"
    }
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
- **Branch:** develop
- **Wersja:** v0.5.2
- **Dokumentacja:** `docs/INTEGRATION.md`
- **Instalacja:** `pip install git+https://github.com/Daldek/Hydrolog.git@v0.5.2`

---

**Ostatnia aktualizacja:** 2026-03-01
