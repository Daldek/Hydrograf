# Prompt implementacyjny — Hydrograf

**Wersja:** 2.1
**Data:** 2026-02-08
**Dla:** Claude Code i inni asystenci AI

---

## 1. Kontekst projektu

Pracujesz nad **Hydrograf** — hubem hydrologicznym integrujacym FastAPI + PostGIS z bibliotekami Hydrolog, Kartograf i IMGWTools.

**Funkcjonalnosci:**
- **Wyznaczanie zlewni** — klikniecie na mape → granica zlewni w <10s (traverse_upstream w PostGIS)
- **Parametry fizjograficzne** — powierzchnia, CN, spadki, pokrycie terenu, morfometria
- **Hydrogramy odplywu** — metoda SCS-CN, 42 scenariusze (7 czasow trwania x 6 prawdopodobienstw)
- **Preprocessing NMT** — Kartograf → pyflwdir → COPY → graf flow_network w PostGIS

**Stack technologiczny:**
- Python 3.12+, FastAPI, SQLAlchemy 2.0, GeoAlchemy2
- PostgreSQL 16 + PostGIS 3.4
- Frontend: Vanilla JS, Leaflet.js, Chart.js, Bootstrap 5
- Deployment: Docker Compose (db + api + nginx)
- Linting: ruff (rules: E, F, I, UP, B, SIM) — NIE black+flake8

**Zaleznosci wlasne (GitHub, branch develop):**
- Hydrolog v0.5.2 — obliczenia hydrologiczne (SCS-CN, UH, splot)
- Kartograf v0.4.0 — dane GIS (NMT/NMPT z GUGiK, BDOT10k, SoilGrids, HSG, Ortofotomapa)
- IMGWTools v2.1.0 — dane opadowe IMGW (kwantyle, stacje)

---

## 2. Dokumentacja — przeczytaj PRZED praca

1. **CLAUDE.md** (korzen projektu) — kontekst sesji, komendy, workflow
2. **docs/PROGRESS.md** — aktualny stan, co zrobiono, nastepne kroki
3. **docs/SCOPE.md** — zakres (co JEST i czego NIE MA w MVP)
4. **docs/PRD.md** — wymagania produktowe
5. **docs/ARCHITECTURE.md** — architektura systemu i ADR
6. **docs/DEVELOPMENT_STANDARDS.md** — standardy kodowania
7. **docs/DATA_MODEL.md** — schemat bazy danych PostGIS
8. **docs/CHANGELOG.md** — historia zmian

Dodatkowe (w razie potrzeby):
- **docs/KARTOGRAF_INTEGRATION.md** — integracja NMT i Land Cover
- **docs/HYDROLOG_INTEGRATION.md** — integracja obliczen hydrologicznych
- **docs/DECISIONS.md** — rejestr decyzji architektonicznych (ADR)

**WAZNE:** Przed napisaniem JAKIEGOKOLWIEK kodu, przeczytaj CLAUDE.md i PROGRESS.md.

---

## 3. Architektura modulow

```
backend/
├── api/                     # Warstwa API (FastAPI)
│   ├── main.py              # App instance, CORS, middleware
│   └── endpoints/           # Endpointy REST
│       ├── watershed.py     # POST /api/delineate-watershed
│       ├── hydrograph.py    # POST /api/generate-hydrograph
│       └── health.py        # GET /health
│
├── core/                    # Logika biznesowa
│   ├── config.py            # Settings (Pydantic BaseSettings, env vars)
│   ├── database.py          # Connection pool (SQLAlchemy 2.0 + PostGIS)
│   ├── watershed.py         # traverse_upstream, build_boundary, find_nearest_stream
│   ├── morphometry.py       # Parametry fizjograficzne (area, slope, length, shape)
│   ├── precipitation.py     # Zapytania opadowe (IDW interpolation)
│   ├── land_cover.py        # Analiza pokrycia terenu, determine_cn()
│   ├── cn_tables.py         # Tablice CN dla HSG x pokrycie terenu
│   └── cn_calculator.py     # Integracja z Kartografem dla HSG-based CN
│
├── models/schemas.py        # Modele Pydantic (request/response)
│
├── utils/                   # Narzedzia pomocnicze
│   ├── geometry.py          # CRS, transformacje (WGS84 ↔ PL-1992)
│   ├── raster_utils.py      # Resample, polygonize
│   └── sheet_finder.py      # Konwersja wspolrzednych → godla arkuszy NMT
│
├── scripts/                 # Skrypty CLI (preprocessing)
│   ├── prepare_area.py      # Pipeline: download + process (glowny entry point)
│   ├── process_dem.py       # pyflwdir → flow_network (COPY do PostGIS)
│   ├── download_dem.py      # Pobieranie NMT przez Kartograf
│   ├── download_landcover.py # Pobieranie BDOT10k/CORINE
│   └── import_landcover.py  # Import pokrycia do PostGIS
│
├── migrations/              # Alembic (PostgreSQL + PostGIS)
├── tests/                   # pytest (unit/ + integration/)
└── pyproject.toml           # Konfiguracja (ruff, pytest, mypy)

frontend/
├── css/                     # Bootstrap 5 + custom
└── js/                      # Leaflet.js, Chart.js, API client (Vanilla JS)
```

### Przeplywy danych

```
User → Leaflet.js → POST /api/delineate-watershed → watershed.py → PostGIS CTE → GeoJSON
User → Leaflet.js → POST /api/generate-hydrograph → Hydrolog (SCS-CN, splot) → Chart.js
Preprocessing: Kartograf → NMT (.asc) → pyflwdir → COPY → PostGIS flow_network
Preprocessing: Kartograf → BDOT10k (.gpkg) → import_landcover → PostGIS land_cover
```

---

## 4. Zrodla danych i API

| Zrodlo | Typ danych | Uzycie w Hydrograf | Via |
|--------|-----------|---------------------|-----|
| GUGiK | NMT (ASC/GeoTIFF) | Graf flow_network | Kartograf |
| GUGiK | BDOT10k (GeoPackage) | Land cover, CN | Kartograf |
| Copernicus | CORINE (GeoTIFF) | Land cover (fallback) | Kartograf |
| ISRIC | SoilGrids + HSG | CN grupy hydrologiczne | Kartograf |
| IMGW | Opady Pmax_PT | precipitation_data | IMGWTools |

### Tabele PostGIS

| Tabela | Geometria | SRID | Opis |
|--------|-----------|------|------|
| flow_network | Point | 2180 | Graf splywu (elevation, slope, downstream_id, is_stream) |
| land_cover | MultiPolygon | 2180 | Pokrycie terenu (category, cn_value) |
| precipitation_data | Point | 2180 | Opady (duration, probability, precipitation_mm) |
| stream_network | LineString | 2180 | Siec rzeczna (name, strahler_order) |

---

## 5. Endpointy API

### POST /api/delineate-watershed
```json
// Request
{ "latitude": 52.123456, "longitude": 21.123456 }

// Response 200
{
  "watershed": {
    "boundary_geojson": { "type": "Feature", "geometry": {...} },
    "area_km2": 45.3,
    "hydrograph_available": true,
    "outlet": { "latitude": 52.123, "longitude": 21.123, "elevation_m": 150.0 },
    "cell_count": 234567
  }
}
// 404: "Nie znaleziono cieku w tym miejscu"
```

### POST /api/generate-hydrograph
```json
// Request
{ "latitude": 52.123456, "longitude": 21.123456, "duration": "1h", "probability": 10 }

// Response 200 — pelna struktura w DATA_MODEL.md sekcja 6.4
```

### GET /health
```json
{ "status": "healthy", "database": "connected", "version": "2.0.0" }
```

---

## 6. Workflow implementacji

### 6.1 Przed rozpoczeciem

```
1. Przeczytaj CLAUDE.md i PROGRESS.md
2. Sprawdz galaz: git branch --show-current (powinno byc: develop)
3. Sprawdz status: git status
4. Zrozum zadanie — znajdz relevantne sekcje w SCOPE.md / PRD.md
5. Zadaj pytania jesli cos niejasne
```

### 6.2 Implementacja

```
1. Pisz kod zgodnie z DEVELOPMENT_STANDARDS.md
2. Type hints (Python 3.12+ style: X | None zamiast Optional[X])
3. Docstrings NumPy style, po angielsku
4. Walidacja inputu na granicy systemu (Pydantic models)
5. Parametryzowane SQL (SQLAlchemy text() z :param, NIGDY f-stringi)
6. raise ... from err (zachowaj lancuch wyjatkow)
7. Konwencja jednostek w nazwach: area_km2, elevation_m, discharge_m3s, time_min
```

### 6.3 Testowanie

```
1. Napisz testy (pytest, AAA pattern)
2. Uzyj fixtures i mocking (nie wywoluj prawdziwych API ani bazy prod)
3. Pokrycie: 80% core / 60% utility
4. Uruchom: cd backend && .venv/bin/python -m pytest tests/ -v --tb=short
5. Sprawdz linting: cd backend && .venv/bin/python -m ruff check .
6. Sprawdz formatowanie: cd backend && .venv/bin/python -m ruff format --check .
```

### 6.4 Commit

```
1. Conventional Commits z scope: feat(api): add CN endpoint
2. Scopes: api, core, db, frontend, tests, docs, docker
3. Commituj czesto, male zmiany
4. Zaktualizuj CHANGELOG.md (sekcja [Unreleased])
5. Zaktualizuj PROGRESS.md na koniec sesji
```

---

## 7. Czego NIE robic

- **Nie dodawaj funkcji poza zakresem** — sprawdz SCOPE.md sekcja "Out of Scope"
- **Nie zmieniaj architektury** bez konsultacji — struktura jest przemyslana (ADR w DECISIONS.md)
- **Nie pomijaj testow** — minimum 80% pokrycia core
- **Nie hardcoduj secrets** — uzyj zmiennych srodowiskowych (.env)
- **Nie uzywaj Optional/Union** — uzyj `X | None` i `X | Y` (Python 3.12+)
- **Nie uzywaj f-stringow w loggerze** — uzyj `logger.info("Area: %s km2", area_km2)`
- **Nie uzywaj black/flake8** — projekt uzywa **ruff** (check + format)
- **Nie uzywaj raw SQL concat** — zawsze `text("... :param ...")` z parametrami
- **Nie wywoluj prawdziwych API w testach** — mockuj requesty i baze
- **Nie twrz osobnych plikow konfiguracyjnych** — konfiguracja w pyproject.toml i .env

---

## 8. Typowe zadania

### 8.1 Nowy endpoint API

```python
# 1. Dodaj Pydantic models w models/schemas.py
# 2. Stworz endpoint w api/endpoints/nowy.py (APIRouter)
# 3. Zarejestruj router w api/main.py (app.include_router)
# 4. Logika biznesowa w core/nowy.py (NIE w endpoincie)
# 5. Napisz testy: tests/unit/test_nowy.py + tests/integration/test_api_nowy.py
# 6. Zaktualizuj CHANGELOG.md
```

### 8.2 Nowy modul core

```python
# 1. Stworz backend/core/nowy_modul.py
# 2. Dodaj type hints, docstrings NumPy style
# 3. Waliduj inputy na poczatku funkcji (ValueError dla zlych danych)
# 4. SQL przez SQLAlchemy text() z parametrami
# 5. Napisz testy w tests/unit/test_nowy_modul.py
# 6. Import w odpowiednim endpoincie
```

### 8.3 Naprawa bledu

```python
# 1. Zidentyfikuj warstwe (api/ core/ utils/ scripts/)
# 2. Napisz test reprodukujacy blad (test MUSI failowac przed fixem)
# 3. Napraw blad
# 4. Potwierdz testem (test MUSI przechodzic po fixie)
# 5. Sprawdz czy nie zepsules istniejacych testow
# 6. Commit: fix(scope): opis bledu
```

### 8.4 Nowy skrypt preprocessing

```python
# 1. Stworz backend/scripts/nowy_skrypt.py
# 2. Uzyj argparse dla parametrow CLI
# 3. Logowanie przez logging (nie print)
# 4. Obsluz bledy (try/except z komunikatami)
# 5. Uzyj Kartograf/IMGWTools jako zrodla danych
# 6. Import do PostGIS przez COPY (nie INSERT) — patrz ADR-006
```

---

## 9. Ograniczenia techniczne

- **PostGIS wymagany** — cala logika runtime oparta na SQL spatial queries + recursive CTE
- **SCS-CN limit** — metoda ograniczona do zlewni <= 250 km² (flaga hydrograph_available)
- **Preprocessing jednorazowy** — ~3.8 min per arkusz NMT (po optymalizacji COPY, ADR-006)
- **Synchroniczny preprocessing** — brak async (pipeline sekwencyjny)
- **Frontend statyczny** — Vanilla JS, brak bundlera/frameworka
- **API timeout** — 30s (nginx proxy_read_timeout)
- **Runtime targets** — wyznaczanie zlewni <10s, hydrogram <5s (p95)
- **Brak cache** — kazde zapytanie od nowa (zaplanowane na przyszlosc)
- **Brak autentykacji** — MVP dziala w sieci wewnetrznej (LAN)
- **10 rownoleglych uzytkownikow** — connection pool: 10 + 5 overflow

---

## 10. Integracje z innymi projektami

### Kartograf (dane GIS)
```python
from kartograf import GugikProvider, DownloadManager, SheetParser, BBox
from kartograf import LandCoverManager, Bdot10kProvider
from kartograf import HSGCalculator, SoilGridsProvider

# Pobieranie NMT
manager = DownloadManager(output_dir="./data/nmt")
manager.download_hierarchy("N-34-130-D", target_scale="1:10000")

# Pobieranie BDOT10k
lc = LandCoverManager(output_dir="./data/landcover")
lc.download(teryt="1465")

# HSG (integracja z cn_calculator.py)
hsg = HSGCalculator()
hsg_path = hsg.calculate_hsg_by_godlo("N-34-130-D")
```

### Hydrolog (obliczenia hydrologiczne)
```python
from hydrolog import HietogramBeta, SCSMethod, UnitHydrograph

# Hietogram → opad efektywny → hydrogram
hietogram = HietogramBeta(precipitation_mm=38.5, duration_min=60)
scs = SCSMethod(cn=72.4)
pe = scs.effective_rainfall(hietogram.intensities)
uh = UnitHydrograph.scs(area_km2=45.3, tc_min=68.5)
discharge = uh.convolve(pe)
```

### IMGWTools (dane opadowe)
```python
from imgwtools import PrecipitationData

# Pobieranie kwantyli opadowych
precip = PrecipitationData()
value = precip.get_pmax(lat=52.23, lon=21.01, duration="1h", probability=10)
```

---

## 11. Checklist przed zakonczeniem sesji

```markdown
- [ ] Kod sformatowany (`cd backend && .venv/bin/python -m ruff format .`)
- [ ] Linting OK (`cd backend && .venv/bin/python -m ruff check .`)
- [ ] Testy przechodza (`cd backend && .venv/bin/python -m pytest tests/ -v`)
- [ ] CHANGELOG.md zaktualizowany (sekcja [Unreleased])
- [ ] PROGRESS.md zaktualizowany (sekcja "Ostatnia sesja")
- [ ] Commity zgodne z Conventional Commits (feat/fix/docs + scope)
- [ ] Brak hardcoded secrets (sprawdz .env, credentials)
- [ ] Migracje Alembic (jesli zmieniles schemat bazy)
```

---

**Wersja dokumentu:** 2.0
**Data ostatniej aktualizacji:** 2026-02-07
**Status:** Aktywny dla wszystkich asystentow AI pracujacych nad projektem
