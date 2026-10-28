"""
DAG Dedicado: World Bank Procurement Pipeline (Banco Mundial API)
==================================================================
Pipeline ELT dedicado exclusivamente para el Banco Mundial (World Bank Group).
Consulta la API REST oficial de Procurement Notices (search.worldbank.org/api/v2/procnotices)
sin requerir navegación de navegador, mapea el esquema estricto de 7 dimensiones
de 'informacion.md', y persiste en bronze.worldbank__procurement.

Estructura de Tareas Efímeras:
  1. run_scraper_api     -> Scrapy/Requests consulta la API y emite Stream JSON IPC
  2. run_rust_worker     -> Rust Worker valida esquemas, Fan-Out Tika y persiste en RustFS S3
  3. run_loader_postgres -> Carga atómica a PostgreSQL bronze.worldbank__procurement
  4. run_dbt_models      -> dbt Core run & test poblando Silver Marts (fct_*, dim_*)
  5. run_metadata_sync   -> Certificación de linaje en OpenMetadata 1.4.2
"""

import os
import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.models.param import Param
from airflow.operators.bash import BashOperator

DEFAULT_ARGS = {
    "owner": "idci_analytics",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

API_DEFAULT_URL = (
    "https://search.worldbank.org/api/v2/procnotices"
    "?format=json&rows=50&apilang=en&srce=both&srt=submission_date%20desc,id%20asc"
)

# Instancia explícita del DAG para Airflow Scheduler
dag: DAG = DAG(
    dag_id="worldbank_procurement_pipeline_dag",
    default_args=DEFAULT_ARGS,
    description="Pipeline ELT Dedicado para Banco Mundial: API REST -> Rust Worker -> Apache Tika -> RustFS S3 -> Postgres Bronze -> dbt Silver -> OpenMetadata",
    schedule_interval="0 7 * * *",  # Diario a las 07:00 UTC
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["worldbank", "api", "procurement", "tenders", "rust_worker", "tika", "bronze", "silver", "dbt", "openmetadata"],
    params={
        "target_url": Param(
            default=API_DEFAULT_URL,
            type="string",
            description="Endpoint REST oficial de Procurement Notices del Banco Mundial.",
        ),
        "scrape_limit": Param(
            default=50,
            type="integer",
            description="Límite máximo de avisos de licitación a consultar desde la API.",
        ),
        "download_binaries": Param(
            default=True,
            type="boolean",
            description="Descargar anexos (pliegos de licitación, términos de referencia) para análisis en Apache Tika.",
        ),
    },
)

with dag:
    # ==========================================================================
    # Tarea 1 (run_scraper_api): Contenedor Scrapy efímero que consulta la API
    # ==========================================================================
    run_scraper_api = BashOperator(
        task_id="run_scraper_api",
        bash_command="""
            set -e
            SPIDER="worldbank"
            INST_NAME="World Bank"
            TARGET_URL="{{ dag_run.conf.get('target_url', params.target_url) }}"
            SCRAPE_LIMIT="{{ dag_run.conf.get('scrape_limit', params.scrape_limit) }}"
            DOWNLOAD_BINARIES="{{ dag_run.conf.get('download_binaries', params.download_binaries) }}"

            echo "=== [Tarea 1: run_scraper_api] Consultando API REST del Banco Mundial ==="
            echo "-> URL Endpoint: $TARGET_URL"
            echo "-> Límite registros: $SCRAPE_LIMIT"

            EXTRA_ARGS=(--no-browser)
            if [ -n "$TARGET_URL" ] && [ "$TARGET_URL" != "None" ]; then
                EXTRA_ARGS+=(--url "$TARGET_URL")
            fi
            if [ -n "$INST_NAME" ]; then
                EXTRA_ARGS+=(--institution "$INST_NAME")
            fi
            if [ "$DOWNLOAD_BINARIES" = "False" ] || [ "$DOWNLOAD_BINARIES" = "false" ]; then
                EXTRA_ARGS+=(--no-binaries)
            fi

            STREAM_FILE="/tmp/worldbank_stream.json"
            rm -f "$STREAM_FILE"

            if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                echo "-> Ejecutando idci_scraper:latest (API direct GET) en modo stream..."
                docker run --rm --network idci_network \
                    idci_scraper:latest --step stream --spider "$SPIDER" --limit "$SCRAPE_LIMIT" "${EXTRA_ARGS[@]}" > "$STREAM_FILE"
            else
                echo "-> Fallback local: ejecutando scraper.py directamente..."
                python3 /opt/airflow/extractor/scraper.py --step stream --spider "$SPIDER" --limit "$SCRAPE_LIMIT" "${EXTRA_ARGS[@]}" > "$STREAM_FILE"
            fi

            echo "-> Extracción API finalizada exitosamente. Stream JSON en $STREAM_FILE ($(wc -c < "$STREAM_FILE") bytes)."
        """,
    )

    # ==========================================================================
    # Tarea 2 (run_rust_worker): Valida esquemas, invoca Tika y genera manifiesto S3
    # ==========================================================================
    run_rust_worker = BashOperator(
        task_id="run_rust_worker",
        bash_command="""
            set -e
            INST_NAME="World Bank"
            STREAM_FILE="/tmp/worldbank_stream.json"
            MANIFEST_FILE="/tmp/worldbank_manifest.json"
            rm -f "$MANIFEST_FILE"

            echo "=== [Tarea 2: run_rust_worker] Ejecutando Rust Worker (Stream -> Tika -> RustFS S3) ==="
            if [ ! -f "$STREAM_FILE" ] || [ ! -s "$STREAM_FILE" ]; then
                echo "❌ Error: El archivo de stream $STREAM_FILE no existe o está vacío."
                exit 1
            fi

            if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                echo "-> Despachando idci_rust_worker:latest recibiendo stream por stdin..."
                cat "$STREAM_FILE" | docker run -i --rm --network idci_network \
                    -e S3_ENDPOINT_URL="http://rustfs:9000" \
                    -e S3_ACCESS_KEY="rustfsadmin" \
                    -e S3_SECRET_KEY="rustfsadmin2026" \
                    -e S3_BUCKET="opportunity-intelligence" \
                    -e TIKA_URL="http://tika:9998" \
                    -e INSTITUTION_NAME="$INST_NAME" \
                    idci_rust_worker:latest --input - > "$MANIFEST_FILE"
            else
                echo "-> Fallback local: ejecutando binario idci_rust_worker directamente..."
                cat "$STREAM_FILE" | /app/idci_rust_worker --input - > "$MANIFEST_FILE"
            fi

            echo "-> Rust Worker finalizado exitosamente. Manifest generado en $MANIFEST_FILE."
        """,
    )

    # ==========================================================================
    # Tarea 3 (run_loader_postgres): Ingesta en Bronze (bronze.worldbank__procurement)
    # ==========================================================================
    run_loader_postgres = BashOperator(
        task_id="run_loader_postgres",
        bash_command="""
            set -e
            SPIDER="worldbank"
            INST_NAME="World Bank"
            MANIFEST_FILE="/tmp/worldbank_manifest.json"

            echo "=== [Tarea 3: run_loader_postgres] Cargando lote validado a bronze.worldbank__procurement ==="

            EXTRA_ARGS=(--institution "$INST_NAME")
            BATCH_URI=""
            if [ -f "$MANIFEST_FILE" ]; then
                BATCH_URI=$(python3 -c "import json; print(json.load(open('$MANIFEST_FILE')).get('batch_uri', ''))" 2>/dev/null || echo "")
            fi
            if [ -n "$BATCH_URI" ]; then
                echo "-> Cargando manifest específico desde S3: $BATCH_URI"
                EXTRA_ARGS+=(--batch-uri "$BATCH_URI")
            fi

            if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                echo "-> Ejecutando idci_loader:latest (--rm)..."
                docker run --rm --network idci_network \
                    -e POSTGRES_HOST="postgres" \
                    -e POSTGRES_PORT="5432" \
                    -e POSTGRES_USER="idci_admin" \
                    -e POSTGRES_PASSWORD="secure_password_2026" \
                    -e POSTGRES_DB="idci_analytics" \
                    -e S3_ENDPOINT_URL="http://rustfs:9000" \
                    -e S3_ACCESS_KEY="rustfsadmin" \
                    -e S3_SECRET_KEY="rustfsadmin2026" \
                    -e S3_BUCKET="opportunity-intelligence" \
                    idci_loader:latest --step load --spider "$SPIDER" "${EXTRA_ARGS[@]}"
            else
                echo "-> Fallback local: ejecutando loader directamente..."
                POSTGRES_HOST="postgres" \
                POSTGRES_PORT="5432" \
                POSTGRES_USER="idci_admin" \
                POSTGRES_PASSWORD="secure_password_2026" \
                POSTGRES_DB="idci_analytics" \
                S3_ENDPOINT_URL="http://rustfs:9000" \
                S3_ACCESS_KEY="rustfsadmin" \
                S3_SECRET_KEY="rustfsadmin2026" \
                S3_BUCKET="opportunity-intelligence" \
                python3 /opt/airflow/extractor/scraper.py --step load --spider "$SPIDER" "${EXTRA_ARGS[@]}"
            fi

            echo "-> Contenedor Loader finalizado exitosamente."
        """,
    )

    # ==========================================================================
    # Tarea 4 (run_dbt_models): Transforma y puebla las tablas Silver con dbt Core
    # ==========================================================================
    run_dbt_models = BashOperator(
        task_id="run_dbt_models",
        bash_command="""
            set -e
            echo "=== [Tarea 4: run_dbt_models] Ejecutando dbt Core (Consolidación Silver Marts & Tests) ==="
            if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                echo "-> Ejecutando idci_dbt:latest run y test..."
                docker run --rm --network idci_network idci_dbt:latest run --profiles-dir . --target docker
                docker run --rm --network idci_network idci_dbt:latest test --profiles-dir . --target docker
            else
                echo "-> Fallback local: ejecutando dbt directamente..."
                export DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true
                cd /opt/airflow/dbt
                dbt run --profiles-dir . --target docker
                dbt test --profiles-dir . --target docker
            fi
            echo "-> dbt Core finalizado y verificado con 45+ pruebas de calidad."
        """,
    )

    # ==========================================================================
    # Tarea 5 (run_metadata_sync): Registra el linaje y actualización en OpenMetadata
    # ==========================================================================
    run_metadata_sync = BashOperator(
        task_id="run_metadata_sync",
        bash_command="""
            set -e
            echo "=== [Tarea 5: run_metadata_sync] Certificando Linaje y Gobierno en OpenMetadata ==="
            if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                echo "-> Ejecutando idci_metadata:latest (--rm)..."
                docker run --rm --network idci_network \
                    -e POSTGRES_HOST="postgres" \
                    -e POSTGRES_PORT="5432" \
                    -e POSTGRES_USER="idci_admin" \
                    -e POSTGRES_PASSWORD="secure_password_2026" \
                    -e POSTGRES_DB="idci_analytics" \
                    -e OPENMETADATA_HOST="http://openmetadata:8585/api" \
                    idci_metadata:latest
            else
                echo "-> Fallback local: ejecutando lineage_validator.py directamente..."
                POSTGRES_HOST="postgres" \
                POSTGRES_PORT="5432" \
                POSTGRES_USER="idci_admin" \
                POSTGRES_PASSWORD="secure_password_2026" \
                POSTGRES_DB="idci_analytics" \
                python3 /opt/airflow/openmetadata/lineage_validator.py
            fi
            echo "-> Linaje registrado y validado en OpenMetadata exitosamente."
        """,
    )

    # Dependencias secuenciales estrictas de contenedores efímeros
    run_scraper_api >> run_rust_worker >> run_loader_postgres >> run_dbt_models >> run_metadata_sync
