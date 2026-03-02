#!/bin/bash
set -eo pipefail

# ---- Ensure writable temp directory (for transient data processing) ----
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
