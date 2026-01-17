# HydroLOG - Progress Tracker

## Aktualny Status

| Pole | Wartość |
|------|---------|
| **Faza** | 0 - Setup |
| **Sprint** | 0.3 - Watershed API |
| **Ostatnia sesja** | 4 |
| **Data** | 2026-01-17 |
| **Następny checkpoint** | CP3: Hydrograph generation |
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
| `v0.2.0` | CP2 - Watershed delineation ✅ |
| `v0.2.1` | Fix: poprawne wypełnianie zagłębień (pysheds) ✅ |
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
| CP2 | `POST /api/delineate-watershed` zwraca granicę zlewni jako GeoJSON | ✅ |
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

### Sprint 0.2: Baza danych i API (Sesje 2) - UKOŃCZONY

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

### Sprint 0.3: Watershed API (Sesja 3) - UKOŃCZONY

- [x] `backend/models/schemas.py` - Pydantic modele (DelineateRequest, WatershedResponse)
- [x] `backend/utils/__init__.py` i `geometry.py` - transformacje współrzędnych (WGS84 ↔ PL-1992)
- [x] `backend/core/watershed.py` - logika biznesowa (FlowCell, find_nearest_stream, traverse_upstream, build_boundary)
- [x] `backend/api/endpoints/watershed.py` - endpoint POST /api/delineate-watershed
- [x] `backend/tests/conftest.py` - fixtures dla testów
- [x] `backend/tests/unit/test_geometry.py` - 19 testów jednostkowych
- [x] `backend/tests/unit/test_watershed.py` - 21 testów jednostkowych
- [x] `backend/tests/integration/test_watershed.py` - 17 testów integracyjnych
- [x] Pokrycie kodu: 89.52% (wymagane >= 80%)

**CP2 OSIĄGNIĘTY**

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

### Preprocessing NMT

```bash
cd backend

# Import danych NMT do bazy (wymagane przed użyciem API)
.venv/bin/python -m scripts.process_dem --input ../data/nmt/plik.asc

# Z zapisem plików pośrednich GeoTIFF (do weryfikacji w QGIS)
.venv/bin/python -m scripts.process_dem \
    --input ../data/nmt/plik.asc \
    --save-intermediates

# Tylko statystyki (bez importu)
.venv/bin/python -m scripts.process_dem --input ../data/nmt/plik.asc --dry-run
```

Szczegółowa dokumentacja: `backend/scripts/README.md`

---

## Ostatnia Sesja

### Sesja 4 (2026-01-17) - UKOŃCZONA

**Wykonane:**
- Przetestowano skrypt `process_dem.py` z rzeczywistymi danymi NMT z Geoportalu
- Naprawiono błąd konwersji `numpy.bool` → `bool` (psycopg2)
- Naprawiono problem FK violation - dwufazowy insert (najpierw bez FK, potem UPDATE)
- Naprawiono konfigurację `DATABASE_URL` dla Docker (obsługa zmiennej środowiskowej)
- **KRYTYCZNA POPRAWKA:** Zidentyfikowano i naprawiono błąd w `fill_depressions`:
  - Stara implementacja zostawiała wewnętrzne zagłębienia bez odpływu
  - Zastąpiono biblioteką `pysheds` (fill_pits → fill_depressions → resolve_flats → flowdir)
  - Teraz wszystkie komórki mają poprawny kierunek odpływu
- Przetestowano endpoint `/api/delineate-watershed` - zwraca prawidłową zlewnię
- Uzupełniono dokumentację:
  - `README.md` - sekcja Preprocessing
  - `backend/scripts/README.md` - dokumentacja skryptów
  - `PROGRESS.md` - sekcja Komendy → Preprocessing NMT
- Utworzono tag `v0.2.1`

**Następne kroki (Sesja 5):**
1. Rozpocząć CP3 - Hydrograph generation
2. Utworzyć `backend/core/hydrograph.py` z metodą SCS-CN
3. Utworzyć endpoint `POST /api/generate-hydrograph`
4. Testy jednostkowe i integracyjne dla hydrogramu

---

### Sesja 3 (2026-01-17) - UKOŃCZONA

**Wykonane:**
- Utworzono `backend/models/schemas.py` z modelami Pydantic (DelineateRequest, WatershedResponse)
- Utworzono `backend/utils/geometry.py` z transformacjami współrzędnych (WGS84 ↔ PL-1992)
- Utworzono `backend/core/watershed.py` z logiką biznesową (FlowCell, find_nearest_stream, traverse_upstream, build_boundary)
- Utworzono `backend/api/endpoints/watershed.py` z endpointem POST /api/delineate-watershed
- Utworzono pełny zestaw testów: 57 nowych testów (40 unit + 17 integration)
- Naprawiono problemy z Shapely 2.0+ (concave_hull jako funkcja modułu)
- **CP2 osiągnięty** - 135 testów przechodzi, pokrycie 89.52%

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
