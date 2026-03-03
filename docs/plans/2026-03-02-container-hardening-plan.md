# Container Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden Docker containerization for production readiness — non-root user, security context, secrets management, optional TLS, localhost port binding, admin rate limiting.

**Architecture:** Purely infrastructure changes — no business logic modifications. All changes confined to Docker/Nginx config files, `config.py` credential defaults, and `admin_auth.py` key logging. Dev workflow unchanged (override.yml still works).

**Tech Stack:** Docker Compose, Nginx, Python/Pydantic-settings, Bash

**Design doc:** `docs/plans/2026-03-02-container-hardening-design.md`

---

### Task 1: Non-root user in Dockerfile

**Files:**
- Modify: `backend/Dockerfile:26-52` (runtime stage)

**Step 1: Add hydro user and set ownership**

In `backend/Dockerfile`, after the runtime apt-get block (line 37) and before COPY venv (line 40), add user creation. After `COPY . .` (line 44), add chown and USER directive.

Replace runtime stage (lines 26-52) with:

```dockerfile
# ============================================================
# Stage 2: runtime — lean production image
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# Runtime-only system libraries (no compilers, no git)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgeos-c1t64 \
    libproj25 \
    libexpat1 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running the application
RUN groupadd -r hydro && useradd -r -g hydro -d /app -s /sbin/nologin hydro

# Copy pre-built virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Ensure entrypoint is executable and set ownership
RUN chmod +x /app/entrypoint.sh && chown -R hydro:hydro /app

USER hydro

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Verify build succeeds**

Run: `cd /home/claude-agent/workspace/Hydrograf && docker compose build api`
Expected: Build completes without errors.

**Step 3: Verify container runs as non-root**

Run: `docker compose run --rm api whoami`
Expected: Output is `hydro` (not `root`).

**Step 4: Commit**

```bash
git add backend/Dockerfile
git commit -m "fix(docker): run API container as non-root hydro user"
```

---

### Task 2: Security context in docker-compose.yml

**Files:**
- Modify: `docker-compose.yml:1-84`

**Step 1: Add security options to db service**

After `shm_size: 256m` (line 21, db service), add:

```yaml
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETUID
      - SETGID
      - FOWNER
      - DAC_READ_SEARCH
```

**Step 2: Add security options to api service**

After `start_period: 30s` (line 68, api service), add:

```yaml
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:size=100M
```

**Step 3: Add security options to nginx service**

After `restart: unless-stopped` (line 81, nginx service), add:

```yaml
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    read_only: true
    tmpfs:
      - /tmp:size=10M
      - /var/cache/nginx:size=50M
      - /var/run:size=1M
```

**Step 4: Verify all services start**

Run: `docker compose up -d && docker compose ps`
Expected: All 3 services running (healthy). Check logs: `docker compose logs --tail=20`

If api fails with read-only filesystem errors, check which path needs writing and add it to tmpfs or verify volumes cover it.

**Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(docker): add security context — no-new-privileges, cap_drop, read-only rootfs"
```

---

### Task 3: Bind Nginx port to localhost

**Files:**
- Modify: `docker-compose.yml:74` (nginx ports)

**Step 1: Change nginx port binding**

Replace line 74:
```yaml
      - "${HYDROGRAF_PORT:-8080}:80"
```
with:
```yaml
      - "127.0.0.1:${HYDROGRAF_PORT:-8080}:80"
```

**Step 2: Verify nginx only listens on localhost**

Run: `docker compose up -d nginx && ss -tlnp | grep 8080`
Expected: Shows `127.0.0.1:8080` (not `0.0.0.0:8080`).

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(docker): bind Nginx to localhost only (127.0.0.1)"
```

---

### Task 4: Secrets management — remove hardcoded credentials

**Files:**
- Modify: `docker-compose.yml:8` (POSTGRES_PASSWORD default)
- Modify: `docker-compose.yml:43` (DATABASE_URL default)
- Modify: `backend/core/config.py:41` (postgres_password default)
- Modify: `backend/core/config.py:119` (_DEFAULT_CONFIG password)
- Modify: `.gitignore` (add secrets/)

**Step 1: Update docker-compose.yml — fail if password not set**

Replace line 8:
```yaml
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-hydro_password}
```
with:
```yaml
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env file}
```

Replace line 43 similarly:
```yaml
      DATABASE_URL: postgresql://${POSTGRES_USER:-hydro_user}:${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-hydro_db}
```

**Step 2: Update config.py — empty default password**

In `backend/core/config.py`, line 41, change:
```python
    postgres_password: str = "hydro_password"
```
to:
```python
    postgres_password: str = ""
```

In `_DEFAULT_CONFIG` (line 119), change:
```python
        "password": "hydro_password",
```
to:
```python
        "password": "",
```

**Step 3: Add secrets/ to .gitignore**

After line 103 (`.worktrees/`), add:
```
# Docker secrets
secrets/
```

**Step 4: Verify .env still works for dev**

The existing `.env` file (gitignored) has `POSTGRES_PASSWORD=hydro_password` — dev workflow unchanged.

Run: `cd /home/claude-agent/workspace/Hydrograf/backend && .venv/bin/python -c "from core.config import get_settings; s = get_settings(); print(s.postgres_password)"`

Expected: Prints `hydro_password` (loaded from .env) or empty string (if no .env).

**Step 5: Commit**

```bash
git add docker-compose.yml backend/core/config.py .gitignore
git commit -m "fix(docker): remove hardcoded default credentials, fail loudly if unset"
```

---

### Task 5: Docker secrets support in docker-compose.prod.yml

**Files:**
- Modify: `docker-compose.prod.yml:1-17`

**Step 1: Add secrets section and env overrides**

Replace the entire file with:

```yaml
# Production overrides — use with:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

services:
  api:
    environment:
      LOG_LEVEL: WARNING
      ADMIN_API_KEY_FILE: /run/secrets/admin_api_key
    secrets:
      - db_password
      - admin_api_key
    # 2 workers for production (no --reload)
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2

  nginx:
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 5s
      retries: 3

secrets:
  db_password:
    file: ${SECRETS_DIR:-./secrets}/db_password.txt
  admin_api_key:
    file: ${SECRETS_DIR:-./secrets}/admin_api_key.txt
```

**Step 2: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat(docker): add Docker secrets support in production compose"
```

---

### Task 6: Admin auth — stop logging generated key, require explicit config

**Files:**
- Modify: `backend/api/dependencies/admin_auth.py:22-34`

**Step 1: Write test for admin key requirement**

Create test file `backend/tests/unit/test_admin_auth_hardened.py`:

```python
"""Tests for hardened admin auth — key must be explicitly configured."""

import pytest
from unittest.mock import patch, MagicMock

from api.dependencies.admin_auth import _get_or_generate_admin_key


def test_configured_key_returned():
    """Configured key is returned as-is."""
    assert _get_or_generate_admin_key("my-secret") == "my-secret"


def test_empty_key_generates_fallback():
    """Empty key generates a UUID fallback (for dev convenience)."""
    import api.dependencies.admin_auth as mod
    mod._generated_key = None  # Reset module state
    result = _get_or_generate_admin_key("")
    assert len(result) == 36  # UUID format
    mod._generated_key = None  # Cleanup


def test_generated_key_not_logged_in_full(caplog):
    """Generated key must NOT appear in full in log messages."""
    import api.dependencies.admin_auth as mod
    mod._generated_key = None
    with caplog.at_level("WARNING"):
        key = _get_or_generate_admin_key("")
    # Key should NOT appear in full in any log message
    for record in caplog.records:
        assert key not in record.message, "Full admin key leaked in logs!"
    mod._generated_key = None
```

**Step 2: Run test to verify it fails**

Run: `cd /home/claude-agent/workspace/Hydrograf/backend && .venv/bin/python -m pytest tests/unit/test_admin_auth_hardened.py -v`
Expected: `test_generated_key_not_logged_in_full` FAILS (key is currently logged in full).

**Step 3: Fix admin_auth.py — redact key in log**

Replace lines 22-34 in `backend/api/dependencies/admin_auth.py`:

```python
def _get_or_generate_admin_key(configured_key: str) -> str:
    """Return configured key, or generate and log a random one."""
    global _generated_key
    if configured_key:
        return configured_key
    if _generated_key is None:
        _generated_key = str(uuid.uuid4())
        logger.warning(
            "ADMIN_API_KEY not configured — generated random key "
            "(set ADMIN_API_KEY or ADMIN_API_KEY_FILE env var for persistent key)"
        )
    return _generated_key
```

Key change: removed `%s, _generated_key` from the log message — no longer leaks the key.

**Step 4: Run tests to verify they pass**

Run: `cd /home/claude-agent/workspace/Hydrograf/backend && .venv/bin/python -m pytest tests/unit/test_admin_auth_hardened.py -v`
Expected: All 3 tests PASS.

**Step 5: Run existing admin auth tests**

Run: `cd /home/claude-agent/workspace/Hydrograf/backend && .venv/bin/python -m pytest tests/ -k admin -v`
Expected: All existing admin tests still pass.

**Step 6: Commit**

```bash
git add backend/api/dependencies/admin_auth.py backend/tests/unit/test_admin_auth_hardened.py
git commit -m "fix(api): stop logging admin API key in full — redact for security"
```

---

### Task 7: Rate limiting on admin endpoints in Nginx

**Files:**
- Modify: `docker/nginx.conf:17-20` (add admin_limit zone)
- Modify: `docker/nginx.conf:58-62` (admin location block)
- Modify: `docker/nginx.conf:72-80` (admin SSE location block)

**Step 1: Add admin rate limit zone**

After line 19 (`tile_limit` zone), add:
```nginx
    limit_req_zone $binary_remote_addr zone=admin_limit:1m rate=5r/s;
```

**Step 2: Add rate limiting to admin panel location**

Replace admin panel block (lines 58-62):
```nginx
        # Admin panel
        location = /admin {
            root /usr/share/nginx/html;
            try_files /admin.html =404;
        }
```
with:
```nginx
        # Admin panel
        location = /admin {
            root /usr/share/nginx/html;
            try_files /admin.html =404;
        }

        # Admin API — stricter rate limiting
        location /api/admin/ {
            limit_req zone=admin_limit burst=10 nodelay;
            limit_req_status 429;

            proxy_pass http://api_backend/api/admin/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
```

Note: The admin SSE location (`= /api/admin/bootstrap/stream`) has exact match priority, so it still overrides this prefix match for the bootstrap stream.

**Step 3: Verify nginx config is valid**

Run: `docker compose run --rm nginx nginx -t`
Expected: `nginx: configuration file /etc/nginx/nginx.conf test is successful`

**Step 4: Commit**

```bash
git add docker/nginx.conf
git commit -m "fix(docker): add rate limiting (5r/s) on admin API endpoints"
```

---

### Task 8: Update .env.example with full documentation

**Files:**
- Modify: `.env.example:1-19`

**Step 1: Replace .env.example with comprehensive version**

```env
# =============================================================================
# Hydrograf Environment Configuration
# Copy to .env and fill in values. NEVER commit .env to version control.
# =============================================================================

# --- Database ---
POSTGRES_DB=hydro_db
POSTGRES_USER=hydro_user
POSTGRES_PASSWORD=              # REQUIRED — set a strong password!
POSTGRES_HOST=localhost         # Use 'db' when running in Docker Compose
POSTGRES_PORT=5432

# --- API ---
LOG_LEVEL=INFO                  # DEBUG, INFO, WARNING, ERROR
DEM_PATH=/data/nmt/dem_mosaic.vrt
CORS_ORIGINS=http://localhost,http://localhost:8080

# --- Admin Panel ---
# Set ONE of these (ADMIN_API_KEY takes precedence):
# ADMIN_API_KEY=your-secret-key-here
ADMIN_API_KEY_FILE=admin.key    # Path to file containing the key

# --- Nginx ---
HYDROGRAF_PORT=8080             # External port for web UI

# --- IMGW Preprocessing ---
IMGW_GRID_SPACING_KM=2.0
IMGW_RATE_LIMIT_DELAY_S=0.5

# --- TLS (production only) ---
# SERVER_NAME=hydrograf.example.com
# SECRETS_DIR=./secrets         # Directory with Docker secrets files
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(docker): expand .env.example with full variable documentation"
```

---

### Task 9: Optional TLS — nginx-ssl.conf.template

**Files:**
- Create: `docker/nginx-ssl.conf.template` (new file)
- Modify: `docker-compose.prod.yml` (add TLS overrides for nginx)

**Step 1: Create SSL nginx config template**

Create `docker/nginx-ssl.conf.template`:

```nginx
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/geo+json application/javascript text/xml application/xml application/x-protobuf;

    # Rate limiting zones
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=tile_limit:10m rate=30r/s;
    limit_req_zone $binary_remote_addr zone=general_limit:10m rate=30r/s;
    limit_req_zone $binary_remote_addr zone=admin_limit:1m rate=5r/s;

    upstream api_backend {
        server api:8000;
    }

    # HTTP → HTTPS redirect
    server {
        listen 80;
        server_name ${SERVER_NAME};
        return 301 https://$host$request_uri;
    }

    # HTTPS server
    server {
        listen 443 ssl;
        server_name ${SERVER_NAME};

        # TLS configuration
        ssl_certificate /etc/nginx/certs/fullchain.pem;
        ssl_certificate_key /etc/nginx/certs/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5:!RC4;
        ssl_prefer_server_ciphers on;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 10m;

        # Security headers
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; img-src 'self' https://*.tile.openstreetmap.org https://server.arcgisonline.com https://*.tile.opentopomap.org https://mapy.geoportal.gov.pl data:; font-src 'self' https://cdn.jsdelivr.net; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        # Tile proxy
        location ^~ /api/tiles/ {
            limit_req zone=tile_limit burst=200 nodelay;
            limit_req_status 429;
            proxy_pass http://api_backend/api/tiles/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 15s;
            proxy_cache_valid 200 1d;
        }

        # Cache for static files
        location ~* \.(css|js|png|ico|svg|pbf|geojson)$ {
            root /usr/share/nginx/html;
            expires 1h;
            add_header Cache-Control "public, must-revalidate";
        }

        # Admin panel
        location = /admin {
            root /usr/share/nginx/html;
            try_files /admin.html =404;
        }

        # Admin API — stricter rate limiting
        location /api/admin/ {
            limit_req zone=admin_limit burst=10 nodelay;
            limit_req_status 429;
            proxy_pass http://api_backend/api/admin/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Frontend
        location / {
            root /usr/share/nginx/html;
            index index.html;
            try_files $uri $uri/ /index.html;
        }

        # Admin SSE stream
        location = /api/admin/bootstrap/stream {
            proxy_pass http://api_backend/api/admin/bootstrap/stream;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Admin-Key $http_x_admin_key;
            proxy_read_timeout 3600s;
            proxy_buffering off;
        }

        # API proxy
        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;
            limit_req_status 429;
            proxy_pass http://api_backend/api/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 30s;
            proxy_send_timeout 30s;
            proxy_read_timeout 120s;
        }

        # Health check
        location /health {
            proxy_pass http://api_backend/health;
            proxy_set_header Host $host;
        }
    }
}
```

**Step 2: Add TLS nginx override to docker-compose.prod.yml**

Add to the nginx service in `docker-compose.prod.yml` (this is optional — operator adds cert volume):

```yaml
  # To enable TLS, uncomment and provide certificates:
  # nginx:
  #   ports:
  #     - "443:443"
  #     - "80:80"
  #   volumes:
  #     - ./frontend:/usr/share/nginx/html:ro
  #     - ./docker/nginx-ssl.conf.template:/etc/nginx/templates/default.conf.template:ro
  #     - ./docker/certs:/etc/nginx/certs:ro
  #   environment:
  #     - SERVER_NAME=${SERVER_NAME:-localhost}
```

Add this as a commented-out section in `docker-compose.prod.yml` after the `nginx:` service.

**Step 3: Add certs/ to .gitignore**

After the `secrets/` line added in Task 4, add:
```
docker/certs/
```

**Step 4: Commit**

```bash
git add docker/nginx-ssl.conf.template docker-compose.prod.yml .gitignore
git commit -m "feat(docker): add optional TLS/HTTPS nginx config template"
```

---

### Task 10: Entrypoint improvements

**Files:**
- Modify: `backend/entrypoint.sh:1-21`

**Step 1: Add pipefail and directory creation**

Replace entrypoint.sh with:

```bash
#!/bin/bash
set -eo pipefail

# ---- Ensure data directories exist ----
mkdir -p /tmp/hydrograf

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

**Step 2: Verify entrypoint works with non-root user**

Run: `docker compose build api && docker compose up -d api && docker compose logs api --tail=10`
Expected: "Database is ready." and "Migrations complete." messages, application starts.

**Step 3: Commit**

```bash
git add backend/entrypoint.sh
git commit -m "fix(docker): add pipefail and tmp directory creation to entrypoint"
```

---

### Task 11: Integration verification and docs update

**Files:**
- Modify: `docs/CHANGELOG.md` (add entry)
- Modify: `docs/DECISIONS.md` (add ADR)

**Step 1: Full stack integration test**

Run:
```bash
cd /home/claude-agent/workspace/Hydrograf
docker compose down
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=5
```

Verify:
- All 3 services healthy
- API responds: `curl -s http://127.0.0.1:8080/health | python -m json.tool`
- Container runs as non-root: `docker exec hydro_api whoami` → `hydro`
- Security context active: `docker inspect hydro_api --format '{{.HostConfig.SecurityOpt}}'` → `[no-new-privileges]`
- Nginx on localhost only: `ss -tlnp | grep 8080` → `127.0.0.1:8080`

**Step 2: Run unit tests**

Run: `cd /home/claude-agent/workspace/Hydrograf/backend && .venv/bin/python -m pytest tests/unit/ -v --tb=short`
Expected: All tests pass (including new admin auth test).

**Step 3: Add ADR to DECISIONS.md**

Add new ADR entry for container hardening (ADR-036 or next available number):
- Title: "Hardening kontenerow Docker"
- Context: Luki bezpieczenstwa przed produkcja
- Decision: Non-root, security context, secrets, opcjonalny TLS
- Status: Accepted

**Step 4: Update CHANGELOG.md**

Add entry under current version section.

**Step 5: Commit**

```bash
git add docs/CHANGELOG.md docs/DECISIONS.md
git commit -m "docs: add ADR and changelog for container hardening"
```

---

## Task Dependency Graph

```
Task 1 (Dockerfile non-root)
    └── Task 2 (security context) — needs non-root to work with read_only
        └── Task 3 (nginx localhost) — small, independent
Task 4 (secrets management) — independent
Task 5 (prod secrets) — depends on Task 4
Task 6 (admin auth) — independent
Task 7 (nginx rate limit) — independent
Task 8 (.env.example) — independent
Task 9 (TLS template) — depends on Task 7 (rate limit zones must match)
Task 10 (entrypoint) — depends on Task 1 (non-root user)
Task 11 (integration) — depends on ALL previous tasks
```

**Parallel groups:**
- Wave 1: Tasks 1, 4, 6, 7, 8 (all independent)
- Wave 2: Tasks 2, 3, 5, 9, 10 (depend on wave 1)
- Wave 3: Task 11 (integration verification)
