# HydroLOG

System analizy hydrologicznej dla wyznaczania zlewni, obliczania parametrów fizjograficznych i generowania hydrogramów odpływu.

## Status

🚧 **W budowie** - CP2 osiągnięty (Watershed delineation)

### Dostępne endpointy

| Endpoint | Opis | Status |
|----------|------|--------|
| `GET /health` | Status systemu i bazy danych | ✅ |
| `POST /api/delineate-watershed` | Wyznaczanie zlewni (GeoJSON) | ✅ |
| `POST /api/generate-hydrograph` | Generowanie hydrogramu | ⏳ |

### Przykład użycia API

```bash
# Health check
curl http://localhost:8000/health

# Wyznaczanie zlewni (współrzędne WGS84)
curl -X POST http://localhost:8000/api/delineate-watershed \
  -H "Content-Type: application/json" \
  -d '{"latitude": 52.23, "longitude": 21.01}'
```

**Response:**
```json
{
  "watershed": {
    "boundary_geojson": {"type": "Feature", "geometry": {...}, "properties": {...}},
    "outlet": {"latitude": 52.23, "longitude": 21.01, "elevation_m": 150.0},
    "cell_count": 1234,
    "area_km2": 45.67,
    "hydrograph_available": true
  }
}
```

## Funkcjonalności (planowane)

- **Wyznaczanie zlewni** - kliknięcie na mapę generuje granicę zlewni w <10s
- **Parametry fizjograficzne** - powierzchnia, CN, spadki, pokrycie terenu
- **Hydrogram odpływu** - 42 scenariusze (7 czasów × 6 prawdopodobieństw), model SCS CN
- **Eksport danych** - GeoJSON, CSV

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0, GeoAlchemy2 |
| Baza danych | PostgreSQL 16 + PostGIS 3.4 |
| Frontend | Vanilla JS, Leaflet.js, Chart.js, Bootstrap 5 |
| Infrastruktura | Docker, Docker Compose, Nginx |

## Wymagania

- Docker i Docker Compose
- Git

## Szybki start

```bash
# Klonowanie repozytorium
git clone https://github.com/Daldek/HydroLOG.git
cd HydroLOG

# Konfiguracja środowiska
cp .env.example .env
# Edytuj .env jeśli potrzebne

# Uruchomienie
docker-compose up -d

# Sprawdzenie statusu
docker-compose ps

# Aplikacja dostępna pod:
# http://localhost (frontend)
# http://localhost/api (API)
```

## Struktura projektu

```
HydroLOG/
├── backend/           # API FastAPI
│   ├── api/           # Endpointy
│   ├── core/          # Logika biznesowa
│   ├── models/        # Schematy Pydantic
│   ├── migrations/    # Migracje Alembic
│   └── tests/         # Testy
├── frontend/          # Aplikacja webowa
│   ├── css/
│   └── js/
├── docker/            # Konfiguracja Docker
├── docs/              # Dokumentacja projektowa
├── PROGRESS.md        # Status implementacji
└── docker-compose.yml
```

## Dokumentacja

- [`docs/SCOPE.md`](docs/SCOPE.md) - Zakres MVP
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - Architektura systemu
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) - Model danych
- [`docs/PRD.md`](docs/PRD.md) - Wymagania produktowe
- [`DEVELOPMENT_STANDARDS.md`](DEVELOPMENT_STANDARDS.md) - Standardy kodowania
- [`IMPLEMENTATION_PROMPT.md`](IMPLEMENTATION_PROMPT.md) - Prompt dla AI
- [`PROGRESS.md`](PROGRESS.md) - Aktualny postęp implementacji

## Rozwój

### Uruchomienie środowiska deweloperskiego

```bash
docker-compose up -d
```

### Migracje bazy danych

```bash
cd backend
alembic upgrade head
```

### Testy

```bash
cd backend
pytest --cov=. --cov-report=html
```

## Git Strategy

### Gałęzie

| Gałąź | Przeznaczenie |
|-------|---------------|
| `main` | Wersja stabilna. Merge tylko po ukończeniu checkpointu. |
| `develop` | Aktywny rozwój. Wszystkie commity tutaj. |

### Tagi

Wersjonowanie semantyczne (`vMAJOR.MINOR.PATCH`):

| Tag | Checkpoint | Opis |
|-----|------------|------|
| `v0.0.1` | - | Setup complete ✅ |
| `v0.1.0` | CP1 | Health endpoint działa ✅ |
| `v0.2.0` | CP2 | Wyznaczanie zlewni ✅ |
| `v0.3.0` | CP3 | Generowanie hydrogramu |
| `v0.4.0` | CP4 | Frontend z mapą |
| `v1.0.0` | CP5 | MVP |

### Workflow dla kontrybutorów

```bash
# Sklonuj i przełącz na develop
git clone https://github.com/Daldek/HydroLOG.git
cd HydroLOG
git checkout develop

# Po ukończeniu pracy
git add .
git commit -m "feat: opis zmian"
git push origin develop
```

### Workflow dla maintainera (po checkpoincie)

```bash
git checkout main
git merge develop
git tag -a vX.Y.Z -m "Opis checkpointu"
git push origin main --tags
git checkout develop
```

## Licencja

MIT
