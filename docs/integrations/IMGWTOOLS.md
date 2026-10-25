# Integracja z IMGWTools

**Wersja:** 1.0
**Data:** 2026-10-25 (the head of IMGWTools, ADR-060)
**Status:** Aktywna

---

## 1. Przegląd

Hydrograf wykorzystuje [IMGWTools](https://github.com/Daldek/IMGWTools) (3.0.0, commit `a304521`) do automatycznego pobierania danych opadowych z IMGW (Instytut Meteorologii i Gospodarki Wodnej). Dane opadowe stanowią kluczowy input do generowania hydrogramów metodą SCS-CN.

### 1.1 Co to jest IMGWTools?

IMGWTools to biblioteka Python do:
- **Pobierania danych opadowych** z serwisu IMGW (maksymalne opady prawdopodobne — PMAXTP)
- **Udostępniania 3 rozkładów** statystycznych opadów: kwantylowy (KS), górna granica (SG), błąd estymacji (RB)
- **Obsługi 432 scenariuszy** per punkt (16 duracji x 27 prawdopodobieństw)

### 1.2 Dlaczego integracja?

| Problem | Rozwiązanie |
|---------|-------------|
| Ręczne pobieranie danych z IMGW | Automatyczne pobieranie przez `fetch_pmaxtp()` |
| Brak spójności formatów CSV | Ujednolicony obiekt `PrecipitationResult` |
| Punktowe dane wymagają interpolacji | Grid preprocessing + IDW w runtime |
| Manualny import do bazy danych | Pipeline INSERT ON CONFLICT z grid WGS84 |

**Decyzja:** ADR-008 — użycie IMGWTools zamiast manualnych importów CSV.

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
│  │     └─→ IMGWTools → serwis IMGW                             │   │
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
│  │  get_precipitation(centroid, duration, probability)          │   │
│  │  → 4 najbliższe punkty (ST_Distance)                       │   │
│  │  → Interpolacja IDW (power=2)                               │   │
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

**The `IMGW_` prefix (IMGWTools 3.0.0):** `imgw_grid_spacing_km` and `imgw_rate_limit_delay_s` are settings of Hydrograf (`core/config.py`, `.env.example`), read from `IMGW_GRID_SPACING_KM` and `IMGW_RATE_LIMIT_DELAY_S`, and `IMGW_` is also the prefix of the settings of IMGWTools (`IMGW_ROOT`, `IMGW_DATA_DIR`, `IMGW_RATE_LIMIT`, ...), which it reads from the environment, from `.env` in the working directory and from `nogat.toml` when `imgwtools` is imported. IMGWTools ignores the names it does not know, so both coexist (checked with the repository `.env` and with exported variables, and `fetch_pmaxtp` works); a setting that IMGWTools adds under one of the two names would be read by both. Hydrograf sets no variable that IMGWTools renamed (`IMGW_STORE_ROOT` is `IMGW_ROOT`, `IMGW_DATA_DIR` is `IMGW_REFERENCE_DIR` for the reference data).

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

## 5. Moduły Hydrografa korzystające z IMGWTools

| Moduł | Import / Użycie | Zastosowanie |
|-------|-----------------|--------------|
| `scripts/preprocess_precipitation.py` | `from imgwtools import fetch_pmaxtp` | Grid preprocessing — pobieranie danych opadowych per punkt |
| `scripts/analyze_watershed.py` | `from imgwtools import fetch_pmaxtp` | Skrypt CLI — fetch opadu dla pojedynczego punktu |
| `core/precipitation.py` | (pośrednio, operuje na tabeli `precipitation_data`) | Walidacja, interpolacja IDW |
| `api/endpoints/hydrograph.py` | (pośrednio, przez `get_precipitation()`) | Endpoint generowania hydrogramu |
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

### 6.3 Struktura odpowiedzi IMGWTools

```python
from imgwtools import fetch_pmaxtp

result = fetch_pmaxtp(latitude=52.23, longitude=21.01)

# Trzy rozkłady statystyczne:
result.data.ks   # Rozkład kwantylowy (domyślny)
result.data.sg   # Górna granica przedziału ufności
result.data.rb   # Błąd estymacji

# Każdy rozkład zawiera macierz:
# 16 duracji × 27 prawdopodobieństw = 432 scenariusze
```

**Dostępne duracje:** 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h

**Dostępne prawdopodobieństwa:** od 0.01% do 99.99% (27 wartości)

---

## 7. API endpoints

### 7.1 `POST /api/generate-hydrograph`

Wewnętrznie korzysta z danych opadowych:
1. Centroid zlewni → `get_precipitation(centroid, duration, probability)`
2. Interpolacja IDW z tabeli `precipitation_data`
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

## 8. Interpolacja IDW

### 8.1 Moduł: `core/precipitation.py`

Interpolacja Inverse Distance Weighting (IDW) dla centroidu zlewni:

```
                    Σ (precipitation_i / distance_i²)
precipitation = ──────────────────────────────────────
                      Σ (1 / distance_i²)
```

**Parametry:**
- **Liczba sąsiadów:** 4 (najbliższe punkty z `precipitation_data`)
- **Wykładnik (power):** 2
- **Wyszukiwanie:** ST_Distance na geometriach EPSG:2180

### 8.2 Walidacja

Moduł `core/precipitation.py` waliduje:
- Czy duracja jest w dopuszczonym zbiorze
- Czy prawdopodobieństwo jest w dopuszczonym zbiorze
- Czy znaleziono wystarczającą liczbę punktów do interpolacji

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
| Typ danych | Dane punktowe — interpolacja IDW dla centroidu zlewni |
| Rozkład domyślny | KS (kwantylowy) — SG i RB dostępne w bazie, ale nieużywane w API |
| Aktualizacja | Wymagany manualny re-run preprocessingu przy aktualizacji danych IMGW |
| Brak agregacji areowej | Opad interpolowany dla centroidu, nie uśredniany po powierzchni zlewni |

### 10.2 Przyszłe rozszerzenia

- [ ] **Agregacja powierzchniowa** — uśrednianie opadu po powierzchni zlewni (poligony Thiessena lub grid)
- [ ] **Użycie rozkładów SG/RB** — udostępnienie górnej granicy i błędu estymacji w API
- [ ] **Automatyczna aktualizacja** — cykliczne odświeżanie danych opadowych
- [ ] **Cache HTTP** — cachowanie odpowiedzi IMGWTools dla tych samych współrzędnych
- [ ] **Równoległy download** — async/parallel fetch dla przyspieszenia preprocessingu

---

## 11. Wymagania

### 11.1 Instalacja

```
# W backend/pyproject.toml (dependencies):
imgwtools @ git+https://github.com/Daldek/IMGWTools.git@a30452182b01f47cc18e48466da4edf4d0c8cb6a
```

### 11.2 Repozytorium

- **GitHub:** https://github.com/Daldek/IMGWTools
- **Branch:** `feature/data-output` (not pushed; the pin is a commit, REL-5.3, ADR-060)
- **Wersja:** 3.0.0 (untagged), commit `a30452182b01f47cc18e48466da4edf4d0c8cb6a`
- **`fetch_pmaxtp`:** `fetch_pmaxtp(latitude, longitude, *, method="POT", timeout=30.0, validate_coords=True)`; `method` was positional in 2.1.0 and Hydrograf passes only `latitude=` and `longitude=`. Failures are `IMGWValidationError`, `IMGWConnectionError` and `IMGWDataError`; both call sites of Hydrograf catch these three and let every other exception surface (`tests/unit/test_imgw_call_sites.py`).
- **uv:** the commit is not on GitHub, so a machine needs it in the uv git cache before `uv lock` or `uv sync` (`docs/PROGRESS.md`, Next 2); the release replaces it with the tag.

---

**Wersja dokumentu:** 1.0
**Ostatnia aktualizacja:** 2026-10-25
