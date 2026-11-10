#!/usr/bin/env bash
# Apply generated bronze DDL (idempotent) to a database of the running warehouse stack.
# usage: scripts/apply_bronze.sh <tables.sql> [database]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . .env; set +a
elif [ -f infra/.env ]; then
  set -a; . infra/.env; set +a
fi
sql="${1:?usage: apply_bronze.sh <tables.sql> [database]}"
db="${2:-$POSTGRES_DB}"
if [ -n "${POSTGRES_CONTAINER:-}" ]; then
  container="$POSTGRES_CONTAINER"
elif docker ps --format '{{.Names}}' | grep -q "^scrapagents-postgres$"; then
  container="scrapagents-postgres"
else
  container="scrapagents-warehouse-postgres-1"
fi

for _ in $(seq 1 30); do
  docker exec "$container" pg_isready -q -U "$POSTGRES_USER" -d "$db" && break
  sleep 2
done
docker exec -i "$container" psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$db" < "$sql"
echo "applied $sql to $db"
