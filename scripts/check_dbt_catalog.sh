#!/usr/bin/env bash
# Generate bronze tables and dbt models for EVERY contract of configs/contracts and `dbt build` them against
# a throw-away database, so the generated SQL (DDL, casts, quoted identifiers, tests) is proven
# valid, not just parsed.
# Needs the warehouse stack (make infra-up). usage: scripts/check_dbt_catalog.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . .env; set +a
elif [ -f infra/.env ]; then
  set -a; . infra/.env; set +a
fi
version="${DBT_CORE_VERSION:-1.12.3}"
db="dbt_check"
container="scrapagents-postgres"
if ! docker ps --format '{{.Names}}' | grep -q "^scrapagents-postgres$"; then
  container="scrapagents-warehouse-postgres-1"
fi
psql() { docker exec -i "$container" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"; }

psql -d postgres -qc "DROP DATABASE IF EXISTS $db WITH (FORCE)" -c "CREATE DATABASE $db"
psql -d "$db" -q < infra/warehouse/init.sql

work="build/dbt_catalog"
rm -rf "$work" && mkdir -p "$work/models"
cp -R dbt/macros dbt/profiles.yml dbt/dbt_project.yml "$work/"

catalog=()
for f in configs/contracts/*/*.yml; do
  case "$(basename "$(dirname "$f")")" in _*) continue;; esac
  catalog+=(--catalog "$(basename "$(dirname "$f")")/$(basename "$f" .yml)")
done
.venv/bin/python -m scrapagents.cli generate-dbt --out "$work" "${catalog[@]}"
# The typed bronze tables the runtime would load, one per contract (same generator as production).
.venv/bin/python -m scrapagents.cli generate-bronze --out "$work/bronze" "${catalog[@]}"
./scripts/apply_bronze.sh "$work/bronze/tables.sql" "$db"

docker run --rm --network scrapagents_net \
  -v "$PWD/$work:/dbt:ro" -w /dbt \
  -e DBT_HOST=postgres -e DBT_USER="$POSTGRES_USER" -e DBT_PASSWORD="$POSTGRES_PASSWORD" \
  -e DBT_DBNAME="$db" -e DBT_PROFILES_DIR=/dbt -e DBT_TARGET_PATH=/tmp/dbt/target \
  -e DBT_LOG_PATH=/tmp/dbt/logs \
  "scrapagents-dbt:$version" build 2>&1 | tail -n 4

psql -d postgres -qc "DROP DATABASE IF EXISTS $db WITH (FORCE)"
