# Integracja z Obserwatorem

**Wersja:** 1.3
**Data:** 2026-11-04 (Hydrograf pins Obserwator `1ee5457`, 3.0.0.dev0, the release set of Nogat, and imports the package `obserwator`)
**Status:** Aktywna

---

## 1. Przegląd

Hydrograf wykorzystuje [Obserwatora](https://github.com/Daldek/Obserwator) (do v3.0.0 IMGWTools) do automatycznego pobierania danych opadowych z IMGW (Instytut Meteorologii i Gospodarki Wodnej). Dane opadowe stanowią kluczowy input do generowania hydrogramów metodą SCS-CN.

**Pin i pakiet:** Hydrograf przypina commit `f9f4ee7` Obserwatora (wersja 3.0.0.dev0, zestaw wydania Nogata candidate-2) i importuje pakiet `obserwator` (`fetch_pmaxtp`, wyjątki `ObserwatorConnectionError`, `ObserwatorDataError`, `ObserwatorValidationError`). Dokumenty wyniku i błędu Obserwatora (standard Nogata 1.0) nie dotyczą Hydrografa, który woła tylko funkcję biblioteki.

### 1.1 Co to jest Obserwator?

Obserwator to biblioteka Python do:
- **Pobierania danych opadowych** z serwisu IMGW (maksymalne opady prawdopodobne — PMAXTP)
- **Udostępniania 3 rozkładów** statystycznych opadów: kwantylowy (KS), górna granica (SG), błąd estymacji (RB)
- **Obsługi 432 scenariuszy** per punkt (16 duracji x 27 prawdopodobieństw)

### 1.2 Dlaczego integracja?

| Problem | Rozwiązanie |
|---------|-------------|
| Ręczne pobieranie danych z IMGW | Automatyczne pobieranie przez `fetch_pmaxtp()` |
| Brak spójności formatów CSV | Ujednolicony obiekt `PrecipitationResult` |
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

Parametry w pliku konfiguracyjnym YAML:

| Parametr | Typ | Domyślnie | Opis |
|----------|-----|-----------|------|
| `imgw_grid_spacing_km` | float | `2.0` | Odstęp siatki punktów pomiarowych [km] |
| `imgw_rate_limit_delay_s` | float | `0.5` | Opóźnienie między kolejnymi żądaniami do IMGW [s] |

**Uwaga:** Mniejszy `grid_spacing_km` daje dokładniejszą interpolację, ale wydłuża czas preprocessingu (więcej punktów = więcej żądań HTTP).

**The `IMGW_` prefix:** `imgw_grid_spacing_km` and `imgw_rate_limit_delay_s` are settings of Hydrograf (`core/config.py`, `.env.example`), read from `IMGW_GRID_SPACING_KM` and `IMGW_RATE_LIMIT_DELAY_S`; they name the provider IMGW and keep their names. Obserwator reads its own settings from `OBSERWATOR_<KEY>`, the shared `NOGAT_<KEY>` and `nogat.toml` (IMGWTools before the rename read `IMGW_*`), so the two sets of names no longer share a prefix.

---

## 4. Tabela bazy danych: `precipitation_data`

| Kolumna | Typ | Opis |
|---------|-----|------|
| `id` | SERIAL | PK |
| `geom` | GEOMETRY(Point, 2180) | Lokalizacja punktu pomiarowego (EPSG:2180) |
| `duration` | VARCHAR | Czas trwania opadu (np. `5min`, `1h`, `24h`) |
| `probability` | FLOAT | Prawdopodobieństwo [%] |
| `precipitation_mm` | FLOAT | Wysokość opadu [mm] |
| `source` | VARCHAR | Źródło danych (rozkład: `ks`, `sg`, `rb`) |
| `updated_at` | TIMESTAMP | Data ostatniej aktualizacji |

**Indeksy:** Spatial index na `geom` (GiST) dla szybkiego wyszukiwania sąsiadów (ST_Distance).

---

## 5. Moduły Hydrografa korzystające z Obserwatora

| Moduł | Import / Użycie | Zastosowanie |
|-------|-----------------|--------------|
| `scripts/preprocess_precipitation.py` | `from obserwator import fetch_pmaxtp` | Grid preprocessing — pobieranie danych opadowych per punkt |
| `scripts/analyze_watershed.py` | `from obserwator import fetch_pmaxtp` | Skrypt CLI — fetch opadu dla pojedynczego punktu |
| `core/precipitation.py` | (pośrednio, operuje na tabeli `precipitation_data`) | Validation, the watershed mean by Thiessen polygons, IDW at a point without a boundary |
| `api/endpoints/hydrograph.py` | (pośrednio, przez `areal_depth()` / `point_depth()`) | Endpoint generowania hydrogramu |
| `api/endpoints/scenarios.py` | (pośrednio, definiuje dostępne duracje/prawdopodobieństwa) | Lista scenariuszy |

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
2. **Generowanie siatki** — grid punktów co `imgw_grid_spacing_km` km w obrębie bbox
3. **Iteracja po punktach** — dla każdego punktu siatki:
   - `fetch_pmaxtp(latitude=..., longitude=...)` → `PMaXTPResult`
   - Rate limiting: `sleep(imgw_rate_limit_delay_s)` między żądaniami
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

**Dostępne prawdopodobieństwa:** 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 3, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98, 98.5, 99, 99.5 i 99.9% (27 wartości). `PMaXTPData.get_precipitation(duration_minutes, probability_percent)` przyjmuje procent jako `float` i tylko jedną z tych wartości; każda inna to `IMGWValidationError` (`validation_error`; w Obserwatorze `ObserwatorValidationError`).

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
| `test_precipitation.py` | Walidacja duracji/prawdopodobieństw, interpolacja IDW, obsługa brakujących danych |
| `test_preprocess_precipitation.py` | Parsowanie bbox, generowanie siatki punktów, logika INSERT |

---

## 10. Ograniczenia i przyszły rozwój

### 10.1 Obecne ograniczenia

| Ograniczenie | Opis |
|-------------|------|
| Zasięg geograficzny | Tylko Polska (14.0-24.2°E, 49.0-54.9°N) |
| Typ danych | Dane punktowe — the watershed mean by Thiessen polygons (ADR-069); IDW at a point without a boundary |
| Rozkład domyślny | KS (kwantylowy) — SG i RB dostępne w bazie, ale nieużywane w API |
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
obserwator = { git = "https://github.com/Daldek/Obserwator.git", rev = "f9f4ee7927ba520d3e82d3e289872090ae24e2ec" }
```

### 11.2 Repozytorium

- **GitHub:** https://github.com/Daldek/Obserwator
- **Branch:** `develop` (on GitHub; the pin is a commit of the release set of Nogat, candidate-2)
- **Wersja:** 3.0.0.dev0 (untagged), commit `f9f4ee7927ba520d3e82d3e289872090ae24e2ec`
- **`fetch_pmaxtp`:** `fetch_pmaxtp(latitude, longitude, *, method="POT", timeout=30.0, validate_coords=True)`; `method` was positional in 2.1.0 and Hydrograf passes only `latitude=` and `longitude=`. Failures are `ObserwatorValidationError`, `ObserwatorConnectionError` and `ObserwatorDataError` (`IMGW*Error` before the rename); both call sites of Hydrograf catch these three and let every other exception surface (`tests/unit/test_imgw_call_sites.py`).
- **uv:** the commit is on GitHub, so `uv lock`, `uv sync --locked` and the image build resolve it anywhere; the release replaces it with a tag of Obserwator.

---

**Wersja dokumentu:** 1.3
**Ostatnia aktualizacja:** 2026-11-04
