# DEVELOPMENT_STANDARDS.md - Standardy Deweloperskie
## System Analizy Hydrologicznej

**Wersja:** 1.0  
**Data:** 2026-01-14  
**Status:** Obowiązujący

---

## 1. Wprowadzenie

Ten dokument definiuje **wszystkie standardy deweloperskie** dla projektu:
- 📝 Konwencje nazewnictwa i formatowania
- ✅ Zasady testowania i jakości kodu
- 🔀 Git workflow i code review
- 🔒 Bezpieczeństwo i wydajność
- 📊 Monitoring i CI/CD
- 📚 Dokumentacja

**Wszyscy członkowie zespołu muszą przestrzegać tych standardów.**

---

## CZĘŚĆ I: KONWENCJE KODOWANIA

---

## 2. Nazewnictwo

### 2.1 Python

#### Zmienne i Funkcje
```python
# DOBRZE - snake_case + jednostka
area_km2 = 45.3
time_concentration_min = 68.5
rainfall_intensity_mm_per_min = 1.5

def calculate_flow_direction(dem):
    pass

def find_nearest_stream(point):
    pass

# ŹLE
areaKm2 = 45.3  # camelCase
a = 45.3  # nieopisowe
area = 45.3  # brak jednostki
def FlowDirection(dem):  # PascalCase
    pass
```

#### Klasy i Stałe
```python
# DOBRZE - PascalCase dla klas
class WatershedDelineator:
    pass

class HydrographGenerator:
    pass

# DOBRZE - UPPER_SNAKE_CASE dla stałych
DEFAULT_TIME_STEP_MIN = 5
FLOW_ACCUMULATION_THRESHOLD = 100

# ŹLE
class watershed_delineator:  # snake_case
    pass

flow_accumulation_threshold = 250  # nie wygląda jak stała
```

#### Zmienne Prywatne
```python
class Watershed:
    def __init__(self):
        self.area_km2 = 0          # publiczne
        self._cells = []            # protected (konwencja)
        self.__internal_cache = {}  # private (name mangling)
```

---

### 2.2 JavaScript

#### Zmienne, Funkcje, Klasy
```javascript
// DOBRZE - camelCase
const watershedArea = 45.3;
let currentZoom = 10;

function calculateBounds(coordinates) {
    return bounds;
}

async function fetchHydrograph(lat, lon) {
    // ...
}

// DOBRZE - PascalCase dla klas
class MapController {
    constructor() {
        this.map = null;
    }
}

// DOBRZE - UPPER_SNAKE_CASE dla stałych
const API_URL = 'http://localhost:8000/api';
const MAX_ZOOM = 18;
const DEFAULT_CENTER = [52.0, 21.0];

// ŹLE
const watershed_area = 45.3;  // snake_case
const WatershedArea = 45.3;   // PascalCase dla zmiennej
let x = 10;                   // nieopisowe
```

#### Event Handlers
```javascript
// DOBRZE - prefix "on" lub "handle"
function onMapClick(event) {}
function handleSubmit() {}
function handleWatershedLoaded(data) {}

// ŹLE
function mapClick() {}   // brak prefixu
function clicked() {}    // niejednoznaczne
```

---

### 2.3 SQL i Baza Danych

#### Tabele i Kolumny
```sql
-- DOBRZE - snake_case
CREATE TABLE flow_network (
    id SERIAL PRIMARY KEY,
    elevation FLOAT,
    flow_accumulation INT,
    slope FLOAT,
    cell_area FLOAT
);

-- ŹLE
CREATE TABLE FlowNetwork (...);        -- PascalCase
CREATE TABLE flow-network (...);      -- kebab-case
CREATE TABLE flownetwork (...);       -- brak separatora
```

#### Indeksy i Constraints
```sql
-- DOBRZE - opisowe nazwy
CREATE INDEX idx_flow_geom ON flow_network(geom);
CREATE INDEX idx_precipitation_scenario ON precipitation_data(duration, probability);

CONSTRAINT valid_elevation CHECK (elevation >= -50 AND elevation <= 3000);
CONSTRAINT positive_area CHECK (cell_area > 0);

-- ŹLE
CREATE INDEX index1 ON flow_network(geom);  -- nieopisowe
CONSTRAINT chk1 CHECK (elevation >= -50);   -- nieopisowe
```

---

### 2.4 Pliki i Katalogi

#### Struktura
```
hydro-system/              # kebab-case dla głównego folderu
├── backend/               # snake_case
│   ├── api/
│   ├── core/
│   │   ├── watershed.py
│   │   ├── hydrograph.py
│   │   └── land_cover.py
│   └── tests/
├── frontend/
│   ├── js/
│   │   ├── map.js
│   │   ├── api.js
│   │   └── chart.js
│   └── css/
└── docs/
```

#### Nazwy Plików
```
# Python - snake_case
watershed_delineation.py
hydrograph_generator.py
test_watershed.py

# JavaScript - camelCase lub kebab-case
mapController.js     # camelCase (jeśli zawiera klasę)
api-client.js        # kebab-case (funkcje utility)

# Dokumentacja - UPPERCASE lub kebab-case
README.md
SCOPE.md
architecture-diagram.png
```

---

### 2.5 Jednostki i Wymiary

**ZAWSZE dodawaj jednostkę do nazwy zmiennej:**

| Wielkość | Jednostka | Symbol | Przykład zmiennej |
|----------|-----------|--------|-------------------|
| Długość | kilometr | km | `length_km` |
| Długość | metr | m | `elevation_m` |
| Powierzchnia | kilometr² | km² | `area_km2` |
| Powierzchnia | metr² | m² | `cell_area_m2` |
| Opad | milimetr | mm | `precipitation_mm` |
| Intensywność | mm/min | mm/min | `intensity_mm_per_min` |
| Przepływ | m³/s | m³/s | `discharge_m3s` |
| Czas | minuta | min | `time_min`, `tc_min` |
| Spadek | procent | % | `slope_percent` |

```python
# DOBRZE
area_km2 = 45.3
length_m = 8200
precipitation_mm = 38.5

# ŹLE
area = 45.3      # km2 czy m2?
length = 8200    # m czy km?
rainfall = 38.5  # mm czy cm?
```

---

## 3. Formatowanie Kodu

### 3.1 Python (PEP 8 + Black)

#### Długość Linii i Wcięcia
```python
# Maksymalnie 88 znaków (Black standard)
# 4 spacje (NIGDY tabulatory)

# DOBRZE
def calculate_physical_parameters(
    watershed_boundary, 
    cells, 
    main_stream
):
    pass

# ŹLE (> 88 znaków)
def calculate_physical_parameters(watershed_boundary, cells, main_stream, elevation_data):
    pass
```

#### Importy
```python
# Kolejność: stdlib → third-party → local
# Alfabetycznie w każdej grupie
# Puste linie między grupami

import os
import sys
from typing import List, Optional

import numpy as np
from fastapi import FastAPI
from shapely.geometry import Point

from core.watershed import delineate
from models.schemas import WatershedResponse
```

#### Spacje
```python
# DOBRZE
x = 5
result = function(a, b, c)
my_list = [1, 2, 3]
my_dict = {'key': 'value'}

if x > 0:
    pass

# ŹLE
x=5                        # brak spacji wokół =
result = function (a,b,c)  # spacja przed (, brak po przecinkach
my_list=[1,2,3]            # brak spacji
```

#### Docstrings (NumPy Style)
```python
def calculate_time_of_concentration(
    length_km: float,
    slope_percent: float,
    method: str = 'kirpich'
) -> float:
    """
    Oblicza czas koncentracji zlewni.

    Parameters
    ----------
    length_km : float
        Długość głównego cieku [km]
    slope_percent : float
        Średni spadek cieku [%]
    method : str, optional
        Metoda obliczenia ('kirpich' lub 'scs'), domyślnie 'kirpich'

    Returns
    -------
    float
        Czas koncentracji w minutach

    Raises
    ------
    ValueError
        Jeśli length_km <= 0 lub slope_percent <= 0

    Examples
    --------
    >>> calculate_time_of_concentration(8.2, 2.3)
    68.5
    """
    pass
```

---

### 3.2 JavaScript (Airbnb Style)

#### Długość Linii i Wcięcia
```javascript
// Maksymalnie 100 znaków
// 2 spacje

// DOBRZE
function calculateBounds(coordinates) {
  const lats = coordinates.map(c => c[1]);
  const lons = coordinates.map(c => c[0]);
  
  return {
    minLat: Math.min(...lats),
    maxLat: Math.max(...lats),
    minLon: Math.min(...lons),
    maxLon: Math.max(...lons)
  };
}
```

#### Średniki i Cudzysłowy
```javascript
// ZAWSZE średniki
const x = 5;
const y = 10;
console.log(x + y);

// Single quotes, template literals dla interpolacji
const name = 'Hydro System';
const url = `${API_URL}/watershed`;

// ŹLE
const x = 5  // brak średnika
const name = "Hydro System";  // double quotes
```

#### Arrow Functions
```javascript
// DOBRZE - używaj dla callbacks
markers.map(m => m.getLatLng());
data.filter(d => d.value > 0);

setTimeout(() => {
  console.log('Done');
}, 1000);

// ŹLE
markers.map(function(m) {
  return m.getLatLng();
});
```

---

### 3.3 SQL

#### Wielkość Liter i Formatowanie
```sql
-- KEYWORDS: UPPERCASE
-- identyfikatory: lowercase

-- DOBRZE
SELECT 
    id, 
    elevation, 
    flow_accumulation
FROM flow_network
WHERE is_stream = TRUE
ORDER BY elevation DESC
LIMIT 100;

-- Multi-line z wcięciami
WITH upstream AS (
    SELECT id, geom
    FROM flow_network
    WHERE downstream_id = $1
)
SELECT 
    u.id,
    u.geom
FROM upstream u;

-- ŹLE
select id, elevation from flow_network where is_stream = true;
```

---

## 4. Komentarze i Dokumentacja

### 4.1 Inline Comments

```python
# DOBRZE - wyjaśnia "dlaczego", nie "co"
# Wzór Kirpicha wymaga długości w metrach
length_m = length_km * 1000

# Rozkład Beta lepiej odwzorowuje rzeczywiste opady niż blokowy
alpha, beta_param = 2.0, 5.0

# ŹLE - oczywiste komentarze
# Pomnóż przez 1000
length_m = length_km * 1000

# Ustaw alpha na 2
alpha = 2.0
```

### 4.2 TODO, FIXME, HACK

```python
# TODO: Dodać cache dla często używanych zlewni
# FIXME: Obsłużyć przypadek gdy CN > 100 (błąd danych)
# HACK: Tymczasowe rozwiązanie do czasu refactoringu modułu
# NOTE: Ten algorytm jest zgodny z SCS TR-55 (1986)
# OPTIMIZE: Można by użyć NumPy vectorization tutaj
```

### 4.3 JSDoc (JavaScript)

```javascript
/**
 * Wyświetla granicę zlewni na mapie
 * 
 * @param {Object} boundaryGeoJSON - Granica jako GeoJSON Feature
 * @param {L.Map} map - Instancja mapy Leaflet
 * @returns {L.GeoJSON} Layer z granicą zlewni
 * @throws {Error} Jeśli boundaryGeoJSON jest invalid
 * 
 * @example
 * const layer = displayWatershed(geojson, map);
 */
function displayWatershed(boundaryGeoJSON, map) {
    // ...
}
```

---

## CZĘŚĆ II: ZASADY ZESPOŁU

---

## 5. Testowanie

### 5.1 Strategia Testowa (Test Pyramid)

```
         /\
        /  \  E2E Tests (10%)
       /    \
      /------\
     /        \
    / Integr.  \ Integration Tests (20%)
   /   Tests    \
  /--------------\
 /                \
/   Unit Tests     \ Unit Tests (70%)
/--------------------\
```

**Wymagania:**
- **Pokrycie kodu: ≥ 80%**
- Unit tests: ~70% wszystkich testów
- Integration tests: ~20%
- E2E tests: ~10%

### 5.2 Nazewnictwo Testów

```python
# DOBRZE - test_<funkcja>_<scenariusz>_<oczekiwany_wynik>
def test_hietogram_beta_suma_equals_total_rainfall():
    pass

def test_wyznacz_zlewnię_returns_error_for_area_over_limit():
    pass

def test_calculate_cn_with_100_percent_forest():
    pass

# ŹLE
def test_hietogram():  # za ogólne
    pass

def test_1():  # nieopisowe
    pass
```

### 5.3 Struktura Testów (AAA Pattern)

```python
def test_calculate_flow_accumulation():
    # Arrange - przygotowanie danych testowych
    dem = np.array([[5, 4, 3], [6, 5, 4], [7, 6, 5]])
    
    # Act - wykonanie testowanej funkcji
    flow_acc = calculate_flow_accumulation(dem)
    
    # Assert - sprawdzenie wyniku
    assert flow_acc[0, 2] == 3
```

### 5.4 Framework

**Python:** pytest  
**JavaScript:** Jest

```bash
# Uruchomienie testów
pytest tests/ --cov=backend/ --cov-report=html

# JavaScript
npm test
```

---

## 6. Git Workflow

### 6.1 Branching Strategy (Git Flow)

```
main (production)
  ↓
develop
  ↓
feature/nazwa-funkcji
hotfix/nazwa-poprawki
bugfix/nazwa-bledu
```

**Zasady:**
- `main` - tylko stabilny kod produkcyjny
- `develop` - integracja wszystkich feature'ów
- `feature/*` - nowe funkcjonalności
- `bugfix/*` - poprawki błędów
- `hotfix/*` - pilne poprawki produkcyjne

### 6.2 Commit Messages (Conventional Commits)

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Typy:**
- `feat` - Nowa funkcjonalność
- `fix` - Poprawka błędu
- `docs` - Dokumentacja
- `style` - Formatowanie (nie wpływa na kod)
- `refactor` - Refaktoryzacja
- `test` - Testy
- `chore` - Inne (config, deps)
- `perf` - Optymalizacja wydajności

**Przykłady:**
```bash
feat(watershed): dodaj algorytm wyznaczania zlewni

Implementacja traversal grafu flow_network do wyznaczania granic
zlewni bez operacji rastrowych.

Closes #12

---

fix(api): napraw błąd dla zlewni > 200 km²

Dodano walidację powierzchni i zwracanie 400 Bad Request.

Fixes #45

---

docs(readme): aktualizuj instrukcje instalacji

---

refactor(hydrograph): zastąp pętle Pythonowe przez NumPy

Zwiększa wydajność o ~50x.
```

### 6.3 Scope (dozwolone wartości)

- `api` - Endpoints FastAPI
- `core` - Logika biznesowa
- `db` - Baza danych, migrations
- `frontend` - Interfejs użytkownika
- `tests` - Testy
- `docs` - Dokumentacja
- `ci` - CI/CD pipeline
- `docker` - Docker, docker-compose

---

## 7. Code Review

### 7.1 Proces

```
1. Deweloper tworzy PR
2. Automated checks (CI/CD)
   ├─> Formatowanie (black, prettier)
   ├─> Linting (flake8, eslint)
   ├─> Testy (pytest, jest)
   └─> Coverage check (≥ 80%)
3. Manual review (inny deweloper)
4. Zmiany jeśli potrzeba
5. Approval
6. Merge
```

### 7.2 Wymagania PR

**PR jest gotowy do merge gdy:**
- ✅ Wszystkie testy przechodzą
- ✅ Pokrycie kodu ≥ 80%
- ✅ Formatowanie zgodne (black/prettier)
- ✅ Brak linting errors
- ✅ Minimum 1 approval
- ✅ Brak konfliktów z target branch
- ✅ Dokumentacja zaktualizowana (jeśli potrzeba)

### 7.3 Co Sprawdza Reviewer

- **Poprawność:** Czy kod działa zgodnie z wymaganiami?
- **Standardy:** Czy przestrzega DEVELOPMENT_STANDARDS.md?
- **Testy:** Czy są odpowiednie testy?
- **Wydajność:** Czy są oczywiste bottlenecki?
- **Bezpieczeństwo:** SQL injection, input validation?
- **Czytelność:** Czy kod jest zrozumiały?

### 7.4 Czas Odpowiedzi

- Standardowy PR: **24 godziny**
- Krytyczny PR: **4 godziny**

---

## 8. Bezpieczeństwo

### 8.1 NIGDY

```python
# ❌ NIGDY hardcode secrets
API_KEY = "sk-1234567890abcdef"  # NIGDY!

# ❌ NIGDY commit .env
# Dodaj do .gitignore:
.env
.env.local
*.pem
*.key

# ❌ NIGDY eval() na user input
eval(user_input)  # NIGDY!

# ❌ NIGDY SQL konkatenacja
query = f"SELECT * FROM users WHERE id = {user_id}"  # NIGDY!
```

### 8.2 ZAWSZE

```python
# ✅ ZAWSZE zmienne środowiskowe
import os
API_KEY = os.getenv('API_KEY')

# ✅ ZAWSZE walidacja input
from pydantic import BaseModel, Field

class DelineateRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

# ✅ ZAWSZE prepared statements
from sqlalchemy import text

query = text("SELECT * FROM users WHERE id = :id")
result = db.execute(query, {"id": user_id})

# ✅ ZAWSZE HTTPS (produkcja)
# nginx.conf:
# listen 443 ssl;
# ssl_certificate /etc/nginx/ssl/cert.pem;
```

### 8.3 Rate Limiting

```python
# FastAPI + slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/delineate-watershed")
@limiter.limit("10/minute")
async def delineate(request: Request):
    pass
```

---

## 9. Wydajność

### 9.1 Priorytety

```
Poprawność > Czytelność > Wydajność
```

**Najpierw:** Zrób działające  
**Potem:** Zrób czytelne  
**Na końcu:** Zrób szybkie (jeśli potrzeba)

### 9.2 Database

```sql
-- ✅ ZAWSZE indeksy dla często filtrowanych kolumn
CREATE INDEX idx_flow_geom ON flow_network USING GIST(geom);
CREATE INDEX idx_downstream ON flow_network(downstream_id);

-- ✅ UNIKAJ N+1 queries
-- ŹLE:
for cell in cells:
    downstream = db.query(Cell).filter(Cell.id == cell.downstream_id).first()

-- DOBRZE:
downstream_ids = [c.downstream_id for c in cells]
downstream_cells = db.query(Cell).filter(Cell.id.in_(downstream_ids)).all()

-- ✅ UŻYWAJ LIMIT
SELECT * FROM flow_network WHERE is_stream = TRUE LIMIT 1000;
```

### 9.3 Python

```python
# ✅ DOBRZE - NumPy vectorization
import numpy as np

def oblicz_opad_efektywny(intensywnosci, cn):
    P_cum = np.cumsum(intensywnosci)
    S = 25400 / cn - 254
    Pe_cum = np.where(P_cum > 0.2 * S, 
                      (P_cum - 0.2 * S)**2 / (P_cum + 0.8 * S), 
                      0)
    return np.diff(Pe_cum, prepend=0)

# ❌ ŹLE - Python loop (10-100x wolniejsze)
def oblicz_opad_efektywny_slow(intensywnosci, cn):
    Pe = []
    for i in intensywnosci:
        # ... kalkulacje ...
        Pe.append(result)
    return Pe
```

### 9.4 Caching

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_cn_value(land_cover_category: str) -> int:
    """Cache dla często używanych wartości CN."""
    mapping = {
        'las': 60,
        'łąka': 70,
        'grunt_orny': 78,
        # ...
    }
    return mapping.get(land_cover_category, 75)
```

### 9.5 Limity Czasowe

- Wyznaczenie zlewni: **< 10s**
- Generowanie hydrogramu: **< 5s**
- API timeout: **30s**

---

## 10. CI/CD Pipeline

### 10.1 GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Black
        run: black --check backend/
      - name: Flake8
        run: flake8 backend/ --max-line-length=88

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgis/postgis:15-3.3
    steps:
      - uses: actions/checkout@v2
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest tests/ --cov=backend/ --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2

  build:
    runs-on: ubuntu-latest
    needs: [lint, test]
    steps:
      - uses: actions/checkout@v2
      - name: Build Docker image
        run: docker build -t hydro:latest .
```

### 10.2 Środowiska

```
┌─────────────────────────────────────────────┐
│           DEVELOPMENT                       │
│  - Auto-deploy z develop branch            │
│  - DEBUG logs                               │
│  - Hot reload                               │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│            STAGING                          │
│  - Manual deploy                            │
│  - INFO logs                                │
│  - Production-like data                     │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           PRODUCTION                        │
│  - Manual deploy + approval                 │
│  - WARNING+ logs                            │
│  - HTTPS enabled                            │
│  - Monitoring active                        │
└─────────────────────────────────────────────┘
```

---

## 11. Monitoring i Logging

### 11.1 Log Levels

```python
import logging

logger = logging.getLogger(__name__)

# DEBUG - szczegóły debugowania (tylko development)
logger.debug(f"Traversing upstream from cell {cell_id}")

# INFO - normalne operacje
logger.info(f"Watershed delineated: {area_km2:.2f} km²")

# WARNING - ostrzeżenia (nie błędy)
logger.warning(f"Watershed area {area_km2:.2f} km² close to limit")

# ERROR - błędy które nie przerywają działania
logger.error(f"Failed to query precipitation data: {e}")

# CRITICAL - błędy krytyczne
logger.critical(f"Database connection lost")
```

### 11.2 Metryki

**Zbieramy:**
- Czas odpowiedzi (p50, p95, p99)
- Requests per minute
- Error rate (4xx, 5xx)
- CPU/Memory usage
- Database slow queries (> 1s)

**Narzędzia:**
- Prometheus (metryki)
- Grafana (dashboards)
- Sentry (error tracking)

---

## 12. Dokumentacja

### 12.1 Wymagana Dokumentacja

**Code-level:**
- ✅ Docstrings dla wszystkich public funkcji/klas
- ✅ Inline comments dla nieoczywistej logiki
- ✅ Type hints (Python)

**Project-level:**
- ✅ README.md w każdym głównym module
- ✅ API documentation (OpenAPI/Swagger)
- ✅ Architecture Decision Records (ADR) dla kluczowych decyzji
- ✅ User manual (dla użytkowników końcowych)

### 12.2 README.md Template

```markdown
# Nazwa Modułu

## Opis
1-2 zdania opisujące moduł

## Instalacja
```bash
pip install -r requirements.txt
```

## Użycie
```python
from module import function
result = function(args)
```

## API Reference
(link do szczegółowej dokumentacji)

## Testy
```bash
pytest tests/
```
```

---

## 13. Pre-Merge Checklist

**Przed każdym merge sprawdź:**

```markdown
- [ ] Kod sformatowany (black/prettier)
- [ ] Brak linting errors (flake8/eslint)
- [ ] Type hints dodane (Python)
- [ ] Docstrings dla public funkcji
- [ ] Testy napisane (unit + integration)
- [ ] Wszystkie testy przechodzą
- [ ] Pokrycie kodu ≥ 80%
- [ ] CI/CD pipeline green
- [ ] Dokumentacja zaktualizowana
- [ ] Brak hardcoded secrets
- [ ] Minimum 1 approval
- [ ] Brak konfliktów z target branch
```

---

## 14. Glossary - Pojęcia Techniczne

| Termin | Definicja |
|--------|-----------|
| **MVP** | Minimum Viable Product |
| **PR** | Pull Request |
| **CI/CD** | Continuous Integration/Continuous Deployment |
| **UAT** | User Acceptance Testing |
| **AAA** | Arrange-Act-Assert (pattern testów) |
| **NMT** | Numeryczny Model Terenu |
| **CN** | Curve Number |
| **tc** | Czas koncentracji |
| **precipitation** | Maksymalne opady (prawdopodobieństwo × czas) |

---

## 15. Podsumowanie Kluczowych Standardów

| Aspekt | Standard | Przykład |
|--------|----------|----------|
| **Python zmienne** | snake_case + jednostka | `area_km2`, `time_min` |
| **Python funkcje** | snake_case + czasownik | `calculate_cn()` |
| **Python klasy** | PascalCase | `WatershedDelineator` |
| **JavaScript zmienne** | camelCase | `watershedArea` |
| **SQL tabele** | snake_case, mn. | `flow_network` |
| **SQL kolumny** | snake_case, poj. | `elevation` |
| **Commits** | Conventional Commits | `feat(api): add endpoint` |
| **Testy** | Pokrycie ≥ 80% | pytest --cov |
| **Długość linii** | Python: 88, JS: 100 | Black/Prettier |
| **Code review** | Minimum 1 approval | - |

---

**Wersja dokumentu:** 1.0  
**Data ostatniej aktualizacji:** 2026-01-14  
**Status:** Obowiązujący dla wszystkich członków zespołu  

---

*Te standardy są obowiązkowe. Odstępstwa wymagają uzasadnienia i zatwierdzenia przez Tech Lead.*
