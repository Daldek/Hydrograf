# HydroLOG

System analizy hydrologicznej dla wyznaczania zlewni, obliczania parametrów fizjograficznych i generowania hydrogramów odpływu.

## Status

🚧 **W budowie** - Faza 0: Setup

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
├── PROGRESS.md        # Status implementacji
├── *.md               # Dokumentacja projektowa
└── docker-compose.yml
```

## Dokumentacja

- `SCOPE.md` - Zakres MVP
- `ARCHITECTURE.md` - Architektura systemu
- `DATA_MODEL.md` - Model danych
- `PRD.md` - Wymagania produktowe
- `DEVELOPMENT_STANDARDS.md` - Standardy kodowania
- `PROGRESS.md` - Aktualny postęp implementacji

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
| `v0.0.1` | - | Setup complete |
| `v0.1.0` | CP1 | Health endpoint działa |
| `v0.2.0` | CP2 | Wyznaczanie zlewni |
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
