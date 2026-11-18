#!/bin/sh
# Restore a dump from backup.sh, REPLACING the current database. Usage: deploy/restore.sh <file.dump> --yes
# Stop the API and workers first so nothing writes during the restore; start them again afterwards.
set -eu
cd "$(dirname "$0")"
file="${1:-}"
[ -f "$file" ] || { echo "usage: restore.sh <file.dump> --yes" >&2; exit 2; }
[ "${2:-}" = "--yes" ] || { echo "this replaces the database; run again with --yes" >&2; exit 2; }
compose="docker compose -f docker-compose.yml --env-file .env"
$compose stop api worker-extract worker-safety worker-notify
$compose exec -T postgres pg_restore -U swasthyoid -d swasthyoid --clean --if-exists --no-owner --single-transaction < "$file"
$compose start api worker-extract worker-safety worker-notify
echo "restored $file"
