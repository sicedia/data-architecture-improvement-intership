"""
DAG Dedicado: IDRC Funding Opportunities Pipeline (Canadá)
===========================================================
Pipeline ELT dedicado exclusivamente para el International Development Research Centre (IDRC).
Monitorea convocatorias globales de investigación y desarrollo desde el portal oficial (idrc-crdi.ca/en/funding).

Arquitectura Medallion Efímera:
  1. Scrapy / Playwright (IDCISpider / Chromium Headless) -> Stream JSON
  2. Rust Worker -> Apache Tika (Fan-Out) -> RustFS S3
  3. Loader -> PostgreSQL bronze.idrc__funding_calls
  4. dbt run & test -> PostgreSQL silver.* (Consolidación dimensional y tests)
  5. Silver S3 Exporter -> Persistencia en RustFS S3
  6. OpenMetadata -> Certificación de linaje y gobernanza
"""

import os
import sys
from datetime import datetime
from airflow import DAG
from airflow.models.param import Param

# Asegurar importación limpia desde el directorio dags
DAGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DAGS_DIR not in sys.path:
    sys.path.insert(0, DAGS_DIR)

from ingestions._pipeline_factory import build_funding_pipeline_dag

# Parámetros personalizados para IDRC
IDRC_CUSTOM_PARAMS = {
    "target_url": Param(
        default="https://idrc-crdi.ca/en/funding",
        type="string",
        description="URL principal de convocatorias IDRC (incluye Open calls y Closed calls).",
    ),
    "scrape_limit": Param(
        default=50,
        type="integer",
        description="Límite de convocatorias a extraer en esta ejecución.",
    ),
    "include_closed_calls": Param(
        default=True,
        type="boolean",
        description="Regla de oro: No eliminar convocatorias cerradas. Extraer histórico de Closed calls.",
    ),
    "extract_faqs_and_updates": Param(
        default=True,
        type="boolean",
        description="Extraer subpáginas FAQ y notas de versión como evidencia de actualización.",
    ),
    "download_binaries": Param(
        default=True,
        type="boolean",
        description="Descargar anexos oficiales (Detailed call PDF, presupuesto Excel) hacia RustFS S3.",
    ),
    "use_browser": Param(
        default=True,
        type="boolean",
        description="Utilizar Playwright Chromium Headless para evasión de bloqueos y renderizado Drupal SSR.",
    ),
}

# Instancia explícita del DAG para Airflow Scheduler
dag: DAG = build_funding_pipeline_dag(
    institution_id="idrc",
    institution_name="IDRC",
    spider_name="idci",
    target_url="https://idrc-crdi.ca/en/funding",
    schedule_interval="0 6 * * 1",  # Semanal: cada lunes a las 06:00 UTC
    start_date=datetime(2026, 1, 1),
    default_scrape_limit=50,
    description="Pipeline ELT Dedicado para IDRC (Canadá): Convocatorias globales, extracción Drupal SSR, Tika y linaje OpenMetadata.",
    tags=[
        "idrc",
        "canada",
        "funding",
        "drupal_ssr",
        "rust_worker",
        "tika",
        "scraper",
        "loader",
        "s3",
        "bronze",
        "silver",
        "dbt",
        "openmetadata",
    ],
    custom_params=IDRC_CUSTOM_PARAMS,
    extra_env={
        "IDRC_INCLUDE_CLOSED": "true",
        "IDRC_EXTRACT_FAQS": "true",
    },
)
