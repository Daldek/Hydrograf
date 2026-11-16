#!/usr/bin/env bash
# Compose of the green (staging) stack of the store migration, docs/plans/2026-11-02-store-migration.md.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(git rev-parse --abbrev-ref HEAD)" == feature/store-migration ]] || { echo "not the store worktree" >&2; exit 1; }
exec docker compose -p hydrograf-staging -f docker-compose.yml -f docker-compose.staging.yml --env-file .env.staging "$@"
