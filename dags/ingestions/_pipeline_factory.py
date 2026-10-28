"""
Factory de Pipelines ELT para Opportunity Intelligence (IDCI)
==============================================================
Construye DAGs dedicados, desacoplados e independientes por institución,
manteniendo aislamiento de fallos, métricas aisladas y cronogramas propios,
pero reutilizando la arquitectura estandarizada de contenedores efímeros:

  1. Scraper Efímero (Scrapy / Playwright) -> Genera Stream JSON
  2. Rust Worker Efímero (Rust de alto rendimiento) -> Filtra + Tika Fan-Out + Persiste en RustFS S3
  3. Loader Efímero (Python / Psycopg2) -> Ingesta manifest a PostgreSQL Bronze.{institución}
  4. dbt Core Efímero (dbt run) -> Transforma y unifica en Silver Marts
  5. dbt Core Efímero (dbt test) -> Valida 41+ reglas de calidad e integridad referencial
  6. OpenMetadata Efímero (Lineage Validator) -> Publica y certifica linaje en OpenMetadata
"""

from datetime import datetime, timedelta
from typing import List, Optional
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


def build_funding_pipeline_dag(
    institution_id: str,
    institution_name: str,
    spider_name: str,
    target_url: str,
    schedule_interval: Optional[str] = "0 6 * * 1",
    start_date: datetime = datetime(2026, 1, 1),
    default_scrape_limit: int = 50,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> DAG:
    """
    Crea un DAG de Airflow altamente parametrizado y aislado para una institución específica.
    """
    dag_id = f"{institution_id.lower().replace('-', '_')}_funding_pipeline_dag"
    desc = (
        description
        or f"Pipeline ELT Dedicado para {institution_name}: Scrapy -> Rust Worker -> Apache Tika -> RustFS S3 -> Postgres Bronze -> dbt Silver -> OpenMetadata"
    )
    dag_tags = tags or [
        institution_id.lower(),
        "spiders",
        "rust_worker",
        "tika",
        "scraper",
        "loader",
        "s3",
        "rustfs",
        "bronze",
        "silver",
        "dbt",
        "openmetadata",
    ]

    dag = DAG(
        dag_id=dag_id,
        default_args=DEFAULT_ARGS,
        description=desc,
        schedule_interval=schedule_interval,
        start_date=start_date,
        catchup=False,
        tags=dag_tags,
        params={
            "target_url": Param(
                default=target_url,
                type="string",
                description=f"URL objetivo de convocatorias para {institution_name}.",
            ),
            "scrape_limit": Param(
                default=default_scrape_limit,
                type="integer",
                description="Límite máximo de páginas o convocatorias a extraer en esta ejecución.",
            ),
            "use_browser": Param(
                default=True,
                type="boolean",
                description="Utilizar ayudante Playwright Chromium Headless con evasión de bloqueos.",
            ),
            "download_binaries": Param(
                default=True,
                type="boolean",
                description="Descargar anexos oficiales (PDF, Word, Excel) para procesamiento en Apache Tika.",
            ),
        },
    )

    with dag:
        # ======================================================================
        # Task 1: Contenedor Efímero Scraper (Scrapy -> Stream JSON IPC)
        # ======================================================================
        task_scraper = BashOperator(
            task_id="run_ephemeral_scraper",
            bash_command=f"""
                set -e
                SPIDER="{spider_name}"
                INST_NAME="{institution_name}"
                TARGET_URL="{{{{ dag_run.conf.get('target_url', params.target_url) }}}}"
                SCRAPE_LIMIT="{{{{ dag_run.conf.get('scrape_limit', params.scrape_limit) }}}}"
                USE_BROWSER="{{{{ dag_run.conf.get('use_browser', params.use_browser) }}}}"
                DOWNLOAD_BINARIES="{{{{ dag_run.conf.get('download_binaries', params.download_binaries) }}}}"

                echo "=== [Task 1] Levantando Contenedor Efímero Scraper (Institución: '$INST_NAME' | Spider: '$SPIDER') ==="

                EXTRA_ARGS=()
                if [ -n "$TARGET_URL" ] && [ "$TARGET_URL" != "None" ]; then
                    echo "-> URL objetivo: $TARGET_URL"
                    EXTRA_ARGS+=(--url "$TARGET_URL")
                fi
                if [ -n "$INST_NAME" ] && [ "$INST_NAME" != "None" ]; then
                    EXTRA_ARGS+=(--institution "$INST_NAME")
                fi
                if [ "$USE_BROWSER" = "False" ] || [ "$USE_BROWSER" = "false" ]; then
                    echo "-> Playwright deshabilitado por configuración."
                    EXTRA_ARGS+=(--no-browser)
                fi
                if [ "$DOWNLOAD_BINARIES" = "False" ] || [ "$DOWNLOAD_BINARIES" = "false" ]; then
                    echo "-> Descarga de binarios deshabilitada por configuración."
                    EXTRA_ARGS+=(--no-binaries)
                fi

                STREAM_FILE="/tmp/{institution_id}_stream.json"
                rm -f "$STREAM_FILE"

                if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                    echo "-> Ejecutando idci_scraper:latest con --step stream..."
                    docker run --rm --network idci_network \\
                        idci_scraper:latest --step stream --spider "$SPIDER" --limit "$SCRAPE_LIMIT" "${{EXTRA_ARGS[@]}}" > "$STREAM_FILE"
                else
                    echo "-> Fallback local: ejecutando scraper.py directamente con --step stream..."
                    python3 /opt/airflow/extractor/scraper.py --step stream --spider "$SPIDER" --limit "$SCRAPE_LIMIT" "${{EXTRA_ARGS[@]}}" > "$STREAM_FILE"
                fi
                echo "-> Extracción finalizada. Stream generado en $STREAM_FILE ($(wc -c < "$STREAM_FILE") bytes)."
            """,
        )

        # ======================================================================
        # Task 2: Contenedor Efímero Rust Worker (Stream -> Tika Fan-Out -> RustFS S3)
        # ======================================================================
        task_rust_worker = BashOperator(
            task_id="run_ephemeral_rust_worker",
            bash_command=f"""
                set -e
                INST_NAME="{institution_name}"
                STREAM_FILE="/tmp/{institution_id}_stream.json"
                MANIFEST_FILE="/tmp/{institution_id}_manifest.json"
                rm -f "$MANIFEST_FILE"

                echo "=== [Task 2] Ejecutando Rust Worker de Alto Rendimiento (Stream -> Tika -> RustFS S3) ==="
                if [ ! -f "$STREAM_FILE" ] || [ ! -s "$STREAM_FILE" ]; then
                    echo "❌ Error: El archivo de stream $STREAM_FILE no existe o está vacío."
                    exit 1
                fi

                if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                    echo "-> Despachando idci_rust_worker:latest recibiendo stream por stdin..."
                    cat "$STREAM_FILE" | docker run -i --rm --network idci_network \\
                        -e S3_ENDPOINT_URL="http://rustfs:9000" \\
                        -e S3_ACCESS_KEY="rustfsadmin" \\
                        -e S3_SECRET_KEY="rustfsadmin2026" \\
                        -e S3_BUCKET="opportunity-intelligence" \\
                        -e TIKA_URL="http://tika:9998" \\
                        -e INSTITUTION_NAME="$INST_NAME" \\
                        idci_rust_worker:latest --input - > "$MANIFEST_FILE"
                else
                    echo "-> Fallback local: ejecutando binario idci_rust_worker directamente..."
                    cat "$STREAM_FILE" | /app/idci_rust_worker --input - > "$MANIFEST_FILE"
                fi

                echo "-> Rust Worker finalizado exitosamente. Manifest consolidado en $MANIFEST_FILE."
            """,
        )

        # ======================================================================
        # Task 3: Contenedor Efímero Loader (RustFS S3 -> PostgreSQL Bronze.{institución})
        # ======================================================================
        task_loader = BashOperator(
            task_id="run_ephemeral_loader",
            bash_command=f"""
                set -e
                SPIDER="{spider_name}"
                INST_NAME="{institution_name}"
                MANIFEST_FILE="/tmp/{institution_id}_manifest.json"

                echo "=== [Task 3] Levantando Contenedor Efímero Loader (Institución: '$INST_NAME') ==="

                EXTRA_ARGS=()
                if [ -n "$INST_NAME" ] && [ "$INST_NAME" != "None" ]; then
                    EXTRA_ARGS+=(--institution "$INST_NAME")
                fi

                # Extraer URI directa del batch manifest si está disponible
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
                    docker run --rm --network idci_network \\
                        -e POSTGRES_HOST="postgres" \\
                        -e POSTGRES_PORT="5432" \\
                        -e POSTGRES_USER="idci_admin" \\
                        -e POSTGRES_PASSWORD="secure_password_2026" \\
                        -e POSTGRES_DB="idci_analytics" \\
                        -e S3_ENDPOINT_URL="http://rustfs:9000" \\
                        -e S3_ACCESS_KEY="rustfsadmin" \\
                        -e S3_SECRET_KEY="rustfsadmin2026" \\
                        -e S3_BUCKET="opportunity-intelligence" \\
                        idci_loader:latest --step load --spider "$SPIDER" "${{EXTRA_ARGS[@]}}"
                else
                    echo "-> Fallback local: ejecutando loader directamente..."
                    POSTGRES_HOST="postgres" \\
                    POSTGRES_PORT="5432" \\
                    POSTGRES_USER="idci_admin" \\
                    POSTGRES_PASSWORD="secure_password_2026" \\
                    POSTGRES_DB="idci_analytics" \\
                    S3_ENDPOINT_URL="http://rustfs:9000" \\
                    S3_ACCESS_KEY="rustfsadmin" \\
                    S3_SECRET_KEY="rustfsadmin2026" \\
                    S3_BUCKET="opportunity-intelligence" \\
                    python3 /opt/airflow/extractor/scraper.py --step load --spider "$SPIDER" "${{EXTRA_ARGS[@]}}"
                fi
                echo "-> Contenedor Loader finalizado y destruido exitosamente."
            """,
        )

        # ======================================================================
        # Task 4: Contenedor Efímero dbt Core (Consolidación Dimensional Silver)
        # ======================================================================
        task_dbt_run = BashOperator(
            task_id="run_ephemeral_dbt_models",
            bash_command="""
                set -e
                echo "=== [Task 4] Ejecutando dbt Core (Consolidación Dimensional Silver) ==="
                if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                    echo "-> Ejecutando idci_dbt:latest (--rm)..."
                    docker run --rm --network idci_network idci_dbt:latest run --profiles-dir . --target docker
                else
                    echo "-> Fallback local: ejecutando dbt run directamente..."
                    export DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true
                    cd /opt/airflow/dbt
                    dbt run --profiles-dir . --target docker
                fi
                echo "-> Contenedor dbt run finalizado y destruido exitosamente."
            """,
        )

        # ======================================================================
        # Task 5: Contenedor Efímero dbt Core (Suite de Tests y Calidad)
        # ======================================================================
        task_dbt_test = BashOperator(
            task_id="run_ephemeral_dbt_tests",
            bash_command="""
                set -e
                echo "=== [Task 5] Ejecutando suite de calidad y validaciones dbt ==="
                if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                    echo "-> Ejecutando idci_dbt:latest test (--rm)..."
                    docker run --rm --network idci_network idci_dbt:latest test --profiles-dir . --target docker
                else
                    echo "-> Fallback local: ejecutando dbt test directamente..."
                    export DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true
                    cd /opt/airflow/dbt
                    dbt test --profiles-dir . --target docker
                fi
                echo "-> Contenedor dbt test finalizado y destruido exitosamente."
            """,
        )

        # ======================================================================
        # Task 6: Contenedor Efímero OpenMetadata (Validación & Envío de Linaje)
        # ======================================================================
        task_metadata = BashOperator(
            task_id="run_ephemeral_metadata",
            bash_command="""
                set -e
                echo "=== [Task 6] Publicando y validando Linaje y Metadatos en OpenMetadata ==="
                if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
                    echo "-> Ejecutando idci_metadata:latest (--rm)..."
                    docker run --rm --network idci_network \\
                        -e POSTGRES_HOST="postgres" \\
                        -e POSTGRES_PORT="5432" \\
                        -e POSTGRES_USER="idci_admin" \\
                        -e POSTGRES_PASSWORD="secure_password_2026" \\
                        -e POSTGRES_DB="idci_analytics" \\
                        -e OPENMETADATA_HOST="http://openmetadata:8585/api" \\
                        idci_metadata:latest
                else
                    echo "-> Fallback local: ejecutando lineage_validator.py directamente..."
                    POSTGRES_HOST="postgres" \\
                    POSTGRES_PORT="5432" \\
                    POSTGRES_USER="idci_admin" \\
                    POSTGRES_PASSWORD="secure_password_2026" \\
                    POSTGRES_DB="idci_analytics" \\
                    python3 /opt/airflow/openmetadata/lineage_validator.py
                fi
                echo "-> Contenedor Metadata finalizado y destruido exitosamente."
            """,
        )

        # Dependencias secuenciales estrictas de contenedores efímeros
        task_scraper >> task_rust_worker >> task_loader >> task_dbt_run >> task_dbt_test >> task_metadata

    return dag
