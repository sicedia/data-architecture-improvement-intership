#!/usr/bin/env bash
# Parse generated YAML DAGs with the real Airflow YAML importer (AIP-85) in a throw-away container.
# usage: scripts/check_airflow_dags.sh <dags-dir> [expected-dag-count]
# Fails on any import error or when the number of loaded DAGs differs from the expected count.
set -euo pipefail

dir="$(cd "${1:?usage: $0 <dags-dir> [expected-dag-count]}" && pwd)"
expected="${2:-$(find "$dir" -maxdepth 1 -name 'ingest__*.yml' | wc -l | tr -d ' ')}"
version="${AIRFLOW_VERSION:-3.4.0}"
image="${AIRFLOW_IMAGE:-apache/airflow:${version}-python${AIRFLOW_PYTHON:-3.12}}"

docker run --rm --entrypoint bash \
  -v "$dir:/opt/airflow/dags:ro" \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=False \
  -e 'AIRFLOW__DAG_PROCESSOR__DAG_IMPORTER_CONFIGS=[{"classpath": "airflow.sdk.importers.yaml_importer.YamlDagImporter"}]' \
  -e EXPECTED="$expected" \
  "$image" -c '
    set -e
    airflow db migrate >/dev/null 2>&1
    airflow dags reserialize >/tmp/reserialize.log 2>&1 || { cat /tmp/reserialize.log; airflow dags list-import-errors; exit 1; }
    errors="$(airflow dags list-import-errors 2>&1)"
    case "$errors" in *"No data found"*) ;; *) echo "$errors"; exit 1;; esac
    count="$(airflow dags list -o json 2>/dev/null | python -c "import json,sys; print(len(json.load(sys.stdin)))")"
    echo "airflow '"$version"' loaded $count DAGs (expected $EXPECTED)"
    [ "$count" = "$EXPECTED" ]
  '
