# Design: Uzupelnienie konteneryzacji Hydrograf

**Data:** 2026-03-02
**Status:** Zatwierdzony

## Kontekst

Analiza konteneryzacji wykazala 5 brakujacych elementow:
1. Brak `.dockerignore` — caly `backend/` kopiowany do obrazu
2. Brak multi-stage Dockerfile — gcc/git w obrazie produkcyjnym (~800MB)
3. Brak `entrypoint.sh` — brak wait-for-db i auto-migracji
4. Brak healthcheck API w compose — nginx nie wie czy API gotowe
5. Brak `docker-compose.prod.yml` — brak konfiguracji produkcyjnej

## Decyzje

- `docker-compose.prod.yml` jako override bazowego pliku (nie samodzielny)
- Dockerfile 2-stage: builder + runtime
- `entrypoint.sh` z automatycznymi migracjami Alembic
- Uzycie: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

## A. `.dockerignore` (backend/)

Umieszczony w `backend/.dockerignore`:

```
__pycache__/
*.pyc
*.pyo
.venv/
.env
.env.*
.git/
.gitignore
tests/
*.md
.ruff_cache/
.mypy_cache/
.pytest_cache/
pyproject.toml
```

Zachowuje: `requirements.txt`, `api/`, `core/`, `scripts/`, `models/`, `alembic/`, `alembic.ini`, `entrypoint.sh`.

## B. Multi-stage Dockerfile

### Stage 1: builder
- Baza: `python:3.12-slim`
- System deps: libpq-dev, libgeos-dev, libproj-dev, gcc, git
- Instaluje pakiety do `/opt/venv`

### Stage 2: runtime
- Baza: `python:3.12-slim`
- System deps: libpq5, libgeos-c1v5, libproj25, postgresql-client
- Kopiuje `/opt/venv` z buildera
- Bez gcc/git — mniejszy obraz (~300MB vs ~800MB)
- ENTRYPOINT: `/entrypoint.sh`
- CMD: `uvicorn api.main:app --host 0.0.0.0 --port 8000`

## C. entrypoint.sh

1. Wait-for-db: `pg_isready` loop (2s interwaly)
2. Alembic migracje: `alembic upgrade head` (idempotentne)
3. `exec "$@"` — przekazuje CMD

## D. API healthcheck w docker-compose.yml

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

Nginx `depends_on` zmienia sie na `condition: service_healthy`.

## E. docker-compose.prod.yml (override)

Roznice wzgledem bazowego:
- API: brak `--reload`, brak bind mount `./backend:/app`, 2 workery, LOG_LEVEL=WARNING
- Nginx: healthcheck (`wget --spider`)
- Uzycie: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
