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
- ~~`utils/sheet_finder.py` — 32 testy (`test_sheet_finder.py`)~~ USUNIĘTE — zastąpione przez `utils/sheet_lookup.py` (cienki wrapper na `kartograf.find_sheets_for_bbox()`, 6 testów w `test_sheet_lookup.py`), pozyskiwanie danych wyłącznie przez Kartograf (ADR-057)
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

## Pamiec przetwarzania NMT (`process_dem`) — ZAPLANOWANE, NIE WDROZONE

**Problem:** bootstrap zlewni Kaczawy (513 arkuszy, raster 183 332 457 komorek 5 m) padl dwa razy na OOM 2026-10-29/30: przy limicie 8G + 8G swap na `zonal_stats` podzlewni progu 10000 (140 183 etykiety), przy 12G + 4G na TWI. Szczyt obecnego kodu to ~103 B/komorke, czyli ~19 GB przy 183M; ponad 13 GB zajmuje 8 roznych etapow (nie ma jednego waskiego gardla). Kotlina Klodzka (113M) zmiescila sie tylko dzieki domyslnemu swapowi Dockera (8G + 8G).

**Pomiar (2026-10-30):** wycinek 4000×4000 (16M komorek, 57% waznych jak w calej mozaice) mozaiki Kaczawy, jednorazowe kontenery bez sieci i bez bazy (`dry_run`), szczyt RSS per etap przeskalowany na 183M; zgodny z miejscami obu OOM. Prototyp poprawek (poza repo) dal identyczne bit w bit 13 rastrow, statystyki, cieki i zlewnie, a czas wycinka spadl z 287,5 s do 52,5 s.

**Glowne przyczyny:** pyflwdir 0.5.12 przy kazdym nowym `FlwdirRaster` buduje macierz doplywow n×7 int32 (28 B/komorke = 5,1 GB), a kod tworzy go 4 razy; pelne kopie float64 w `zonal_stats`, spadku, ekspozycji i TWI; sciezki splywu sledzone do ujscia calej zlewni (1,3 mld komorek, 5,2 GB) i dopiero potem przycinane; wyniki progu 10000 trzymane podczas liczenia progu 100000.

| # | Zmiana | Miejsce | Oszczednosc przy 183M | Naklad |
|---|--------|---------|-----------------------|--------|
| F7 | Usunac zbedne kopie: `astype(copy=False)` w `save_raster_geotiff`, `np.asarray` zamiast `fdir.astype(np.int16)`, `upstream_count` uint8, `del dem` po hydrologii, `label_raster`/`strahler_t` w `del` | `core/raster_io.py:73`, `core/stream_extraction.py:47,153,324`, `scripts/process_dem.py:760,780,954` | 0,2–0,8 GB na etap | maly |
| F1 | Statystyki podzlewni w jednym przejsciu numba (count, sumy, min, max, max hydrauliczny) + histogram numba; stare funkcje zostaja dla `generate_depressions.py` i testow | `core/stream_extraction.py:424-472`, `core/zonal_stats.py:44-171` | −9,4 GB (prog 100000: −10 GB) | sredni |
| F2 | Argmax per etykieta w numba i sledzenie sciezki splywu tylko w obrebie podzlewni | `scripts/process_dem.py:145-186,257-299,333-342` | −7,2 GB oraz −5,2 GB | sredni-maly |
| F3 | Spadek, ekspozycja i TWI pasami po 512 wierszy z 1-wierszowym marginesem, zapis okienkowy; usuwa tez wyciek `valid_aspect` | `scripts/process_dem.py:755-790,828-839`, `core/morphometry_raster.py:38-52,76-77,102-108,366-380` | TWI −9,9 GB, ekspozycja −9,3 GB | sredni |
| F4 | Jeden `FlwdirRaster` dla calego przebiegu (`order_cells(method='sort')`), Strahler przez `pyflwdir.streams.strahler_order(...)`. Pulapka: `FlwdirRaster.stream_order` cache'uje `strord` i ignoruje maske | `core/hydrology.py:1311`, `scripts/process_dem.py:667-670,741,815,871`, `core/morphometry_raster.py:312-315`; `tests/unit/test_lake_drain.py` (4 miejsca) | −5 do −11 GB na etap | maly-sredni |
| F5 | Wypelnianie dziur z licznikiem uint8 i srednia tylko dla wypelnialnych komorek; akumulacja Kahna w numba zamiast `deque`; `del dem_patched`; maska numba zamiast `np.isin` | `core/hydrology.py:61-113,1049-1090,1139-1157,1287-1331` | dziury 7,15 → 2,2 GB i 88 min → ~1 s; akumulacja 11,5 → 5,9 GB | maly-sredni |
| F6 | Progi od najwiekszego, zwalnianie wynikow poprzedniego progu, sortowanie przed zapisem do bazy | `scripts/process_dem.py:860,885,943,954` | ~2 GB | maly |

**Spodziewany szczyt przy 183M:** F1–F7 ~9,1 GB (wyniki identyczne). Dalsze kroki: F8 (wypelnianie `label_raster` w miejscu zamiast `flw.basins` + kopia), F9 (spadek float32; `mean_slope` rozni sie o 8,6e-8 wzglednie), F10 (`GDAL_CACHEMAX` 64–256 MB) daja ~8,3 GB; F11 (zwalnianie `acc`, `fdir`, `strahler`, `filled_dem`, `slope` w ostatnim progu) ~7,4 GB, czyli 8 GiB bez swapu. Nie warto: poligonizacja okienkowa (≤0,8 GB), przyciecie do obwiedni zlewni (zysk ~0), kafelkowanie (lamie ciaglosc hydrologiczna).

**Kolejnosc wdrozenia:** F7 → F1 + F2 → F3 → F4 + F6 (bez nich Strahler progu 100000 zostaje na ~16,5 GB) → F5 → ewentualnie F8–F11. Potem jeden kontrolny bootstrap Kaczawy w osobnym kontenerze (`docker compose run --rm`), nie w `hydro_api`.

**Testy do napisania:** rownowaznosc stare/nowe dla `fill_internal_nodata_holes` (dziury wielokrokowe, krawedzie, float64), `recompute_flow_accumulation` (kody 0/-1/255, nodata, pary cykli), obliczen pasami (pasy nie dzielace liczby wierszy, `strip_rows=1`, nodata na granicy pasa), Strahlera dla dwoch progow na wspolnym `flw` oraz `sort` vs `walk`, `zonal_summary` i histogramu wobec bincount/scipy (etykieta 0, brakujace etykiety, same nodata), argmax per etykieta i sledzenia w obrebie etykiety (rozszerzyc `tests/unit/test_flow_path.py`). Bez testu jednostkowego na pamiec — weryfikacja jednym przebiegiem na pelnym rastrze.

**Przy okazji (osobne zadanie, wplywa na wyniki):** `fix_internal_sinks` strategia `max_acc` tworzy pary komorek splywajacych do siebie (Kaczawa: 4520 poprawek, wszystkie `max_acc`; to zaglebienia przy nodata, nie prawdziwe wewnetrzne). Kahn nie przetwarza komorek cyklu, wiec akumulacja w tych ujsciach pomija obszar partnera, a `d8_fdir`/`flw` nie dostaje poprawek — odleglosc splywu, Strahler i zlewnie licza sie na niepoprawionej sieci. Ponadto `pyflwdir.streams.stream_distance` (0.5.12) nie jest `@njit` (4 min przy 183M), a ekspozycja i TWI licza sie takze przy `save_intermediates=False`.

**Priorytet:** HIGH przed kolejnym bootstrapem obszaru > ~110M komorek; do tego czasu duze obszary sa poza zasiegiem.

---

*Ostatnia aktualizacja: 2026-10-30*
