# HydroLOG - Progress Tracker

## Aktualny Status

| Pole | Wartość |
|------|---------|
| **Faza** | 0 - Setup |
| **Sprint** | 0.2 - Baza danych |
| **Ostatnia sesja** | 2 |
| **Data** | 2026-01-15 |
| **Następny checkpoint** | CP2: Watershed delineation |
| **Gałąź robocza** | develop |

---

## Git Strategy

### Gałęzie
- `main` - stabilna wersja, tylko merge z develop po ukończeniu checkpointu
- `develop` - aktywny rozwój, wszystkie commity tutaj

### Tagi
| Tag | Opis |
|-----|------|
| `v0.0.1` | Setup complete - Sprint 0.1 |
| `v0.1.0` | CP1 - Health endpoint ✅ |
| `v0.2.0` | (planowany) CP2 - Watershed delineation |
| `v0.3.0` | (planowany) CP3 - Hydrograph generation |
| `v0.4.0` | (planowany) CP4 - Frontend map |
| `v1.0.0` | (planowany) CP5 - MVP |

### Workflow
```bash
# Praca na develop
git checkout develop

# Po ukończeniu checkpointu
git checkout main
git merge develop
git tag -a vX.Y.Z -m "Opis"
git checkout develop
```

---

## Checkpointy

| CP | Opis | Status |
|----|------|--------|
| CP1 | `curl localhost:8000/health` zwraca `{"status": "healthy", "database": "connected"}` | ✅ |
| CP2 | `POST /api/delineate-watershed` zwraca granicę zlewni jako GeoJSON | ⏳ |
| CP3 | `POST /api/generate-hydrograph` zwraca kompletny JSON z hydrogramem | ⏳ |
| CP4 | Mapa działa, kliknięcie wyświetla zlewnię | ⏳ |
| CP5 | MVP: Pełny flow klik → zlewnia → parametry → hydrogram → eksport | ⏳ |

---

## Faza 0: Setup

### Sprint 0.1: Inicjalizacja (Sesje 1-2) - UKOŃCZONY

- [x] Struktura katalogów (`backend/`, `frontend/`, `docker/`)
- [x] `.gitignore`
- [x] `docker-compose.yml` z PostgreSQL + PostGIS
- [x] `backend/requirements.txt`
- [x] Alembic setup (`alembic.ini`, `migrations/`)
- [x] `backend/Dockerfile`
- [x] `docker/nginx.conf`
- [x] `.env.example`
- [x] `PROGRESS.md`
- [x] `README.md`
- [x] Pierwszy commit (6cafd17)

### Sprint 0.2: Baza danych i API (Sesje 3-5) - UKOŃCZONY

- [x] Migracja 001: `precipitation_data`
- [x] Migracja 002: `flow_network`, `land_cover`, `stream_network`
- [x] Indeksy GIST i B-tree
- [x] `backend/core/config.py`
- [x] `backend/core/database.py`
- [x] `backend/core/precipitation.py`
- [x] `backend/api/main.py`
- [x] `backend/api/endpoints/health.py`
- [x] Testy integracyjne health endpoint (5/5 pass)

**CP1 OSIĄGNIĘTY**

---

## Pliki Krytyczne do Przeczytania

Na początku każdej sesji przeczytaj:

1. `PROGRESS.md` (ten plik)
2. `DEVELOPMENT_STANDARDS.md` - konwencje kodowania
3. Pliki wymienione poniżej w zależności od aktualnej pracy

### Dla pracy nad bazą danych:
- `docs/DATA_MODEL.md`
- `backend/migrations/versions/` (ostatnia migracja)

### Dla pracy nad API:
- `docs/ARCHITECTURE.md`
- `backend/api/main.py`

### Dla pracy nad frontendem:
- `frontend/README.md`
- `frontend/js/app.js`

---

## Komendy

### Uruchomienie środowiska deweloperskiego

```bash
# Start wszystkich kontenerów
docker-compose up -d

# Sprawdzenie statusu
docker-compose ps

# Logi API
docker-compose logs -f api

# Połączenie z bazą danych
docker exec -it hydro_db psql -U hydro_user -d hydro_db
```

### Migracje Alembic

```bash
cd backend

# Utworzenie nowej migracji
alembic revision --autogenerate -m "opis_migracji"

# Wykonanie migracji
alembic upgrade head

# Cofnięcie migracji
alembic downgrade -1

# Historia migracji
alembic history
```

### Testy

```bash
cd backend

# Wszystkie testy
pytest

# Z coverage
pytest --cov=. --cov-report=html

# Tylko unit testy
pytest tests/unit/

# Konkretny test
pytest tests/unit/test_geometry.py -v
```

---

## Ostatnia Sesja

### Sesja 2 (2026-01-15) - UKOŃCZONA

**Wykonane:**
- Utworzono migrację 002 z tabelami: `flow_network`, `land_cover`, `stream_network`
- Utworzono `backend/api/main.py` - FastAPI aplikacja
- Utworzono `backend/api/endpoints/health.py` - health endpoint
- Utworzono testy integracyjne dla health endpoint (5/5 pass)
- **CP1 osiągnięty**

**Następne kroki (Sesja 3):**
1. Rozpocząć CP2 - Watershed delineation
2. Utworzyć `backend/core/watershed.py`
3. Utworzyć endpoint `POST /api/delineate-watershed`
4. Utworzyć `backend/models/schemas.py` z Pydantic models

---

## Instrukcja dla Nowej Sesji

1. Przeczytaj `PROGRESS.md` (ten plik)
2. Sprawdź sekcję "Ostatnia Sesja" - co zostało zrobione, co jest w trakcie
3. Sprawdź "Pliki Krytyczne" odpowiednie dla planowanej pracy
4. Kontynuuj od "Następnych kroków" lub rozpocznij nowe zadanie
5. **Po zakończeniu sesji:** Zaktualizuj ten plik!

---

## Notatki Techniczne

### Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0, GeoAlchemy2
- **Baza:** PostgreSQL 16 + PostGIS 3.4
- **Frontend:** Vanilla JS, Leaflet.js, Chart.js, Bootstrap 5
- **Infrastruktura:** Docker, Docker Compose, Nginx

### Konwencje

- **Docstrings:** NumPy style
- **Type hints:** Wymagane wszędzie
- **Testy:** >80% coverage
- **Układ współrzędnych:** EPSG:2180 (PL-1992)

### Znane Problemy

- Warning Pydantic: "Support for class-based `config` is deprecated" - do naprawy w przyszłości
