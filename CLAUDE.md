# Instrukcje dla Claude Code

## Opis projektu

Hydrograf — hub hydrologiczny integrujacy FastAPI + PostGIS z bibliotekami Hydrolog, Kartograf i IMGWTools. System wyznacza granice zlewni z NMT (klikniecie na mape → granica w <10s), oblicza parametry fizjograficzne (powierzchnia, CN, spadki, pokrycie terenu) i generuje hydrogramy odplywu metoda SCS-CN (42 scenariusze: 7 czasow trwania × 6 prawdopodobienstw).

Architektura: preprocessing NMT → graf w PostGIS → szybkie zapytania SQL runtime.
Frontend: Leaflet.js (mapa) + Chart.js (wykresy) + Bootstrap (UI).
Development: .venv + PostGIS w Docker. Deployment: Docker Compose (db + api + nginx).

## Srodowisko Python

Uzywaj srodowiska wirtualnego z `backend/.venv`:
- Python: `backend/.venv/bin/python`
- Pip: `backend/.venv/bin/pip`
- Wymagany Python: 3.12+

Setup .venv:
```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e ".[dev]"
```

Baza danych (jedyny wymagany serwis Docker do developmentu):
```bash
docker compose up -d db
```

Serwer dev:
```bash
cd backend && .venv/bin/python -m uvicorn api.main:app --reload
```

Zmienne srodowiskowe (plik `.env` w korzeniu):
- `POSTGRES_*` — polaczenie z PostgreSQL+PostGIS (uzywane przez .venv i docker compose)
- `CORS_ORIGINS` — dozwolone originy (domyslnie `http://localhost`)
- `LOG_LEVEL` — poziom logowania (domyslnie `INFO`)

## Dokumentacja

**Przeczytaj w kolejnosci:**
1. `docs/PROGRESS.md` — aktualny stan projektu i zadania
2. `docs/SCOPE.md` — zakres projektu (co IN/OUT)
3. `docs/PRD.md` — wymagania produktowe
4. `docs/ARCHITECTURE.md` — architektura systemu
5. `docs/DECISIONS.md` — rejestr decyzji architektonicznych (ADR)
6. `docs/CHANGELOG.md` — historia zmian per-release

Dodatkowa dokumentacja:
- `docs/DATA_MODEL.md` — schemat bazy danych PostGIS
- `docs/KARTOGRAF_INTEGRATION.md` — integracja z Kartografem (NMT, Land Cover)
- `docs/HYDROLOG_INTEGRATION.md` — integracja z Hydrologiem (obliczenia)
- `docs/CROSS_PROJECT_ANALYSIS.md` — analiza zaleznosci miedzy projektami

## Struktura modulow

```
backend/
├── api/                     # Warstwa API (FastAPI)
│   ├── main.py              # FastAPI app instance, CORS, middleware
│   └── endpoints/           # Endpointy REST API
│       ├── watershed.py     # POST /api/delineate-watershed
│       ├── hydrograph.py    # POST /api/generate-hydrograph
│       ├── profile.py       # POST /api/terrain-profile
│       ├── depressions.py   # GET /api/depressions
│       ├── tiles.py         # GET /api/tiles/{streams|catchments}/{z}/{x}/{y}.pbf
│       ├── select_stream.py # POST /api/select-stream
│       └── health.py        # GET /health
│
├── core/                    # Logika biznesowa
│   ├── config.py            # Settings (Pydantic, zmienne srodowiskowe)
│   ├── database.py          # Connection pool (SQLAlchemy + PostGIS)
│   ├── watershed.py         # Wyznaczanie zlewni (traverse_upstream, build_boundary)
│   ├── morphometry.py       # Parametry fizjograficzne (area, slope, length)
│   ├── precipitation.py     # Zapytania opadowe (IDW interpolation)
│   ├── land_cover.py        # Analiza pokrycia terenu, determine_cn()
│   ├── cn_tables.py         # Tablice CN dla HSG × pokrycie terenu
│   ├── cn_calculator.py     # Integracja z Kartografem dla HSG-based CN
│   ├── raster_io.py         # Odczyt/zapis rastrow (ASC, VRT, GeoTIFF)
│   ├── hydrology.py         # Hydrologia: fill, fdir, acc, stream burning
│   ├── morphometry_raster.py # Nachylenie, aspekt, TWI, Strahler
│   ├── stream_extraction.py # Wektoryzacja ciekow, zlewnie czastkowe
│   ├── db_bulk.py           # Bulk INSERT via COPY, timeout management
│   ├── zonal_stats.py       # Statystyki strefowe (bincount, max)
│   └── flow_graph.py        # Graf przeplywu in-memory (scipy sparse CSR)
│
├── models/
│   └── schemas.py           # Modele Pydantic (request/response)
│
├── utils/
│   ├── geometry.py          # Operacje geometryczne (CRS, transformacje)
│   ├── raster_utils.py      # Narzedzia rastrowe (resample, polygonize)
│   ├── dem_color.py         # Wspolny modul kolorow DEM (colormap, hillshade)
│   └── sheet_finder.py      # Wyszukiwanie arkuszy NMT
│
├── scripts/                 # Skrypty CLI (preprocessing)
│   ├── process_dem.py       # Import NMT do bazy (orchestrator → core/)
│   ├── generate_depressions.py # Generowanie zaglebie (blue spots)
│   ├── generate_tiles.py    # Pre-generacja kafelkow MVT (tippecanoe)
│   ├── generate_dem_tiles.py # Piramida kafelkow DEM (XYZ)
│   ├── export_pipeline_gpkg.py # Export GeoPackage + raport
│   ├── analyze_watershed.py # Pelna analiza zlewni (CLI)
│   ├── prepare_area.py      # Pobieranie + przetwarzanie obszaru
│   ├── download_dem.py      # Pobieranie NMT przez Kartograf
│   ├── download_landcover.py # Pobieranie pokrycia terenu
│   └── import_landcover.py  # Import pokrycia do bazy
│
├── migrations/              # Migracje Alembic (PostgreSQL + PostGIS)
├── tests/                   # Testy (pytest)
│   ├── unit/
│   └── integration/
└── pyproject.toml           # Konfiguracja projektu (ruff, pytest, mypy)

frontend/
├── css/                     # Style (Bootstrap + custom)
└── js/                      # Logika (Leaflet.js, Chart.js, API client)
```

## Komendy

```bash
# Serwer dev
cd backend && .venv/bin/python -m uvicorn api.main:app --reload

# Testy
cd backend && .venv/bin/python -m pytest tests/ -v
cd backend && .venv/bin/python -m pytest tests/ --cov=. --cov-report=html

# Linter i formatowanie (ruff)
cd backend && .venv/bin/python -m ruff check .
cd backend && .venv/bin/python -m ruff check . --fix
cd backend && .venv/bin/python -m ruff format .
cd backend && .venv/bin/python -m ruff format --check .

# Type checking
cd backend && .venv/bin/python -m mypy .

# Migracje
cd backend && alembic upgrade head
cd backend && alembic revision --autogenerate -m "opis"

# Skrypty CLI
cd backend && .venv/bin/python -m scripts.process_dem --input ../data/nmt/plik.asc
cd backend && .venv/bin/python -m scripts.analyze_watershed --lat 52.23 --lon 21.01
cd backend && .venv/bin/python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5

# Docker — baza danych (development)
docker compose up -d db                       # Uruchomienie PostGIS
docker compose down                           # Zatrzymanie

# Docker — pelny stack (testowanie / produkcja)
docker compose up -d                          # Uruchomienie calego stacku
docker compose logs -f api                    # Logi API
docker compose exec api bash                  # Shell w kontenerze
```

## Workflow sesji

### Poczatek sesji
1. Przeczytaj `docs/PROGRESS.md` — sekcja "Ostatnia sesja"
2. `git status` + `git log --oneline -5`
3. Sprawdz na ktorej jestes galezi (`git branch --show-current`) — pracuj na `develop`

### W trakcie sesji
- Commituj czesto (male zmiany)
- Aktualizuj `docs/CHANGELOG.md` na biezaco
- W razie watpliwosci — pytaj

### Koniec sesji
**OBOWIAZKOWO zaktualizuj** `docs/PROGRESS.md`:
- Co zostalo zrobione
- Co jest w trakcie (plik, linia, kontekst)
- Nastepne kroki

### Git Workflow

**Galecie:**
- **main** — stabilna wersja (tylko merge z develop po checkpoincie)
- **develop** — aktywny rozwoj (ZAWSZE pracuj na tej galezi)

**Commity:** Conventional Commits z scope:
- `feat(api): ...` — nowa funkcjonalnosc
- `fix(core): ...` — naprawa bledu
- `docs(readme): ...` — dokumentacja
- `refactor(db): ...` — refactoring
- `test(unit): ...` — testy

Scope: `api`, `core`, `db`, `frontend`, `tests`, `docs`, `docker`

## Specyfika projektu

### Zaleznosci zewnetrzne (biblioteki wlasne)
- **Hydrolog** v0.5.2 — obliczenia hydrologiczne (SCS-CN, hydrogramy, morfometria)
- **Kartograf** v0.4.1 — pobieranie danych GIS (NMT z GUGiK, Land Cover, SoilGrids, BDOT10k hydro)
- **IMGWTools** v2.1.0 — dane obserwacyjne IMGW (opady projektowe)

Wszystkie trzy dostepne z GitHub (branch develop), nie z PyPI.

### Integracje
- Hydrograf jest **hubem** — integruje Hydrolog, Kartograf, IMGWTools
- Hydrolog wykonuje obliczenia (splot, UH, opad efektywny)
- Kartograf pobiera dane przestrzenne (NMT, pokrycie terenu, gleby i inne)
- IMGWTools dostarcza dane opadowe (kwantyle, stacje)

### Ograniczenia
- PostGIS jest **wymagany** — cala logika oparta na SQL spatial queries
- Metoda SCS-CN ograniczona do zlewni <= 250 km²
- Preprocessing NMT: jednorazowy, ~3.8 min per arkusz (po optymalizacji COPY)
- Frontend: statyczny HTML/JS, brak frameworka (Vanilla JS)

### Konwencje nazewnictwa z jednostkami
```python
area_km2 = 45.3
elevation_m = 150.0
discharge_m3s = 12.5
time_concentration_min = 68.5
slope_percent = 3.2
precipitation_mm = 25.0
length_km = 12.3
```
