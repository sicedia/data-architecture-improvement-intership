#!/usr/bin/env bash
# ==============================================================================
# Entrypoint raíz para dbt Core (Redirige a scripts/local/run_dbt.sh)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/scripts/local/run_dbt.sh" "$@"
