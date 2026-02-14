# Integracja Hydrograf ↔ Hydrolog

**Data utworzenia:** 2026-01-20
**Status:** ✅ Zaimplementowane (CP3)

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
│  - Wyznaczanie zlewni z NMT (flow network)                      │
│  - Obliczanie parametrów geometrycznych z boundary/cells        │
│  - Obliczanie statystyk wysokości z DEM                         │
│  - Obliczanie CN z pokrycia terenu                              │
│  - Interpolacja opadów (IDW/Thiessen)                           │
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

### 2. Schematy Pydantic: `backend/models/schemas.py`

**Status:** ✅ Zaimplementowane

Dodane klasy:
- `MorphometricParameters` - parametry morfometryczne zgodne z Hydrolog
- `HydrographRequest` - request do generowania hydrogramu
- `HydrographResponse` - pełna odpowiedź z hydrogramem
- `PrecipitationInfo` - informacje o opadzie i hietogramie
- `HydrographInfo` - dane hydrogramu (times, discharge, peak, volume)
- `WaterBalance` - bilans wodny (CN, retention, effective rainfall)
- `HydrographMetadata` - metadane obliczeń (tc, metoda, model UH)

### 3. Endpoint: `POST /api/generate-hydrograph`

**Status:** ✅ Zaimplementowane

**Plik:** `backend/api/endpoints/hydrograph.py`

**Parametry wejściowe:**
- `latitude`, `longitude` - współrzędne WGS84
- `duration` - czas trwania opadu: 15min, 30min, 1h, 2h, 6h, 12h, 24h
- `probability` - prawdopodobieństwo: 1%, 2%, 5%, 10%, 20%, 50%
- `timestep_min` - krok czasowy (default: 5 min)
- `tc_method` - metoda tc: kirpich, scs_lag, giandotti
- `hietogram_type` - typ hietogramu: beta, block, euler_ii

**Ograniczenia:**
- Maksymalna powierzchnia zlewni: 250 km² (limit metody SCS-CN)

### 4. Rozszerzenie endpointu watershed

**Status:** ✅ Zaimplementowane

Endpoint `/api/delineate-watershed` zwraca teraz `morphometry` w odpowiedzi.

---

## Lista zmian - podsumowanie

### Hydrograf (CP3)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/requirements.txt` | + hydrolog (git develop) | ✅ |
| `backend/core/morphometry.py` | NOWY - 6 funkcji obliczeniowych | ✅ |
| `backend/models/schemas.py` | + 7 nowych klas Pydantic | ✅ |
| `backend/api/endpoints/watershed.py` | + morphometry w response | ✅ |
| `backend/api/endpoints/hydrograph.py` | NOWY - endpoint hydrogramu | ✅ |
| `backend/api/main.py` | + router hydrograph | ✅ |
| `backend/tests/unit/test_morphometry.py` | NOWY - 24 testy jednostkowe | ✅ |
| `backend/tests/integration/test_hydrograph.py` | NOWY - 16 testów integracyjnych | ✅ |

### Hydrolog

| Plik | Zmiana | Status |
|------|--------|--------|
| `hydrolog/morphometry/watershed_params.py` | WatershedParameters | ✅ |
| `hydrolog/morphometry/geometric.py` | + `from_dict()` | ✅ |
| `hydrolog/morphometry/terrain.py` | + `from_dict()` | ✅ |

---

## TODO / Przyszłe rozszerzenia

1. **Obliczanie CN z pokrycia terenu** - obecnie używany jest domyślny CN=75
   - Wymaga integracji z danymi land_cover (Corine/OSM)
   - Lokalizacja: `backend/core/morphometry.py` i `hydrograph.py`

2. **Dodatkowe metody tc** - rozszerzenie o inne metody czasu koncentracji

3. **Eksport wyników** - eksport hydrogramu do CSV/Excel

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
      "cn": 75,
      "source": "Hydrograf",
      "crs": "EPSG:2180"
    }
  },
  "precipitation": {
    "total_mm": 45.0,
    "duration_min": 60.0,
    "probability_percent": 10,
    "timestep_min": 5.0,
    "times_min": [0, 5, 10, ...],
    "intensities_mm": [0.5, 1.2, 2.1, ...]
  },
  "hydrograph": {
    "times_min": [0, 5, 10, ...],
    "discharge_m3s": [0, 0.1, 0.5, ...],
    "peak_discharge_m3s": 12.5,
    "time_to_peak_min": 45.0,
    "total_volume_m3": 125000
  },
  "water_balance": {
    "total_precip_mm": 45.0,
    "total_effective_mm": 28.5,
    "runoff_coefficient": 0.63,
    "cn_used": 75,
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
- **Dokumentacja:** `docs/INTEGRATION.md`

---

**Ostatnia aktualizacja:** 2026-01-20
