# Technical Debt - Hydrograf

Lista znanych problemów technicznych do naprawy w przyszłych iteracjach.

---

## Hardcoded Values (Q3.9)

**Akcja:** ~~Utworzyć `backend/core/constants.py` z wszystkimi stałymi.~~ ZREALIZOWANE (v0.4.0, `core/constants.py` — CRS, konwersje jednostek, domyslne CN, limity zlewni i grafu).

### Stałe jednostek konwersji — CZESCIOWO ZREALIZOWANE

Stale `M_PER_KM` i `M2_PER_KM2` istnieja w `core/constants.py`, ale nie sa uzywane w modulach `core/`:

| Wartość | Lokalizacja | Status |
|---------|-------------|--------|
| `1000.0` (m/km) | `core/morphometry.py` ×4 (linie 37, 73, 253, 486) | Nadal hardcoded — `M_PER_KM` nie importowane |
| `1_000_000` (m²/km²) | `core/watershed.py:252`, `core/morphometry.py:598` | Nadal hardcoded — `M2_PER_KM2` nie importowane |

**Uwaga:** `M2_PER_KM2` jest importowane w `api/endpoints/watershed.py`, ale moduly core nie korzystaja ze stalych — rozjazd miedzy intencja a realizacja.

### Parametry algorytmów

| Wartość | Lokalizacja | Opis | Status |
|---------|-------------|------|--------|
| `0.3` | `core/watershed.py:211` | Concave hull ratio | Nadal hardcoded |
| `75` | ~~`core/morphometry.py`~~ | Default CN value | ZREALIZOWANE — `DEFAULT_CN` w `constants.py`, uzywane przez `land_cover.py` |

### Identyfikatory CRS — CZESCIOWO ZREALIZOWANE

Stale `CRS_PL1992` i `CRS_WGS84` istnieja w `core/constants.py`, ale string `"EPSG:2180"` nadal pojawia sie bezposrednio w 7+ plikach core:

| Wartość | Lokalizacja | Status |
|---------|-------------|--------|
| `"EPSG:2180"` | `core/cn_calculator.py`, `core/hydrology.py` ×2, `core/morphometry.py`, `core/precipitation.py`, `core/raster_io.py`, `core/watershed_service.py` | Nadal hardcoded — `CRS_PL1992` nie importowane |
| `"EPSG:2180"` | `utils/geometry.py`, `models/schemas.py` | Nadal hardcoded |

### Inne

| Wartość | Lokalizacja | Status |
|---------|-------------|--------|
| `"Hydrograf"` | `core/morphometry.py:613` | Nadal hardcoded |

**Priorytet:** LOW — `constants.py` istnieje, ale moduly core trzeba zmigrowac do importu stalych zamiast literalow. Czysto kosmetyczny refactoring, bez ryzyka bledu.

---

## Hardcoded Secrets (S5.3)

### S5.3a - Default password w config.py — NADAL OTWARTE

```python
# backend/core/config.py:38
postgres_password: str = "hydro_password"

# backend/core/config.py:106 (_DEFAULT_CONFIG)
"password": "hydro_password",
```

**Problem:** Domyslne haslo `hydro_password` pojawia sie w 2 miejscach w `config.py` — w `Settings` (linia 38) i w `_DEFAULT_CONFIG` dla pipeline YAML (linia 106).

**Rekomendacja:**
- Usunac domyslna wartosc z `Settings`
- Wymagac zmiennej srodowiskowej `POSTGRES_PASSWORD`
- W `_DEFAULT_CONFIG` uzyc placeholder lub `os.getenv()`

### S5.3b - Connection string w migrations/env.py — NADAL OTWARTE

```python
# backend/migrations/env.py:27
database_url = os.getenv(
    "DATABASE_URL", "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db"
)
```

**Problem:** Hardcoded connection string jako fallback w `os.getenv()`.

**Rekomendacja:**
- Wymagac zmiennej `DATABASE_URL`
- Rzucac blad jesli brak konfiguracji

**Priorytet:** MEDIUM — w srodowisku dev nie stanowi zagrożenia, ale w produkcji moze prowadzic do uzywania domyslnych credentials jesli braknie zmiennej srodowiskowej.

---

## Brakujące testy dla scripts/ (T4.8) — CZESCIOWO ZREALIZOWANE

**Problem:** Wiekszość skryptow preprocessingu (`scripts/*.py`) miala niskie pokrycie testami.

**Stan testow (aktualizacja 2026-03-01, 568 test functions, 35 plikow):**
- `scripts/process_dem.py` — **47 testow** (`test_process_dem.py`)
- `scripts/import_landcover.py` — **16 testow** (`test_import_landcover.py`) — NOWE
- `utils/sheet_finder.py` — **32 testy** (`test_sheet_finder.py`) — NOWE
- `utils/raster_utils.py` — 0% pokrycia — NADAL BRAK
- `scripts/bootstrap.py` — **20 testow** (`test_bootstrap.py`) — NOWE
- `scripts/download_landcover.py` — **17 testow** (`test_download_landcover.py`) — NOWE
- `scripts/preprocess_precipitation.py` — **12 testow** (`test_preprocess_precipitation.py`) — NOWE
- `scripts/generate_dem_overlay.py` — 0% pokrycia
- `scripts/generate_tiles.py` — 0% pokrycia
- `scripts/prepare_area.py` — 0% pokrycia
- `scripts/download_dem.py` — 0% pokrycia
- `scripts/analyze_watershed.py` — 0% pokrycia

**Priorytet:** LOW (kluczowe moduly core pokryte, scripts to jednorazowe narzedzia pipeline)

> **Uwaga:** Pipeline CI/CD via GitHub Actions zostal wdrozony (v0.4.0). Obejmuje:
> lint (ruff check + format --check), testy (pytest), type-check (mypy).
> Kazdy push i PR na `develop`/`main` uruchamia pelna walidacje.

---

## Dokumentacja vs Kod (C2.x) — CZESCIOWO NIEAKTUALNE

**Problem:** Dokumentacja API jest nieaktualna wzgledem kodu.

**Znane rozbieznosci (stan na 2026-03-01):**
| Element | Dokumentacja | Kod | Status |
|---------|--------------|-----|--------|
| `outlet_coords` | `[lon, lat]` array | `outlet.latitude/longitude` (obiekt `OutletInfo`) | Prawdopodobnie naprawione — wymaga audytu ARCHITECTURE.md |
| `parameters` | sekcja `parameters` | `morphometry` (obiekt `MorphometricParameters`) | Wymaga audytu |
| `water_balance` | BRAK | nowa sekcja w response | Wymaga audytu |
| Panel admin | BRAK | 8 endpointow `/api/admin/*` + strona `/admin` | Brak w ARCHITECTURE.md |
| SSE bootstrap | BRAK | `/api/admin/bootstrap/stream` (text/event-stream) | Brak w ARCHITECTURE.md |
| MVT tiles | Czesciowo | 3 endpointy `/api/tiles/*` (streams, catchments, landcover) | Wymaga audytu |

**Akcja:** Zaktualizowac `docs/ARCHITECTURE.md` — sekcja API endpoints + nowe wzorce (admin, SSE, MVT).

**Priorytet:** MEDIUM

---

## ~~Wydajnosc bazy danych — bulk INSERT + indeksy (P1.x)~~ ZREALIZOWANE

**ZREALIZOWANE (ADR-028, migracja 015, sesja 33): Tabela `flow_network` wyeliminowana.**

Tabela `flow_network` (39.4M rekordow, 58% czasu pipeline) zostala calkowicie usunieta. Pipeline generuje `stream_network` i `stream_catchments` bezposrednio z rastra. Sekcje P1.1 i P1.2 sa nieaktualne — dotyczyly optymalizacji usunietej tabeli.

Brak referencji do `flow_network` w zadnym pliku `core/*.py` ani `api/endpoints/*.py` (zweryfikowane 2026-03-01).

---

## Checklist po migracjach DB (zapobieganie regresji)

**Problem:** Migracja 014 dodala `segment_idx` do `stream_network`, ale nie zaktualizowano `find_nearest_stream_segment()` w `watershed_service.py` — funkcja nadal pobierala `id` (auto-increment PK) i zwracala go jako `segment_idx`. Bug trwal przez 6 sesji (24-32).

**Checklist po kazdej migracji:**
1. `grep -r "TABLE_NAME" backend/` — znajdz WSZYSTKIE zapytania SQL do zmienionej tabeli
2. Sprawdz czy nowa/zmieniona kolumna jest uzywana poprawnie w kazdym zapytaniu
3. Sprawdz czy mapowanie wynikow (result.X → dict["Y"]) jest spojne z SQL SELECT
4. Uruchom istniejace testy integracyjne — jesli testy nie pokrywaja nowej kolumny, dodaj
5. `verify_graph()` przy starcie API — walidacja spojnosci danych miedzy tabelami

**Priorytet:** HIGH — cichy bug tral 6 sesji bez wykrycia

---

## f-string w logowaniu (L1.x) — NOWE

**Problem:** W 30 plikach backendu uzywane sa f-stringi w wywolaniach `logger.*()` zamiast lazy formatting z `%s`. Lacznie ~396 wystapien.

**Najczesciej w:**
- `scripts/analyze_watershed.py` (61 wystapien)
- `scripts/prepare_area.py` (46 wystapien)
- `scripts/download_dem.py` (31 wystapien)
- `scripts/download_landcover.py` (32 wystapien)
- `utils/raster_utils.py` (20 wystapien)
- `scripts/process_dem.py` (26 wystapien)
- `scripts/bootstrap.py` (18 wystapien)
- moduly core: `raster_io.py` (11), `cn_calculator.py` (9), `land_cover.py` (7), `hydrology.py` (7), `watershed.py` (5)

**Standard (z DEVELOPMENT_STANDARDS.md sekcja 14.3):**
```python
# DOBRZE — lazy evaluation z %s
logger.info("Watershed area: %s km2", area_km2)

# ZLE — f-string (ewaluowany nawet jesli poziom logowania filtruje)
logger.info(f"Watershed area: {area_km2} km2")
```

**Priorytet:** LOW — nie wplywa na poprawnosc, minimalny impact na wydajnosc. Refactoring moze byc zautomatyzowany (ruff rule `G` — flake8-logging-format).

---

## traceback.print_exc() zamiast logger.exception() (L2.x) — NOWE

**Problem:** W kilku plikach uzywane jest `import traceback; traceback.print_exc()` zamiast `logger.exception()`.

**Lokalizacje:**
- `core/cn_calculator.py:331-333`
- `scripts/prepare_area.py:330`
- `scripts/analyze_watershed.py:414-416, 1310-1312`

**Rekomendacja:** Zamienic na `logger.exception("Opis bledu")` — automatycznie loguje traceback i szanuje konfiguracje loggera.

**Priorytet:** LOW

---

## TODO w kodzie (T5.x) — NOWE

**Problem:** Jeden aktywny TODO w kodzie produkcyjnym (po wylaczeniu .venv):

| Plik | Linia | Tresc | Priorytet |
|------|-------|-------|-----------|
| `core/cn_calculator.py:198` | `# TODO: Analiza pliku GeoPackage` | Funkcja `get_land_cover_stats()` zwraca puste `{}` po pobraniu GeoPackage — brak parsowania | MEDIUM |

**Kontekst:** Funkcja `get_land_cover_stats()` pobiera plik pokrycia terenu z Kartografa, ale nie parsuje go — zwraca pusty slownik i fallbackuje do domyslnych wartosci. To oznacza, ze obliczenie CN opiera sie na szacunkowych (nie rzeczywistych) danych o pokryciu terenu gdy uzywany jest ten sciezka kodu.

**Priorytet:** MEDIUM — wplywa na dokladnosc obliczen CN w sciezce Kartograf

---

*Ostatnia aktualizacja: 2026-03-01*
