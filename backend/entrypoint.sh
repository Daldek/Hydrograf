#!/bin/bash
set -eo pipefail

# ---- Ensure writable temp directory (for transient data processing) ----
mkdir -p /tmp/hydrograf

# ---- Wait for the database and migrate it, when the container is given one ----
# Docker Compose gives the API and its one-off containers DATABASE_URL
# (docker-compose.yml). A script run with plain `docker run` and no database
# (scripts.write_instance_info, --help) starts at once instead of waiting for a host
# named db that is not there.
if [[ -n "${DATABASE_URL:-}" || -n "${POSTGRES_HOST:-}" ]]; then
    DB_HOST="${POSTGRES_HOST:-db}"
    DB_PORT="${POSTGRES_PORT:-5432}"
    DB_USER="${POSTGRES_USER:-hydro_user}"

    echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
    until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
        sleep 2
    done
    echo "Database is ready."

    echo "Running database migrations..."
    alembic upgrade head
    echo "Migrations complete."
fi

# ---- Start application ----
exec "$@"
