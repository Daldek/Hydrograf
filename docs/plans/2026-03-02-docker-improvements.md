# Docker Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Uzupelnic 5 brakujacych elementow konteneryzacji: .dockerignore, multi-stage Dockerfile, entrypoint.sh, API healthcheck, docker-compose.prod.yml.

**Architecture:** Multi-stage Dockerfile (builder + runtime) zmniejsza obraz z ~800MB do ~300MB. entrypoint.sh zapewnia wait-for-db + auto-migracje Alembic. docker-compose.prod.yml jako override bazowego pliku (bez --reload, bez bind mount kodu, 2 workery uvicorn).

**Tech Stack:** Docker, Docker Compose 3.8, Alembic, uvicorn, nginx:alpine, python:3.12-slim, PostgreSQL 16 + PostGIS 3.4

---

### Task 1: Create `.dockerignore`

**Files:**
- Create: `backend/.dockerignore`

**Step 1: Create .dockerignore file**

```
# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/

# Virtual environment
.venv/

# Environment files (secrets)
.env
.env.*

# Git
.git/
.gitignore

# Tests (not needed in production image)
tests/

# Dev tools cache
.ruff_cache/
.mypy_cache/
.pytest_cache/

# Documentation (not needed in image)
*.md

# Dev config (runtime deps are in requirements.txt)
pyproject.toml
```

**Step 2: Verify .dockerignore excludes correctly**

Run from project root:
```bash
# List what WOULD be sent to Docker context (approximate check)
cd backend && find . -type f \
  ! -path './.venv/*' \
  ! -path './__pycache__/*' \
  ! -path './tests/*' \
  ! -path './.git/*' \
  ! -path './.ruff_cache/*' \
  ! -path './.mypy_cache/*' \
  ! -path './.pytest_cache/*' \
  ! -name '*.pyc' \
  ! -name '*.pyo' \
  ! -name '*.md' \
  ! -name '.env' \
  ! -name '.env.*' \
  ! -name '.gitignore' \
  ! -name 'pyproject.toml' \
  | head -30
```

Expected: Only production files listed (requirements.txt, api/, core/, scripts/, models/, migrations/, alembic.ini).

**Step 3: Commit**

```bash
git add backend/.dockerignore
git commit -m "chore(docker): add .dockerignore to reduce build context"
```

---

### Task 2: Create `entrypoint.sh`

**Files:**
- Create: `backend/entrypoint.sh`

**Step 1: Create the entrypoint script**

```bash
#!/bin/bash
set -e

# ---- Wait for database ----
DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-hydro_user}"

echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
  sleep 2
done
echo "Database is ready."

# ---- Run Alembic migrations ----
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

# ---- Start application ----
exec "$@"
```

Important context for implementor:
- `alembic.ini` is in `backend/` which maps to `/app` in Docker — so `alembic upgrade head` works from WORKDIR `/app`
- `env.py` reads `DATABASE_URL` from environment (set in docker-compose.yml)
- `pg_isready` requires `postgresql-client` package (installed in runtime stage of Dockerfile)
- Script must have execute permission: `chmod +x backend/entrypoint.sh`

**Step 2: Make executable and verify syntax**

```bash
chmod +x backend/entrypoint.sh
bash -n backend/entrypoint.sh
```

Expected: No output (no syntax errors).

**Step 3: Commit**

```bash
git add backend/entrypoint.sh
git commit -m "feat(docker): add entrypoint.sh with wait-for-db and auto-migrations"
```

---

### Task 3: Convert Dockerfile to multi-stage build

**Files:**
- Modify: `backend/Dockerfile`

**Step 1: Read the current Dockerfile**

Current contents (for reference):
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Replace with multi-stage Dockerfile**

New contents:
```dockerfile
# ============================================================
# Stage 1: builder — install build tools and compile deps
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Build-time system dependencies (gcc, git for git+https:// pip deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libgeos-dev \
    libproj-dev \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: runtime — lean production image
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# Runtime-only system libraries (no compilers, no git)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgeos3.11.1 \
    libproj25 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Key details:
- `libgeos3.11.1` is the runtime lib on Debian Bookworm (python:3.12-slim base). If build fails, check with `dpkg -l 'libgeos*'` inside builder and use the correct package name.
- `postgresql-client` provides `pg_isready` used by `entrypoint.sh`
- `--no-install-recommends` minimizes package footprint
- `ENTRYPOINT` runs wait-for-db + migrations, `CMD` is the uvicorn command (overridable in compose)

**Step 3: Verify Dockerfile syntax**

```bash
docker build --check -f backend/Dockerfile backend/ 2>&1 || echo "Docker BuildKit check not available, syntax looks OK"
```

**Step 4: Commit**

```bash
git add backend/Dockerfile
git commit -m "refactor(docker): convert Dockerfile to multi-stage build

Builder stage compiles dependencies with gcc/git.
Runtime stage contains only shared libraries (~300MB vs ~800MB).
Adds ENTRYPOINT for entrypoint.sh (wait-for-db + migrations)."
```

---

### Task 4: Add API healthcheck to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Read the current docker-compose.yml**

Locate the `api:` service block and the `nginx:` service block.

**Step 2: Add healthcheck to api service**

Add after the `command:` line in the `api` service:

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

**Step 3: Update nginx depends_on to use service_healthy**

Change nginx `depends_on` from:
```yaml
    depends_on:
      - api
```

To:
```yaml
    depends_on:
      api:
        condition: service_healthy
```

This ensures nginx only starts when the API is actually responding to health checks (not just when the container is running).

**Step 4: Verify compose syntax**

```bash
docker compose config --quiet
```

Expected: No output (valid config).

**Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add API healthcheck and nginx dependency on healthy API"
```

---

### Task 5: Create docker-compose.prod.yml

**Files:**
- Create: `docker-compose.prod.yml`

**Step 1: Create the production override file**

```yaml
# Production overrides — use with:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

services:
  api:
    # No code bind mount (use built image)
    volumes:
      - ./data:/data
      - ./frontend/data:/frontend/data
      - ./frontend/tiles:/frontend/tiles
    environment:
      LOG_LEVEL: WARNING
    # No --reload, 2 workers for production
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2

  nginx:
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Key details:
- `volumes` list **replaces** the base file's volumes list (Compose override semantics) — this removes `./backend:/app` bind mount so the image's built-in code is used
- `environment` entries are **merged** — LOG_LEVEL overrides base, DATABASE_URL etc. stay
- `command` **replaces** the base `--reload` command with production `--workers 2`
- nginx healthcheck uses `wget` (available in alpine) to check the proxied `/health` endpoint

**Step 2: Verify compose override syntax**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```

Expected: No output (valid merged config).

**Step 3: Verify merged config removes ./backend bind mount**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config | grep -A5 "volumes:" | head -20
```

Expected: api volumes should list `./data:/data`, `./frontend/data:/frontend/data`, `./frontend/tiles:/frontend/tiles` but NOT `./backend:/app`.

**Step 4: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat(docker): add docker-compose.prod.yml production override

Removes --reload and code bind mount, adds 2 uvicorn workers,
sets LOG_LEVEL=WARNING, adds nginx healthcheck.
Usage: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

---

### Task 6: Integration test — build and verify

**Files:**
- None (verification only)

**Step 1: Build the Docker image**

```bash
docker compose build api
```

Expected: Successful 2-stage build. Look for:
- `[builder ...]` stage logs
- `[stage-1 ...]` or `[2/...]` runtime stage logs
- No errors

**Step 2: Check image size**

```bash
docker images | grep hydro
```

Expected: Image size ~300-400MB (down from ~800MB).

**Step 3: Start full stack**

```bash
docker compose up -d
```

Expected: All 3 services start. Check with `docker compose ps`.

**Step 4: Verify API healthcheck**

```bash
# Wait for start_period
sleep 35
docker compose ps
```

Expected: `hydro_api` shows `healthy` status.

**Step 5: Verify health endpoint**

```bash
curl -s http://localhost:8080/health | python -m json.tool
```

Expected:
```json
{
    "status": "healthy",
    "database": "connected",
    "version": "1.0.0"
}
```

**Step 6: Verify migrations ran (check entrypoint logs)**

```bash
docker compose logs api | head -20
```

Expected: Lines containing:
- "Waiting for database..."
- "Database is ready."
- "Running database migrations..."
- "Migrations complete."

**Step 7: Tear down**

```bash
docker compose down
```

**Step 8: Test production override**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api | head -20
```

Expected: API running with 2 workers, no `--reload` in process list, LOG_LEVEL=WARNING.

**Step 9: Tear down production**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

**Step 10: Commit any fixes**

If any fixes were needed during integration testing, commit them.

---

### Task 7: Update documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md` (deployment section)
- Modify: `docs/DECISIONS.md` (new ADR)
- Modify: `docs/CHANGELOG.md`

**Step 1: Add ADR to DECISIONS.md**

Find the last ADR number in `docs/DECISIONS.md` and add the next one:

```markdown
### ADR-0XX: Uzupelnienie konteneryzacji (multi-stage, entrypoint, prod override)

- **Data:** 2026-03-02
- **Status:** Accepted
- **Kontekst:** Brakujace elementy konteneryzacji: .dockerignore, multi-stage Dockerfile, entrypoint.sh z auto-migracjami, healthcheck API, docker-compose.prod.yml.
- **Opcje:**
  - A) Samodzielny docker-compose.prod.yml — prosty, ale wymaga synchronizacji z bazowym plikiem
  - B) Override docker-compose.prod.yml — DRY, bazowy plik wspoldzielony miedzy dev i prod
- **Decyzja:** Opcja B. Multi-stage Dockerfile (builder + runtime, ~300MB vs ~800MB). entrypoint.sh z wait-for-db i auto-migracjami Alembic. docker-compose.prod.yml jako override (bez --reload, bez bind mount kodu, 2 workery, LOG_LEVEL=WARNING).
- **Konsekwencje:** Mniejszy obraz produkcyjny. Automatyczne migracje na starcie. Jasny podzial dev/prod. Wymaga `docker compose -f ... -f ... up` dla produkcji.
```

**Step 2: Update ARCHITECTURE.md deployment section**

Update section 5 (deployment) to mention:
- Multi-stage Dockerfile
- entrypoint.sh with auto-migrations
- Production override: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
- API healthcheck in compose

**Step 3: Update CHANGELOG.md**

Add entry under current version/date:

```markdown
### Docker
- Dodano `.dockerignore` — mniejszy kontekst budowania
- Multi-stage Dockerfile (builder + runtime) — obraz ~300MB zamiast ~800MB
- `entrypoint.sh` z wait-for-db i automatycznymi migracjami Alembic
- Healthcheck API w docker-compose.yml (+ nginx depends_on service_healthy)
- `docker-compose.prod.yml` — override produkcyjny (2 workery, bez --reload, LOG_LEVEL=WARNING)
```

**Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md docs/DECISIONS.md docs/CHANGELOG.md
git commit -m "docs: update architecture, ADR, and changelog for Docker improvements"
```
