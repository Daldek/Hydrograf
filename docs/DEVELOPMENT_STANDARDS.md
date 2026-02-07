# Standardy deweloperskie — Hydrograf

**Wersja:** 2.0
**Data:** 2026-02-07
**Status:** Obowiazujacy
**Zrodlo:** Zunifikowane standardy workspace (`shared/standards/DEVELOPMENT_STANDARDS.md` v1.0)

---

## Spis tresci

1. [Wprowadzenie](#1-wprowadzenie)
2. [Nazewnictwo (Python + JavaScript + SQL)](#2-nazewnictwo-python--javascript--sql)
3. [Formatowanie kodu (Ruff)](#3-formatowanie-kodu-ruff)
4. [Dokumentacja w kodzie (NumPy docstrings)](#4-dokumentacja-w-kodzie-numpy-docstrings)
5. [Python — importy](#5-python--importy)
6. [Python — type hints (3.12+)](#6-python--type-hints-312)
7. [Python — testy (pytest, AAA, fixtures, asyncio)](#7-python--testy-pytest-aaa-fixtures-asyncio)
8. [Python — pokrycie kodu](#8-python--pokrycie-kodu)
9. [JavaScript — konwencje frontend](#9-javascript--konwencje-frontend)
10. [SQL/PostGIS — konwencje](#10-sqlpostgis--konwencje)
11. [Git workflow (Conventional Commits)](#11-git-workflow-conventional-commits)
12. [Docker — konwencje](#12-docker--konwencje)
13. [Python — obsluga bledow](#13-python--obsluga-bledow)
14. [Python — logging](#14-python--logging)
15. [Python — wydajnosc](#15-python--wydajnosc)
16. [Bezpieczenstwo](#16-bezpieczenstwo)
17. [Pre-merge checklist](#17-pre-merge-checklist)

---

## 1. Wprowadzenie

Standardy deweloperskie dla **Hydrograf** — huba hydrologicznego integrujacego
FastAPI + PostGIS z bibliotekami Hydrolog, Kartograf i IMGWTools.

**Architektura:** Backend (FastAPI async + SQLAlchemy + PostGIS), Frontend
(Leaflet.js + Chart.js + Bootstrap), Deployment (Docker Compose: db + api + nginx).

**Integracje:** Hydrolog (obliczenia SCS-CN), Kartograf (NMT, Land Cover),
IMGWTools (opady projektowe).

Odstepstwa od tych standardow wymagaja uzasadnienia w `CLAUDE.md` projektu.

---

## 2. Nazewnictwo (Python + JavaScript + SQL)

### 2.1 Python

| Element | Konwencja | Przyklad |
|---------|-----------|----------|
| Zmienne | snake_case + jednostka | `area_km2`, `elevation_m` |
| Funkcje | snake_case + czasownik | `delineate_watershed()`, `calculate_cn()` |
| Klasy | PascalCase | `WatershedDelineator`, `HydrographGenerator` |
| Stale | UPPER_SNAKE_CASE | `DEFAULT_TIME_STEP_MIN`, `MAX_AREA_KM2` |
| Pliki .py | snake_case | `watershed.py`, `land_cover.py` |
| Protected | `_prefix` | `self._cells` |
| Private | `__prefix` | `self.__internal_cache` |

### 2.2 Jednostki w nazwach zmiennych

**ZAWSZE** dodawaj jednostke do nazwy zmiennej fizycznej:

| Wielkosc | Symbol | Przyklad zmiennej |
|----------|--------|-------------------|
| Powierzchnia | km2, m2 | `area_km2`, `cell_area_m2` |
| Dlugosc | km, m | `length_km`, `elevation_m` |
| Opad | mm | `precipitation_mm` |
| Intensywnosc | mm_per_min | `intensity_mm_per_min` |
| Przeplyw | m3s | `discharge_m3s` |
| Czas | min, s | `time_concentration_min`, `duration_min` |
| Spadek | percent | `slope_percent` |

```python
# GOOD
area_km2 = 45.3
elevation_m = 150.0
discharge_m3s = 12.5
time_concentration_min = 68.5
slope_percent = 3.2
precipitation_mm = 25.0
length_km = 12.3

# BAD — unit ambiguity
area = 45.3          # km2 or m2?
discharge = 12.5     # m3/s or l/s?
```

### 2.3 Prefiksy semantyczne

| Prefiks | Znaczenie | Przyklad w Hydrograf |
|---------|-----------|----------------------|
| `delineate_*` | Wyznaczanie granicy | `delineate_watershed()` |
| `calculate_*` | Obliczenie wyniku | `calculate_cn()`, `calculate_morphometry()` |
| `generate_*` | Generowanie danych | `generate_hydrograph()` |
| `fetch_*` | Pobranie danych z API | `fetch_precipitation()` |
| `traverse_*` | Przejscie grafu | `traverse_upstream()` |
| `query_*` | Zapytanie SQL | `query_upstream_cells()` |
| `import_*` | Import danych do bazy | `import_dem()`, `import_landcover()` |

### 2.4 JavaScript

```javascript
// Variables and functions: camelCase
const watershedArea = 45.3;
function calculateBounds(coordinates) { ... }
async function fetchHydrograph(lat, lon) { ... }

// Classes: PascalCase
class MapController { ... }

// Constants: UPPER_SNAKE_CASE
const API_URL = 'http://localhost:8000/api';
const MAX_ZOOM = 18;

// Event handlers: prefix "on" or "handle"
function onMapClick(event) { ... }
function handleWatershedLoaded(data) { ... }
```

### 2.5 SQL

```sql
-- Tables: snake_case, descriptive
CREATE TABLE flow_network ( ... );
CREATE TABLE precipitation_data ( ... );

-- Indexes: idx_<table>_<column(s)>
CREATE INDEX idx_flow_geom ON flow_network USING GIST(geom);
CREATE INDEX idx_flow_downstream ON flow_network(downstream_id);

-- Constraints: descriptive names
CONSTRAINT valid_elevation CHECK (elevation >= -50 AND elevation <= 3000);
CONSTRAINT valid_cn CHECK (cn BETWEEN 0 AND 100);
```

---

## 3. Formatowanie kodu (Ruff)

### 3.1 Konfiguracja

Hydrograf uzywa **Ruff** jako jedynego narzedzia do formatowania i lintingu Python.
Nie uzywamy black, flake8, isort ani innych narzedzi.

```toml
# pyproject.toml
[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ruff.format]
quote-style = "double"
```

**Reguly:** `E` pycodestyle, `F` pyflakes, `I` isort, `UP` pyupgrade,
`B` bugbear, `SIM` simplify.

### 3.2 Komendy

```bash
ruff format backend/ tests/                  # Formatowanie
ruff format --check backend/ tests/          # Sprawdzenie (bez zmian)
ruff check backend/ tests/                   # Linting
ruff check --fix backend/ tests/             # Linting z auto-fix
```

### 3.3 Zasady

```python
# Line length: 88 characters, Indentation: 4 spaces (NEVER tabs)

# GOOD — multi-line when exceeds 88 chars
def delineate_watershed(
    latitude: float,
    longitude: float,
    threshold: int = 100,
    max_area_km2: float = 250.0,
) -> WatershedResult:
    pass
```

### 3.4 JavaScript — formatowanie

- Dlugosc linii: **100 znakow**, wciecia: **2 spacje**
- **Zawsze** sredniki, single quotes, template literals dla interpolacji
- Arrow functions dla callbacks

### 3.5 SQL — formatowanie

```sql
-- Keywords: UPPERCASE, Identifiers: lowercase
SELECT
    fn.id,
    fn.elevation,
    ST_AsGeoJSON(fn.geom) AS geojson
FROM flow_network fn
WHERE fn.is_stream = TRUE
ORDER BY fn.elevation DESC
LIMIT 100;
```

---

## 4. Dokumentacja w kodzie (NumPy docstrings)

### 4.1 Jezyk

- **Docstrings i komentarze w kodzie** — po angielsku
- **Dokumentacja projektowa (.md)** — po polsku
- **Commit messages** — po angielsku

### 4.2 Funkcje

```python
def delineate_watershed(
    latitude: float,
    longitude: float,
    threshold: int = 100,
) -> WatershedResult:
    """
    Delineate watershed boundary from a pour point.

    Traverses the flow network graph upstream from the nearest stream
    cell to the given coordinates.

    Parameters
    ----------
    latitude : float
        Pour point latitude in WGS84 (EPSG:4326).
    longitude : float
        Pour point longitude in WGS84 (EPSG:4326).
    threshold : int, optional
        Flow accumulation threshold, by default 100.

    Returns
    -------
    WatershedResult
        Watershed boundary as GeoJSON with morphometric parameters.

    Raises
    ------
    ValidationError
        If coordinates are outside Poland extent.
    DatabaseError
        If flow network data is not available for the area.
    """
    pass
```

### 4.3 Klasy

```python
class HydrographGenerator:
    """
    Generate runoff hydrograph using SCS-CN method.

    Produces 42 scenarios (7 durations x 6 probabilities) for a given
    watershed. Integrates with Hydrolog and IMGWTools.

    Parameters
    ----------
    area_km2 : float
        Watershed area [km2].
    cn : int
        Curve Number (0-100).
    tc_min : float
        Time of concentration [min].
    """

    def __init__(self, area_km2: float, cn: int, tc_min: float) -> None:
        pass
```

### 4.4 Komentarze inline

```python
# GOOD — explains "why", not "what"
# SCS-CN method is limited to watersheds <= 250 km2
if area_km2 > MAX_AREA_KM2:
    return WatershedResult(hydrograph_available=False)

# Recursive CTE is faster than Python graph traversal for PostGIS
query = text(UPSTREAM_RECURSIVE_CTE)
```

### 4.5 JSDoc (JavaScript)

```javascript
/**
 * Display watershed boundary on the map.
 *
 * @param {Object} boundaryGeoJSON - Boundary as GeoJSON Feature.
 * @param {L.Map} map - Leaflet map instance.
 * @returns {L.GeoJSON} Layer with watershed boundary.
 */
function displayWatershed(boundaryGeoJSON, map) { ... }
```

---

## 5. Python — importy

### 5.1 Kolejnosc

```python
# Order: stdlib -> third-party -> local
# Ruff sorts automatically (rule I)

import logging
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from core.config import settings
from core.watershed import delineate_watershed
from models.schemas import DelineateRequest, WatershedResponse
```

### 5.2 Zasady

```python
# GOOD — import specific names
from core.watershed import delineate_watershed, build_boundary

# GOOD — import module when using many names
from core import morphometry

# BAD — wildcard imports
from core.watershed import *
```

### 5.3 Publiczne API przez `__init__.py`

```python
# core/__init__.py
from core.watershed import delineate_watershed
from core.morphometry import calculate_morphometry

__all__ = ["delineate_watershed", "calculate_morphometry"]
```

---

## 6. Python — type hints (3.12+)

### 6.1 Modern syntax

```python
# GOOD — modern syntax (PEP 604, PEP 585)
def get_watershed(watershed_id: int | None = None) -> WatershedResult | None:
    pass

def traverse_upstream(start_cell_id: int, cells: list[int]) -> set[int]:
    pass

# BAD — legacy typing
from typing import List, Optional, Union
```

### 6.2 NumPy typing

```python
from numpy.typing import NDArray
import numpy as np

def effective_precipitation(
    intensities: NDArray[np.float64], cn: int,
) -> NDArray[np.float64]:
    pass
```

### 6.3 Pydantic models (API boundary)

```python
from pydantic import BaseModel, Field

class DelineateRequest(BaseModel):
    latitude: float = Field(..., ge=49.0, le=55.0)
    longitude: float = Field(..., ge=14.0, le=25.0)
    threshold: int = Field(default=100, ge=10, le=1000)
```

### 6.4 Wymagane wszedzie

Type hints sa wymagane dla wszystkich argumentow funkcji publicznych,
wartosci zwracanych i atrybutow klas.

```bash
mypy backend/ --strict
```

---

## 7. Python — testy (pytest, AAA, fixtures, asyncio)

### 7.1 Konfiguracja

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
asyncio_mode = "auto"
```

### 7.2 Struktura katalogow

```
backend/tests/
├── conftest.py              # Shared fixtures (db session, test client)
├── unit/
│   ├── test_watershed.py
│   ├── test_morphometry.py
│   ├── test_cn_calculator.py
│   └── test_schemas.py
├── integration/
│   ├── test_api_watershed.py
│   └── test_database.py
└── fixtures/
    ├── sample_watershed.json
    └── sample_flow_network.sql
```

### 7.3 Nazewnictwo testow

```python
# Pattern: test_<function>_<scenario>[_<expected>]
def test_delineate_watershed_typical_point(): ...
def test_delineate_watershed_large_area_returns_no_hydrograph(): ...
def test_calculate_cn_full_forest_returns_low_cn(): ...
def test_traverse_upstream_circular_reference_raises(): ...
```

### 7.4 AAA Pattern (Arrange-Act-Assert)

```python
def test_calculate_morphometry_typical_watershed():
    # Arrange
    cells = [
        {"id": 1, "elevation": 250.0, "area_m2": 100.0},
        {"id": 2, "elevation": 200.0, "area_m2": 100.0},
    ]

    # Act
    result = calculate_morphometry(cells)

    # Assert
    assert result.area_km2 > 0
    assert result.elevation_min_m < result.elevation_max_m
```

### 7.5 Fixtures

```python
@pytest.fixture
def sample_pour_point():
    """Fixture with sample pour point coordinates."""
    return {"latitude": 52.23, "longitude": 21.01}

@pytest.fixture
async def async_client():
    """Async HTTP client for API tests."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
async def db_session():
    """Database session for integration tests."""
    async with get_session() as session:
        yield session
        await session.rollback()
```

### 7.6 Async tests

```python
# asyncio_mode = "auto" — no need for @pytest.mark.asyncio

async def test_delineate_watershed_api(async_client, sample_pour_point):
    response = await async_client.post(
        "/api/delineate-watershed", json=sample_pour_point,
    )
    assert response.status_code == 200
    assert "area_km2" in response.json()

async def test_delineate_invalid_coords(async_client):
    response = await async_client.post(
        "/api/delineate-watershed",
        json={"latitude": 10.0, "longitude": 10.0},
    )
    assert response.status_code == 422
```

### 7.7 Mocking zewnetrznych zaleznosci

```python
async def test_generate_hydrograph_with_mocked_hydrolog():
    with patch("core.hydrograph.hydrolog.generate") as mock_gen:
        mock_gen.return_value = Mock(
            time_min=np.array([0, 5, 10, 15]),
            discharge_m3s=np.array([0.0, 5.2, 12.5, 3.1]),
        )
        result = await generate_hydrograph(area_km2=45.3, cn=72, tc_min=68.5)
        assert result.peak_discharge_m3s == 12.5
```

---

## 8. Python — pokrycie kodu

### 8.1 Progi pokrycia

| Warstwa | Wymagane pokrycie | Moduly |
|---------|-------------------|--------|
| Core logic | **>= 80%** | `core/watershed.py`, `core/morphometry.py`, `core/cn_calculator.py` |
| Utility | **>= 60%** | `utils/`, `models/schemas.py` |
| Scripts | **0%** (TODO) | `scripts/process_dem.py`, `scripts/prepare_area.py` |

```bash
pytest tests/ --cov=. --cov-report=html --cov-fail-under=60
```

### 8.2 Wylaczenia

```toml
# pyproject.toml
[tool.coverage.run]
omit = ["scripts/*", "migrations/*", "tests/*", "*/conftest.py"]
```

---

## 9. JavaScript — konwencje frontend

### 9.1 Stack

| Biblioteka | Zastosowanie |
|------------|-------------|
| Leaflet.js 1.9+ | Mapa interaktywna |
| Chart.js 4.x | Wykresy hydrogramow |
| Bootstrap 5.x | UI components |

Frontend jest statyczny (Vanilla JS) — brak frameworka SPA.

### 9.2 Struktura plikow

```
frontend/
├── index.html
├── css/
│   └── style.css
└── js/
    ├── app.js               # Entry point
    ├── mapController.js     # Leaflet map logic
    ├── chartManager.js      # Chart.js rendering
    ├── apiClient.js         # HTTP client for backend
    └── utils.js             # Shared utilities
```

### 9.3 API client pattern

```javascript
const apiClient = {
  async delineateWatershed(lat, lon) {
    const response = await fetch(`${API_URL}/delineate-watershed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latitude: lat, longitude: lon }),
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.json();
  },
};
```

### 9.4 Error handling

```javascript
try {
  const data = await apiClient.delineateWatershed(lat, lon);
  mapController.displayWatershed(data);
} catch (error) {
  if (error.message.includes('422')) {
    showAlert('Punkt poza zakresem danych. Kliknij na obszar Polski.');
  } else {
    showAlert('Blad serwera. Sprobuj ponownie pozniej.');
    console.error('Delineation failed:', error);
  }
}
```

---

## 10. SQL/PostGIS — konwencje

### 10.1 Recursive CTE — kluczowy pattern

```sql
WITH RECURSIVE upstream AS (
    SELECT id, downstream_id, geom, elevation
    FROM flow_network
    WHERE id = :start_cell_id

    UNION ALL

    SELECT fn.id, fn.downstream_id, fn.geom, fn.elevation
    FROM flow_network fn
    INNER JOIN upstream u ON fn.downstream_id = u.id
)
SELECT
    ST_Union(geom) AS watershed_boundary,
    COUNT(*) AS cell_count,
    SUM(ST_Area(geom::geography)) / 1e6 AS area_km2
FROM upstream;
```

### 10.2 PostGIS — nearest stream cell

```sql
SELECT id,
    ST_Distance(geom::geography,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS distance_m
FROM flow_network
WHERE is_stream = TRUE
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
LIMIT 1;
```

### 10.3 Indeksowanie

```sql
-- GIST indexes for spatial queries (REQUIRED)
CREATE INDEX idx_flow_geom ON flow_network USING GIST(geom);
CREATE INDEX idx_landcover_geom ON land_cover USING GIST(geom);

-- B-tree indexes for graph traversal (REQUIRED)
CREATE INDEX idx_flow_downstream ON flow_network(downstream_id);
CREATE INDEX idx_flow_stream ON flow_network(is_stream) WHERE is_stream = TRUE;

-- Composite indexes for scenario lookups
CREATE INDEX idx_precip_scenario ON precipitation_data(duration, probability);
```

### 10.4 Parametrized queries — ZAWSZE

```python
# GOOD — parametrized query
query = text("SELECT id FROM flow_network WHERE downstream_id = :cell_id")
result = await session.execute(query, {"cell_id": cell_id})

# BAD — SQL injection risk!
query = f"SELECT * FROM flow_network WHERE id = {cell_id}"  # NEVER!
```

### 10.5 Migracje (Alembic)

```bash
alembic revision --autogenerate -m "add land_cover table"   # Create
alembic upgrade head                                         # Apply
alembic downgrade -1                                         # Rollback
```

Kazda zmiana schematu bazy danych wymaga migracji Alembic.

---

## 11. Git workflow (Conventional Commits)

### 11.1 Branching (Git Flow)

```
main              # Stabilna wersja (tylko merge z develop)
develop           # Aktywny rozwoj (DOMYSLNA GALAZ ROBOCZA)
feature/<nazwa>   # Nowe funkcjonalnosci
fix/<nazwa>       # Poprawki bledow
hotfix/<nazwa>    # Pilne poprawki produkcyjne (branch z main)
```

### 11.2 Tagowanie

```bash
git tag -a v0.1.0 -m "Release v0.1.0: watershed delineation MVP"
git push origin v0.1.0
```

### 11.3 Format commitow

```
<type>(<scope>): <opis>

<body>           # opcjonalny
<footer>         # opcjonalny (np. Closes #12)
```

### 11.4 Typy

| Typ | Kiedy |
|-----|-------|
| `feat` | Nowa funkcjonalnosc |
| `fix` | Poprawka bledu |
| `docs` | Tylko dokumentacja |
| `test` | Dodanie/zmiana testow |
| `refactor` | Refaktoryzacja (bez zmian funkcjonalnosci) |
| `perf` | Optymalizacja wydajnosci |
| `style` | Formatowanie (nie wplywa na logike) |
| `chore` | Config, dependencies, build |

### 11.5 Scope — specyficzne dla Hydrograf

| Scope | Warstwa | Przyklad |
|-------|---------|----------|
| `api` | Endpoints FastAPI | `feat(api): add watershed statistics endpoint` |
| `core` | Logika biznesowa | `fix(core): handle edge case in upstream traversal` |
| `db` | Baza danych, migracje | `feat(db): add land_cover table with GIST index` |
| `frontend` | Interfejs uzytkownika | `feat(frontend): add hydrograph chart rendering` |
| `tests` | Testy | `test(tests): add integration tests for watershed API` |
| `docs` | Dokumentacja | `docs(docs): update ARCHITECTURE.md` |
| `docker` | Docker, docker-compose | `chore(docker): update PostGIS to 16-3.4` |

### 11.6 Code Review

```
1. Deweloper tworzy PR
2. Automated checks:
   +-- Formatowanie (ruff format --check)
   +-- Linting (ruff check)
   +-- Type checking (mypy)
   +-- Testy (pytest --cov)
3. Manual review
4. Approval -> Merge
```

**Co sprawdza reviewer:** poprawnosc, testy, standardy, czytelnosc,
bezpieczenstwo (secrets, SQL injection), wydajnosc (N+1, indeksy).

**Wymagania PR:** testy OK, pokrycie w normie, brak bledow ruff/mypy,
min. 1 approval, brak konfliktow, dokumentacja aktualna.

---

## 12. Docker — konwencje

### 12.1 Serwisy

| Serwis | Obraz | Port | Rola |
|--------|-------|------|------|
| `db` | `postgis/postgis:16-3.4` | 5432 | PostgreSQL + PostGIS |
| `api` | custom (backend/Dockerfile) | 8000 | FastAPI backend |
| `nginx` | `nginx:alpine` | 80 | Reverse proxy + static files |

### 12.2 Zasady Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app

# System deps first (cached layer)
RUN apt-get update && apt-get install -y \
    libpq-dev libgeos-dev libproj-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps (cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (changes most often — last layer)
COPY . .
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 12.3 Zasady docker-compose

- Pinned image versions (`postgis/postgis:16-3.4`, nie `latest`)
- Explicit container names (`hydro_db`, `hydro_api`)
- Environment defaults z `.env` (`${POSTGRES_DB:-hydro_db}`)
- Named volumes dla danych (`postgres_data`)
- Healthcheck dla bazy danych (**ZAWSZE**)
- `depends_on: condition: service_healthy` dla API

### 12.4 Zmienne srodowiskowe

```bash
# .env (NIE COMMITOWAC)
POSTGRES_DB=hydro_db
POSTGRES_USER=hydro_user
POSTGRES_PASSWORD=secure_password_here
DATABASE_URL=postgresql://hydro_user:secure_password_here@db:5432/hydro_db
CORS_ORIGINS=http://localhost
LOG_LEVEL=INFO
```

### 12.5 Komendy

```bash
docker-compose up -d              # Uruchomienie stacku
docker-compose down               # Zatrzymanie
docker-compose build api          # Rebuild po zmianach
docker-compose logs -f api        # Logi
docker-compose exec api bash      # Shell w kontenerze
docker-compose exec db psql -U hydro_user -d hydro_db  # DB shell
```

---

## 13. Python — obsluga bledow

### 13.1 Hierarchia wyjatkow

```python
# core/exceptions.py

class HydrografError(Exception):
    """Base exception for Hydrograf."""

class ValidationError(HydrografError):
    """Invalid input parameter (coordinates, thresholds)."""

class DatabaseError(HydrografError):
    """Database query or connection error."""

class DelineationError(HydrografError):
    """Error during watershed delineation."""

class CalculationError(HydrografError):
    """Error during hydrological calculation."""

class IntegrationError(HydrografError):
    """Error communicating with Hydrolog, Kartograf, or IMGWTools."""
```

### 13.2 Walidacja — Pydantic na granicy API

```python
class DelineateRequest(BaseModel):
    latitude: float = Field(..., ge=49.0, le=55.0)
    longitude: float = Field(..., ge=14.0, le=25.0)
    threshold: int = Field(default=100, ge=10, le=1000)
```

### 13.3 Raise from — zachowaj lancuch wyjatkow

```python
# GOOD — preserve exception chain
try:
    result = await session.execute(query, params)
except SQLAlchemyError as e:
    raise DatabaseError(f"Query failed for cell {cell_id}: {e}") from e

# BAD — loses original traceback
except SQLAlchemyError as e:
    raise DatabaseError(f"Query failed: {e}")
```

### 13.4 FastAPI error handling

```python
@router.post("/delineate-watershed")
async def delineate(request: DelineateRequest):
    try:
        return await delineate_watershed(request.latitude, request.longitude)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except DatabaseError as e:
        logger.error("Database error: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")
    except DelineationError as e:
        logger.error("Delineation error: %s", e)
        raise HTTPException(status_code=500, detail="Delineation failed")
```

---

## 14. Python — logging

### 14.1 Konfiguracja

```python
import logging
logger = logging.getLogger(__name__)
```

Poziom ustawiany przez zmienna `LOG_LEVEL` (default: `INFO`).

### 14.2 Poziomy

```python
logger.debug("Traversing upstream from cell %d", cell_id)
logger.info("Watershed delineated: %.2f km2, %d cells", area_km2, cell_count)
logger.warning("Area %.2f km2 exceeds SCS-CN limit (250 km2)", area_km2)
logger.error("Failed to query upstream cells: %s", exc)
logger.critical("Database connection pool exhausted")
```

### 14.3 Zasady

```python
# GOOD — lazy evaluation with %s
logger.info("Watershed area: %s km2", area_km2)

# BAD — f-string (evaluated even if level is filtered out)
logger.info(f"Watershed area: {area_km2} km2")
```

Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

---

## 15. Python — wydajnosc

### 15.1 Priorytet

```
Poprawnosc > Czytelnosc > Wydajnosc
```

### 15.2 NumPy vectorization

```python
# GOOD — vectorized (fast)
def effective_precipitation(
    intensities: NDArray[np.float64], cn: int,
) -> NDArray[np.float64]:
    P_cum = np.cumsum(intensities)
    S = 25400 / cn - 254
    Pe_cum = np.where(
        P_cum > 0.2 * S,
        (P_cum - 0.2 * S) ** 2 / (P_cum + 0.8 * S), 0,
    )
    return np.diff(Pe_cum, prepend=0)

# BAD — Python loop (10-100x slower)
```

### 15.3 Connection pooling

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)
```

### 15.4 GIST indexes

```sql
CREATE INDEX idx_flow_geom ON flow_network USING GIST(geom);
CREATE INDEX idx_flow_stream ON flow_network(is_stream) WHERE is_stream = TRUE;
```

### 15.5 Avoid N+1

```python
# GOOD — batch query
query = text("SELECT id, elevation FROM flow_network WHERE id = ANY(:ids)")
result = await session.execute(query, {"ids": cell_ids})

# BAD — N+1 queries
for cell in cells:
    downstream = await session.execute(
        text("SELECT * FROM flow_network WHERE id = :id"),
        {"id": cell.downstream_id},
    )
```

### 15.6 Limity czasowe

| Operacja | Target | Timeout |
|----------|--------|---------|
| Wyznaczenie zlewni | < 10s | 30s |
| Generowanie hydrogramu | < 5s | 30s |
| Preprocessing NMT (jednorazowy) | ~3.8 min/arkusz | — |
| Wszystkie HTTP requests | — | 30s |

---

## 16. Bezpieczenstwo

### 16.1 NIGDY

```python
DATABASE_URL = "postgresql://user:password@localhost/db"  # NEVER hardcode!
query = f"SELECT * FROM flow_network WHERE id = {cell_id}"  # NEVER concat SQL!
eval(user_input)                                             # NEVER eval!
# NEVER commit .env — .gitignore must contain: .env, *.pem, *.key
```

### 16.2 ZAWSZE

```python
# Environment variables for secrets
DATABASE_URL = os.getenv("DATABASE_URL")

# Pydantic validation at API boundary
class DelineateRequest(BaseModel):
    latitude: float = Field(..., ge=49.0, le=55.0)

# Parametrized SQL
query = text("SELECT * FROM flow_network WHERE id = :id")
result = await session.execute(query, {"id": cell_id})

# Timeouts for all HTTP requests
response = await httpx.get(url, timeout=30.0)
```

### 16.3 CORS z env

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),  # From env var
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

### 16.4 Rate limiting

```python
limiter = Limiter(key_func=get_remote_address)

@app.post("/api/delineate-watershed")
@limiter.limit("10/minute")
async def delineate(request: Request):
    pass
```

---

## 17. Pre-merge checklist

```markdown
### Kod
- [ ] Formatowanie OK (`ruff format --check backend/ tests/`)
- [ ] Linting OK (`ruff check backend/ tests/`)
- [ ] Type hints OK (`mypy backend/`)
- [ ] Docstrings dla publicznych funkcji/klas (NumPy style, angielski)
- [ ] Brak hardcoded secrets

### Testy
- [ ] Testy przechodza (`pytest tests/ -v`)
- [ ] Pokrycie kodu w normie (80% core / 60% utility)
- [ ] Nowa logika pokryta testami (unit + integration)
- [ ] Async tests dzialaja (asyncio_mode = "auto")

### Baza danych
- [ ] Migracja Alembic utworzona (jesli zmiana schematu)
- [ ] Parametrized queries (brak f-string SQL)
- [ ] Indeksy GIST dla nowych kolumn geometrycznych
- [ ] Brak N+1 query patterns

### Frontend
- [ ] JSDoc dla publicznych funkcji
- [ ] Error handling z user-friendly komunikatami

### Docker
- [ ] `docker-compose up -d` dziala bez bledow
- [ ] Healthcheck przechodzi
- [ ] Brak secrets w docker-compose.yml (uzywaj .env)

### Dokumentacja i Git
- [ ] Dokumentacja zaktualizowana (jesli potrzeba)
- [ ] PROGRESS.md / CHANGELOG.md zaktualizowany
- [ ] Conventional Commits z prawidlowym scope
- [ ] Minimum 1 approval
- [ ] Brak konfliktow z target branch
```

---

**Wersja dokumentu:** 2.0
**Data ostatniej aktualizacji:** 2026-02-07
**Zrodlo:** `shared/standards/DEVELOPMENT_STANDARDS.md` v1.0

*Odstepstwa od tych standardow wymagaja uzasadnienia w `CLAUDE.md` projektu.*
