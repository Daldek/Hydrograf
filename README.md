# Hydrograf

System analizy hydrologicznej dla wyznaczania zlewni, obliczania parametrów fizjograficznych i generowania hydrogramów odpływu.

## Status

✅ **CP4 osiągnięty** - Frontend z mapą interaktywną

### Dostępne endpointy

| Endpoint | Opis | Status |
|----------|------|--------|
| `GET /health` | Status systemu i bazy danych | ✅ |
| `POST /api/delineate-watershed` | Wyznaczanie zlewni (GeoJSON) | ✅ |
| `POST /api/generate-hydrograph` | Generowanie hydrogramu | ✅ |
| `GET /api/scenarios` | Lista dostępnych scenariuszy | ✅ |
| `POST /api/terrain-profile` | Profil terenu wzdłuż cieku | ✅ |
| `GET /api/depressions` | Zagłębienia terenu (blue spots) | ✅ |
| `POST /api/select-stream` | Wybór cieku i zlewnia cząstkowa | ✅ |
| `GET /api/tiles/streams/{z}/{x}/{y}.pbf` | Kafelki MVT — cieki | ✅ |
| `GET /api/tiles/catchments/{z}/{x}/{y}.pbf` | Kafelki MVT — zlewnie cząstkowe | ✅ |
| `GET /api/tiles/landcover/{z}/{x}/{y}.pbf` | Kafelki MVT — pokrycie terenu | ✅ |
| `GET /api/tiles/thresholds` | Dostępne progi akumulacji | ✅ |
| `GET /api/admin/dashboard` | Panel admina — status systemu | ✅ |
| `POST /api/admin/bootstrap/start` | Uruchomienie pipeline preprocessingu | ✅ |
| `GET /api/admin/bootstrap/status` | Status pipeline | ✅ |
| `GET /api/admin/bootstrap/stream` | SSE stream logów pipeline | ✅ |
| `POST /api/admin/bootstrap/cancel` | Anulowanie pipeline | ✅ |
| `GET /api/admin/resources` | Lista zasobów (pliki, tabele) | ✅ |
| `GET /api/admin/cleanup/estimate` | Estymacja czyszczenia | ✅ |
| `POST /api/admin/cleanup` | Czyszczenie zasobów | ✅ |

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
    "area_km2": 45.67,
    "hydrograph_available": true,
    "morphometry": {"area_km2": 45.67, "perimeter_km": 32.1, "...": "..."}
  }
}
```

## Funkcjonalności

- **Wyznaczanie zlewni** - kliknięcie na mapę generuje granicę zlewni w <10s
- **Parametry fizjograficzne** - powierzchnia, CN, spadki, pokrycie terenu
- **Hydrogram odpływu** - 42 scenariusze (7 czasów × 6 prawdopodobieństw), model SCS CN
- **Mapa interaktywna** - Leaflet.js, kafelki MVT (cieki, zlewnie, land cover), DEM z hillshade
- **Panel administracyjny** - bootstrap pipeline, monitoring zasobów, czyszczenie danych
- **Eksport danych** - GeoJSON, CSV

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0, GeoAlchemy2 |
| Baza danych | PostgreSQL 16 + PostGIS 3.4 |
| Frontend | Vanilla JS, Leaflet.js, Chart.js, Bootstrap 5 |
| Infrastruktura | Docker, Docker Compose, Nginx |

## Wymagania

### Development
- Python 3.12+
- Git
- Docker (tylko dla PostGIS)

### Deployment (Docker)
- Docker i Docker Compose
- Git

### Deployment (bare-metal / VPS)
- Python 3.12+
- PostgreSQL 16 + PostGIS 3.4
- Nginx
- Git

## Szybki start

### Development (.venv + PostGIS w Docker)

```bash
# Klonowanie repozytorium
git clone https://github.com/Daldek/Hydrograf.git
cd Hydrograf

# Konfiguracja środowiska
cp .env.example .env

# Uruchomienie bazy danych
docker compose up -d db

# Setup .venv
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e ".[dev]"

# Migracje
alembic upgrade head

# Serwer dev
.venv/bin/python -m uvicorn api.main:app --reload
# API dostępne pod http://localhost:8000
```

### Pełny stack (Docker Compose)

```bash
git clone https://github.com/Daldek/Hydrograf.git
cd Hydrograf
cp .env.example .env

docker compose up -d

# Aplikacja dostępna pod:
# http://localhost (frontend)
# http://localhost/api (API)
```

### Deployment na VPS bez Dockera (np. Mikrus)

Scenariusz: **preprocessing na maszynie lokalnej**, serwowanie na tanim VPS.
Pipeline preprocessingu (NMT, land cover, HSG) wymaga ~4 GB RAM i dużo CPU — nie nadaje się na mały VPS. Zamiast tego przetwarzamy dane lokalnie, a na serwer przenosimy gotową bazę i pliki statyczne.

#### Architektura

```
┌──────────────────────┐         pg_dump + rsync        ┌──────────────────┐
│   Maszyna lokalna    │  ──────────────────────────►   │   VPS (Mikrus)   │
│                      │                                │                  │
│  bootstrap.py        │                                │  PostgreSQL      │
│  (NMT, land cover,   │                                │  + PostGIS       │
│   HSG, IMGW, tiles)  │                                │                  │
│                      │                                │  uvicorn (API)   │
│  PostgreSQL + PostGIS│                                │  nginx (proxy    │
│  (przetwarzanie)     │                                │   + frontend)    │
└──────────────────────┘                                └──────────────────┘
```

#### Krok 1 — Preprocessing na maszynie lokalnej

Uruchom pipeline na maszynie z wystarczającą ilością RAM (4 GB+):

```bash
# Na maszynie lokalnej — pełny pipeline
cd backend
.venv/bin/python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
```

Po zakończeniu masz dane w PostgreSQL oraz pliki w `data/` i `frontend/`.

#### Krok 2 — Eksport danych

```bash
# Dump bazy danych
pg_dump -U hydro_user -d hydro_db -Fc -f hydro_db.dump

# Spakuj pliki danych (DEM raster + frontend assets)
tar czf hydrograf-data.tar.gz \
    data/nmt/dem_mosaic.vrt \
    data/nmt/dem_mosaic_01_dem.tif \
    frontend/data/ \
    frontend/tiles/
```

#### Krok 3 — Setup VPS

```bash
# PostgreSQL 16 + PostGIS
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-postgis-3 \
    libpq-dev libgeos-dev libproj-dev gcc git python3.12 python3.12-venv nginx

# Utworzenie bazy
sudo -u postgres psql <<SQL
CREATE USER hydro_user WITH PASSWORD 'TWOJE_SILNE_HASLO';
CREATE DATABASE hydro_db OWNER hydro_user;
\c hydro_db
CREATE EXTENSION IF NOT EXISTS postgis;
ALTER DATABASE hydro_db SET postgis.gdal_enabled_drivers = 'ENABLE_ALL';
SQL
```

Tuning PostgreSQL dla małego VPS (1–2 GB RAM):

```bash
sudo -u postgres psql -c "
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET work_mem = '8MB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET effective_cache_size = '512MB';
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET jit = off;
ALTER SYSTEM SET statement_timeout = '120s';
"
sudo systemctl restart postgresql
```

#### Krok 4 — Transfer danych na VPS

```bash
# Z maszyny lokalnej
scp hydro_db.dump hydrograf-data.tar.gz user@vps:/home/user/

# Na VPS — import bazy
pg_restore -U hydro_user -d hydro_db -Fc hydro_db.dump

# Na VPS — rozpakuj pliki
cd /home/user/Hydrograf
tar xzf /home/user/hydrograf-data.tar.gz
```

#### Krok 5 — Backend (FastAPI)

```bash
cd /home/user/Hydrograf/backend

python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Migracje (wyrównanie schematu po pg_restore)
.venv/bin/alembic upgrade head
```

Plik `.env` w katalogu `backend/`:

```env
DATABASE_URL=postgresql://hydro_user:TWOJE_SILNE_HASLO@localhost:5432/hydro_db
LOG_LEVEL=INFO
DEM_PATH=/home/user/Hydrograf/data/nmt/dem_mosaic.vrt
ADMIN_API_KEY=twoj_klucz_admina
```

Serwis systemd:

```ini
# /etc/systemd/system/hydrograf.service
[Unit]
Description=Hydrograf API
After=postgresql.service
Requires=postgresql.service

[Service]
Type=exec
User=user
WorkingDirectory=/home/user/Hydrograf/backend
EnvironmentFile=/home/user/Hydrograf/backend/.env
ExecStart=/home/user/Hydrograf/backend/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now hydrograf
```

#### Krok 6 — Nginx (reverse proxy + frontend)

```nginx
# /etc/nginx/sites-available/hydrograf
server {
    listen 80;
    server_name twoja-domena.pl;

    root /home/user/Hydrograf/frontend;
    index index.html;

    # Pliki statyczne z cache
    location ~* \.(css|js|png|ico|svg|pbf|geojson)$ {
        expires 1h;
        add_header Cache-Control "public, must-revalidate";
    }

    # Admin panel
    location = /admin {
        try_files /admin.html =404;
    }

    # SSE stream (bootstrap) — dłuższy timeout
    location = /api/admin/bootstrap/stream {
        proxy_pass http://127.0.0.1:8000/api/admin/bootstrap/stream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    # Frontend SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/hydrograf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

#### Krok 7 — HTTPS (opcjonalne, zalecane)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d twoja-domena.pl
```

#### Aktualizacja danych

Gdy przetworzone zostaną nowe obszary na maszynie lokalnej:

```bash
# Lokalnie — inkrementalny dump
pg_dump -U hydro_user -d hydro_db -Fc -f hydro_db_new.dump

# Lokalnie — zaktualizowane pliki
rsync -avz data/nmt/ user@vps:/home/user/Hydrograf/data/nmt/
rsync -avz frontend/data/ user@vps:/home/user/Hydrograf/frontend/data/
rsync -avz frontend/tiles/ user@vps:/home/user/Hydrograf/frontend/tiles/

# Na VPS — podmiana bazy
sudo systemctl stop hydrograf
pg_restore -U hydro_user -d hydro_db --clean -Fc hydro_db_new.dump
sudo systemctl start hydrograf
```

#### Minimalne wymagania VPS

| Zasób | Minimum | Zalecane |
|-------|---------|----------|
| RAM   | 1 GB (+1 GB swap) | 2 GB |
| CPU   | 1 vCPU  | 2 vCPU |
| Dysk  | 5 GB + dane | 10 GB + dane |

> **Uwaga:** Rozmiar danych zależy od przetworzonego obszaru. Przykład: okolice Poznania (~55M komórek NMT) to ~150 MB w bazie + ~110 MB plików statycznych.

## Struktura projektu

```
Hydrograf/
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
│   ├── PROGRESS.md    # Status implementacji
│   ├── CHANGELOG.md   # Historia zmian
│   ├── DECISIONS.md   # Decyzje architektoniczne (ADR)
│   └── ...            # PRD, SCOPE, ARCHITECTURE, integracje
└── docker-compose.yml
```

## Dokumentacja

- [`docs/SCOPE.md`](docs/SCOPE.md) - Zakres MVP
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - Architektura systemu
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) - Model danych
- [`docs/PRD.md`](docs/PRD.md) - Wymagania produktowe
- [`docs/KARTOGRAF_INTEGRATION.md`](docs/KARTOGRAF_INTEGRATION.md) - Integracja z Kartografem (pobieranie NMT)
- [`docs/DECISIONS.md`](docs/DECISIONS.md) - Decyzje architektoniczne (ADR)
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) - Historia zmian
- [`docs/BENCHMARK_QUERIES.md`](docs/BENCHMARK_QUERIES.md) - Benchmark zapytań PostGIS
- [`docs/DEVELOPMENT_STANDARDS.md`](docs/DEVELOPMENT_STANDARDS.md) - Standardy kodowania
- [`docs/IMPLEMENTATION_PROMPT.md`](docs/IMPLEMENTATION_PROMPT.md) - Prompt dla AI
- [`docs/PROGRESS.md`](docs/PROGRESS.md) - Aktualny postęp implementacji

## Preprocessing danych NMT

Przed uruchomieniem systemu wymagane jest jednorazowe przetworzenie danych NMT (Numeryczny Model Terenu) z GUGiK.

### Integracja z Kartografem

Hydrograf wykorzystuje [Kartograf](https://github.com/Daldek/Kartograf) do automatycznego pobierania danych NMT z GUGiK. Kartograf eliminuje konieczność ręcznego pobierania plików z Geoportalu.

#### Automatyczne pobieranie i przetwarzanie (zalecane)

```bash
cd backend

# Przygotowanie danych dla obszaru (pobieranie + przetwarzanie)
.venv/bin/python -m scripts.prepare_area \
    --lat 52.23 --lon 21.01 \
    --buffer 5

# Tylko pobieranie NMT (bez przetwarzania)
.venv/bin/python -m scripts.download_dem \
    --lat 52.23 --lon 21.01 \
    --buffer 5 \
    --output ../data/nmt/
```

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--lat`, `--lon` | Współrzędne centrum obszaru (WGS84) | (wymagane) |
| `--buffer` | Promień bufora w km | 5 |
| `--output`, `-o` | Katalog wyjściowy | `../data/nmt/` |
| `--format` | Format pobierania (AAIGrid, GTiff) | AAIGrid |

#### Ręczne przetwarzanie (gdy masz już pliki .asc)

```bash
cd backend

# Podstawowe użycie - import do bazy danych
.venv/bin/python -m scripts.process_dem \
    --input ../data/nmt/nazwa_pliku.asc

# Z zapisem plików pośrednich (dla zaawansowanych użytkowników)
.venv/bin/python -m scripts.process_dem \
    --input ../data/nmt/nazwa_pliku.asc \
    --save-intermediates

# Tylko statystyki (bez importu)
.venv/bin/python -m scripts.process_dem \
    --input ../data/nmt/nazwa_pliku.asc \
    --dry-run
```

### Wymagania

- Uruchomiona baza PostgreSQL/PostGIS (`docker compose up -d db`)
- Wykonane migracje (`cd backend && alembic upgrade head`)
- Połączenie z internetem (dla automatycznego pobierania)

### Opcje

| Parametr | Opis | Domyślnie |
|----------|------|-----------|
| `--input`, `-i` | Ścieżka do pliku .asc | (wymagane) |
| `--stream-threshold` | Próg akumulacji dla strumieni | 1000 |
| `--batch-size` | Rozmiar batch przy imporcie | 10000 |
| `--dry-run` | Tylko statystyki, bez importu | false |
| `--save-intermediates`, `-s` | Zapis plików GeoTIFF | false |
| `--output-dir`, `-o` | Katalog wyjściowy dla GeoTIFF | (katalog wejściowy) |

### Pliki pośrednie (dla weryfikacji obliczeń)

Opcja `--save-intermediates` zapisuje pliki GeoTIFF do weryfikacji w QGIS:

| Plik | Opis |
|------|------|
| `*_01_dem.tif` | Oryginalny NMT |
| `*_02_filled.tif` | NMT po wypełnieniu zagłębień |
| `*_03_flowdir.tif` | Kierunek przepływu (D8) |
| `*_04_flowacc.tif` | Akumulacja przepływu |
| `*_05_slope.tif` | Spadek terenu [%] |
| `*_06_streams.tif` | Maska strumieni |

> **Uwaga:** Pliki pośrednie są przeznaczone dla zaawansowanych użytkowników do weryfikacji poprawności obliczeń hydrologicznych.

---

## Rozwój

### Uruchomienie środowiska deweloperskiego

```bash
docker compose up -d db
cd backend && .venv/bin/python -m uvicorn api.main:app --reload
```

### Migracje bazy danych

```bash
cd backend
alembic upgrade head
```

### Testy

```bash
cd backend

# Testy jednostkowe (domyślne — 774 testy)
.venv/bin/python -m pytest tests/ -q

# Testy integracyjne z PostGIS (wymagają działającej bazy)
.venv/bin/python -m pytest tests/integration/test_select_stream_correctness.py -m db -v

# Benchmarki wydajności zapytań PostGIS
.venv/bin/python -m pytest tests/performance/ -m benchmark -v -s

# Pokrycie kodu
.venv/bin/python -m pytest --cov=. --cov-report=html
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
| `v0.2.1` | - | Fix: poprawne wypełnianie zagłębień ✅ |
| `v0.3.0` | CP3 | Generowanie hydrogramu ✅ |
| `v0.4.0` | CP4 | Frontend z mapą interaktywną ✅ |
| `v1.0.0` | CP5 | MVP |

### Workflow dla kontrybutorów

```bash
# Sklonuj i przełącz na develop
git clone https://github.com/Daldek/Hydrograf.git
cd Hydrograf
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

Projekt udostępniony na licencji MIT. Szczegóły w pliku `LICENSE`.

## Autor

[Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/)
