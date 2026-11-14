# Integracja z Obserwatorem

**Wersja:** 1.5
**Data:** 2026-11-14 (the pin `0394af7` of the release set candidate-4 of Nogat, was `f9f4ee7`: Obserwator splits its store into a raw root and a data root, its ADR-017, takes the station details of hydro.imgw.pl, its ADR-021, and adds its GUI and stored analyses; `fetch_pmaxtp`, which reads no store, and the three exceptions Hydrograf catches are unchanged). 2026-11-14 (audit against the code of 2026-11-14: the pin `f9f4ee7` is that of the release set candidate-3 of Nogat; the `source` column holds `IMGW_PMAXTP` and only the KS quantiles are stored; `PMaXTPResult`; `ObserwatorValidationError` of `get_precipitation`; `GET /api/scenarios` in `api/endpoints/hydrograph.py`; the scope of the tests). 2026-11-10: Hydrograf pins Obserwator `f9f4ee7`, 3.0.0.dev0, the release set candidate-2 of Nogat (was `1ee5457`), and imports the package `obserwator`
**Status:** Aktywna

---

## 1. Przegląd

Hydrograf wykorzystuje [Obserwatora](https://github.com/Daldek/Obserwator) (do v3.0.0 IMGWTools) do automatycznego pobierania danych opadowych z IMGW (Instytut Meteorologii i Gospodarki Wodnej). Dane opadowe stanowią kluczowy input do generowania hydrogramów metodą SCS-CN.

**Pin i pakiet:** Hydrograf pins the commit `0394af7` of Obserwator (version 3.0.0.dev0; the release set candidate-4 of Nogat) and imports the package `obserwator` (`fetch_pmaxtp`, the exceptions `ObserwatorConnectionError`, `ObserwatorDataError`, `ObserwatorValidationError`). Dokumenty wyniku i błędu Obserwatora (standard Nogata 1.0) nie dotyczą Hydrografa, który woła tylko funkcję biblioteki. `fetch_pmaxtp` asks IMGW-PIB directly and reads no store, so Obserwator's raw and data roots (its ADR-017, `OBSERWATOR_RAW_ROOT`, `OBSERWATOR_ROOT`) are not set for Hydrograf.

### 1.1 Co to jest Obserwator?

Obserwator to biblioteka Python do:
- **Pobierania danych opadowych** z serwisu IMGW (maksymalne opady prawdopodobne — PMAXTP)
- **Three series** of the PMAXTP precipitation: the quantiles (KS), their upper confidence bounds (SG) and the estimation errors (RB)
- **Obsługi 432 scenariuszy** per punkt (16 duracji x 27 prawdopodobieństw)

### 1.2 Dlaczego integracja?

| Problem | Rozwiązanie |
|---------|-------------|
| Ręczne pobieranie danych z IMGW | Automatyczne pobieranie przez `fetch_pmaxtp()` |
| Brak spójności formatów CSV | One object, `PMaXTPResult` (its `data`, a `PMaXTPData`) |
| Punktowe dane wymagają interpolacji | Grid preprocessing; at runtime the watershed mean by Thiessen polygons (ADR-069) |
| Manualny import do bazy danych | Pipeline INSERT ON CONFLICT z grid WGS84 |

**Decyzja:** ADR-008 — użycie IMGWTools (obecnie Obserwator) zamiast manualnych importów CSV.

---

## 2. Architektura Integracji

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PRZEPŁYW DANYCH                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Użytkownik / Panel Admin                                           │
│      │                                                              │
│      │ (bbox WGS84 / --skip-precipitation)                          │
│      ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    bootstrap.py                              │   │
│  │  Krok 6: Preprocessing opadów (opcjonalny)                  │   │
│  └─────────────────┬───────────────────────────────────────────┘   │
│                    │                                                │
│                    ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │            preprocess_precipitation.py                       │   │
│  │                                                             │   │
│  │  1. BBox WGS84 → siatka punktów (grid_spacing_km)          │   │
│  │  2. Per punkt: fetch_pmaxtp(lat, lon)                       │   │
│  │     └─→ Obserwator → serwis IMGW                            │   │
│  │  3. Rate limiting (0.5s między żądaniami)                   │   │
│  │  4. INSERT ON CONFLICT DO UPDATE → PostGIS                  │   │
│  │  5. Reprojekcja → EPSG:2180                                 │   │
│  └─────────────────┬───────────────────────────────────────────┘   │
│                    │                                                │
│                    ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │               PostgreSQL + PostGIS                           │   │
│  │                                                             │   │
│  │  Tabela: precipitation_data                                 │   │
│  │  (id, geom EPSG:2180, duration, probability,               │   │
│  │   precipitation_mm, source, updated_at)                     │   │
│  └─────────────────┬───────────────────────────────────────────┘   │
│                    │                                                │
│                    │  Runtime (API request)                         │
│                    ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              core/precipitation.py                           │   │
│  │                                                             │   │
│  │  thiessen_cells(boundary) → areal_depth(cells, D, p)         │   │
│  │  → Thiessen polygons of the grid points in the watershed    │   │
│  │  → mean weighted by area (Hydrolog thiessen_polygons)       │   │
│  │  → precipitation_mm                                         │   │
│  └─────────────────┬───────────────────────────────────────────┘   │
│                    │                                                │
│                    ▼                                                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Endpoint: POST /api/generate-hydrograph                    │   │
│  │  → Hietogram → Hydrolog → Hydrogram                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Konfiguracja

The grid of the PMAXTP points is set by the options of `scripts/preprocess_precipitation.py`:
`--spacing` (km, default 2.0) and `--delay` between the requests to IMGW (s, default 0.5);
step 6 of the bootstrap uses the defaults. A smaller spacing gives a finer interpolation and
a longer preprocessing (more points, more HTTP requests). Obserwator reads its own settings
from `OBSERWATOR_<KEY>`, the shared `NOGAT_<KEY>` and `nogat.toml`.

---

## 4. Tabela bazy danych: `precipitation_data`

| Kolumna | Typ | Opis |
|---------|-----|------|
| `id` | SERIAL | PK |
| `geom` | GEOMETRY(Point, 2180) | Lokalizacja punktu pomiarowego (EPSG:2180) |
| `duration` | VARCHAR | Czas trwania opadu (np. `5min`, `1h`, `24h`) |
| `probability` | FLOAT | Prawdopodobieństwo [%] |
| `precipitation_mm` | FLOAT | Wysokość opadu [mm] |
| `source` | VARCHAR | The source of the data: `IMGW_PMAXTP` (the preprocessing stores only the KS quantiles, `get_precipitation`) |
| `updated_at` | TIMESTAMP | Data ostatniej aktualizacji |

**Indeksy:** a GiST spatial index on `geom` (the grid points near a watershed and the nearest points of the IDW, KNN `<->`), btree indexes on `duration`, `probability` and the pair.

---

## 5. Moduły Hydrografa korzystające z Obserwatora

| Moduł | Import / Użycie | Zastosowanie |
|-------|-----------------|--------------|
| `scripts/preprocess_precipitation.py` | `from obserwator import fetch_pmaxtp` | Grid preprocessing — pobieranie danych opadowych per punkt |
| `scripts/analyze_watershed.py` | `from obserwator import fetch_pmaxtp` | Skrypt CLI — fetch opadu dla pojedynczego punktu |
| `core/precipitation.py` | (pośrednio, operuje na tabeli `precipitation_data`) | Validation, the watershed mean by Thiessen polygons, IDW at a point without a boundary |
| `api/endpoints/hydrograph.py` | (pośrednio, przez `areal_depth()` / `point_depth()`) | Endpoint generowania hydrogramu |
| `api/endpoints/hydrograph.py` (`GET /api/scenarios`) | (pośrednio, definiuje dostępne duracje/prawdopodobieństwa) | Lista scenariuszy |

---

## 6. Pipeline preprocessing

### 6.1 Miejsce w bootstrap.py

Preprocessing opadów to **krok 6** w orchestratorze `bootstrap.py`. Może być pominięty flagą `--skip-precipitation`.

```bash
# Pełny bootstrap (z opadami)
.venv/bin/python -m scripts.bootstrap \
    --bbox "20.8,52.1,21.2,52.4"

# Bootstrap bez opadów
.venv/bin/python -m scripts.bootstrap \
    --bbox "20.8,52.1,21.2,52.4" \
    --skip-precipitation
```

### 6.2 Algorytm preprocessingu

1. **Parsowanie bbox** — WGS84 (min_lon, min_lat, max_lon, max_lat)
2. **Generowanie siatki** — grid punktów co `--spacing` km w obrębie bbox
3. **Iteracja po punktach** — dla każdego punktu siatki:
   - `fetch_pmaxtp(latitude=..., longitude=...)` → `PMaXTPResult`
   - Rate limiting: `sleep(--delay)` między żądaniami
4. **INSERT do bazy** — `INSERT ON CONFLICT DO UPDATE` (aktualizacja istniejących punktów)
5. **Reprojekcja** — geometrie przechowywane w EPSG:2180

### 6.3 Struktura odpowiedzi Obserwatora

```python
from obserwator import fetch_pmaxtp

result = fetch_pmaxtp(latitude=52.23, longitude=21.01)

# Trzy rozkłady statystyczne:
result.data.ks   # Rozkład kwantylowy (domyślny)
result.data.sg   # Górna granica przedziału ufności
result.data.rb   # Błąd estymacji

# Każdy rozkład zawiera macierz:
# 16 duracji × 27 prawdopodobieństw = 432 scenariusze
```

**Dostępne duracje:** 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h

**Dostępne prawdopodobieństwa:** 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 3, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98, 98.5, 99, 99.5 i 99.9% (27 wartości). `PMaXTPData.get_precipitation(duration_minutes, probability_percent)` takes the percentage as a `float` and only one of these values; any other raises `ObserwatorValidationError` (`validation_error`).

---

## 7. API endpoints

### 7.1 `POST /api/generate-hydrograph`

Wewnętrznie korzysta z danych opadowych:
1. The Thiessen cells of the watershed (`pmaxtp_grid` of the delineation, or computed from the boundary on the full path) → `areal_depth(cells, duration, probability)`; without a boundary `point_depth()` (IDW at the point)
2. The mean of the scenario's depths at the grid points of `precipitation_data`, weighted by area
3. Wynikowy opad [mm] → hietogram → hydrolog → hydrogram

**Parametry opadowe w request:**
- `duration` — czas trwania opadu (np. `1h`, `24h`)
- `probability` — prawdopodobieństwo [%] (np. `1`, `10`, `50`)

**The terms of PMAXTP** (https://klimat.imgw.pl/opady-maksymalne; Nogat DEV-20.2, DEV-20.7,
ADR-083): every product with the data, all of them processed here, carries the source with
the address of the PMAXTP page, the note that the data were processed and the monograph of
the project, then the link to the PMAXTP terms (Nogat ECO-065: linked, never summarised). The response has them in `attribution` and `terms_notice`, from
`backend/core/attribution.py`.

### 7.2 `GET /api/scenarios`

Zwraca dostępne kombinacje parametrów:
- Lista duracji
- Lista prawdopodobieństw
- Metody tc, typy hietogramów itp.

---

## 8. The design depth (ADR-069)

### 8.1 Module: `core/precipitation.py`

The design depth of a watershed is the mean of the PMAXTP grid points weighted by the
areas of their Thiessen polygons inside it (KZGW 2017, ch. II, eq. 2.1):

```
                Σ (precipitation_i × area_i)
precipitation = ────────────────────────────
                        Σ area_i
```

- `thiessen_cells(boundary, db)`: the grid points within 5 km of the watershed's bounding
  box, their Voronoi polygons clipped to the watershed (`area_km2` > 0).
- `areal_depth(cells, duration, probability, db)`: Hydrolog's `thiessen_polygons` over
  the scenario's depths at the cells.
- `point_depth(point, duration, probability, db)`: without a boundary, Hydrolog's
  `inverse_distance_weighting` of the 4 nearest points (KNN `<->`, EPSG:2180), power 2.

### 8.2 Validation

`core/precipitation.py` checks:
- that the duration and the probability are in the allowed sets;
- that every cell given back is a point of the grid (within 1 m), else
  `UnknownGridPointError` (400 `pmaxtp_grid_point_unknown` for the request's
  `pmaxtp_grid`).

---

## 9. Testy

### 9.1 Testy jednostkowe

```bash
# Testy precipitation (walidacja, IDW, scenariusze)
cd backend && .venv/bin/python -m pytest tests/unit/test_precipitation.py -v

# Testy preprocess_precipitation (bbox parsing, grid generation)
cd backend && .venv/bin/python -m pytest tests/unit/test_preprocess_precipitation.py -v
```

### 9.2 Zakres testów

| Plik testowy | Zakres |
|-------------|--------|
| `test_precipitation.py` | The validation of the durations and probabilities, the Thiessen cells, the watershed mean (`areal_depth`), the IDW at a point (`point_depth`), the duration mapping |
| `test_preprocess_precipitation.py` | The bbox parsing and the grid of points |

---

## 10. Ograniczenia i przyszły rozwój

### 10.1 Obecne ograniczenia

| Ograniczenie | Opis |
|-------------|------|
| Zasięg geograficzny | Tylko Polska (14.0-24.2°E, 49.0-54.9°N) |
| Typ danych | Dane punktowe — the watershed mean by Thiessen polygons (ADR-069); IDW at a point without a boundary |
| Rozkład domyślny | Only KS (the quantiles) is stored in `precipitation_data`; SG and RB are neither stored nor used |
| Aktualizacja | Wymagany manualny re-run preprocessingu przy aktualizacji danych IMGW |
| Areal reduction | The watershed mean of point depths is reduced only by the user's own `areal_reduction_factor` (none by default; KZGW 2017, p. 105: up to 10 % for 10–100 km²); the author's decision (ADR-069) |

### 10.2 Przyszłe rozszerzenia

- [x] **Agregacja powierzchniowa** — the watershed mean by Thiessen polygons and the user's optional areal reduction factor (ADR-069, 2026-11-05)
- [ ] **Użycie rozkładów SG/RB** — udostępnienie górnej granicy i błędu estymacji w API
- [ ] **Automatyczna aktualizacja** — cykliczne odświeżanie danych opadowych
- [ ] **Cache HTTP** — cachowanie odpowiedzi Obserwatora dla tych samych współrzędnych
- [ ] **Równoległy download** — async/parallel fetch dla przyspieszenia preprocessingu

---

## 11. Wymagania

### 11.1 Instalacja

```
# In backend/pyproject.toml ([tool.uv.sources]; the range in dependencies is "obserwator>=3.0.0.dev0,<4"):
obserwator = { git = "https://github.com/Daldek/Obserwator.git", rev = "0394af7c66b60cccb88f14b6118893b78443dc21" }
```

### 11.2 Repozytorium

- **GitHub:** https://github.com/Daldek/Obserwator
- **Branch:** `develop` (on GitHub; the pin is a commit of the release set of Nogat, candidate-4)
- **Wersja:** 3.0.0.dev0 (untagged), commit `0394af7c66b60cccb88f14b6118893b78443dc21`
- **`fetch_pmaxtp`:** `fetch_pmaxtp(latitude, longitude, *, method="POT", timeout=30.0, validate_coords=True)`; `method` was positional in 2.1.0 and Hydrograf passes only `latitude=` and `longitude=`. Failures are `ObserwatorValidationError`, `ObserwatorConnectionError` and `ObserwatorDataError` (`IMGW*Error` before the rename); both call sites of Hydrograf catch these three and let every other exception surface (`tests/unit/test_imgw_call_sites.py`).
- **uv:** the commit is on GitHub, so `uv lock`, `uv sync --locked` and the image build resolve it anywhere; the release replaces it with a tag of Obserwator.

---

**Wersja dokumentu:** 1.4
**Ostatnia aktualizacja:** 2026-11-14
