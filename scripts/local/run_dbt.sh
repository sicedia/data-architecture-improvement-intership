#!/usr/bin/env bash
# ==============================================================================
# Script Ejecutor Efímero de dbt Core
# Levanta el contenedor de dbt, aplica transformaciones/tests y se autodestruye (--rm)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Priorizar compose modular en deploy/local o fallback a la raíz
if [ -f "$REPO_ROOT/deploy/local/docker-compose.dbt.yml" ]; then
    COMPOSE_FILE="$REPO_ROOT/deploy/local/docker-compose.dbt.yml"
else
    COMPOSE_FILE="$REPO_ROOT/docker-compose.dbt.yml"
fi

echo "=== [1/2] Ejecutando modelos en contenedor efímero dbt (Staging & Silver Marts) ==="
docker compose -f "$COMPOSE_FILE" run --rm dbt run --profiles-dir . --target docker

echo "=== [2/2] Ejecutando suite de calidad de datos en contenedor efímero dbt ==="
docker compose -f "$COMPOSE_FILE" run --rm dbt test --profiles-dir . --target docker

echo "=== ✅ Finalizado: Los datos fueron transformados en PostgreSQL y el contenedor dbt fue destruido. ==="
