#!/bin/sh
# Back up the database to deploy/backups/swasthyoid-<UTC time>.dump (pg_dump custom format).
# Keys (PII_KEY, DOCUMENT_KEY, EXTRACTION_KEY, ...) are NOT in the dump: keep them apart, or the backup cannot be read.
# Encrypted document originals live in the "documents" volume; back that up with the same timestamp.
set -eu
cd "$(dirname "$0")"
mkdir -p backups
out="backups/swasthyoid-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose -f docker-compose.yml --env-file .env exec -T postgres \
  pg_dump -U swasthyoid -d swasthyoid --format=custom --no-owner > "$out"
[ -s "$out" ] || { echo "backup failed: empty file" >&2; rm -f "$out"; exit 1; }
echo "wrote $out"
