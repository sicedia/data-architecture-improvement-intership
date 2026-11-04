"""
DAG Dedicado: UN Global Marketplace (UNGM) Procurement Pipeline
================================================================
Pipeline ELT dedicado exclusivamente para el Mercado Global de las Naciones Unidas (UNGM).
Implementa una estrategia de Scraper Híbrido:
  - Endpoints AJAX internos (POST /Public/Notice/Search) para listado paginado ligero sin emulador pesado.
  - Extracción HTML detallada (GET /Public/Notice/{notice_id}) para pestañas General, Documents, Contacts.
  - Descarga de pliegos y términos de referencia (DownloadDocument) a RustFS S3.
  - Catálogos REST auxiliares (/API/NoticeTypes, /API/RegistrationLevels) para dimensionalidad Silver.

Arquitectura Medallion Efímera:
  1. Scraper Efímero (Scrapy / AJAX Requests) -> Stream JSON IPC
  2. Rust Worker -> Apache Tika (Fan-Out) -> RustFS S3
  3. Loader -> PostgreSQL bronze.ungm__notices
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

# Parámetros personalizados para UNGM
UNGM_CUSTOM_PARAMS = {
    "target_url": Param(
        default="https://www.ungm.org/Public/Notice",
        type="string",
        description="URL principal del portal de avisos de contrataciones de la ONU.",
    ),
    "scrape_limit": Param(
        default=100,
        type="integer",
        description="Límite máximo de avisos a consultar en esta ejecución.",
    ),
    "only_active": Param(
        default=False,
        type="boolean",
        description="Filtrar solo oportunidades activas. Si es False, ingesta también cerradas para histórico.",
    ),
    "download_binaries": Param(
        default=True,
        type="boolean",
        description="Descargar anexos oficiales (ToR, Request for Proposals en PDF) hacia RustFS S3.",
    ),
    "use_browser": Param(
        default=False,
        type="boolean",
        description="Deshabilitado por defecto para usar consultas HTTP AJAX directas y eficientes.",
    ),
}

# Instancia explícita del DAG para Airflow Scheduler
dag: DAG = build_funding_pipeline_dag(
    institution_id="ungm",
    institution_name="UN Global Marketplace (UNGM)",
    spider_name="idci",
    target_url="https://www.ungm.org/Public/Notice",
    schedule_interval="0 5 * * *",  # Diario a las 05:00 UTC
    start_date=datetime(2026, 1, 1),
    default_scrape_limit=100,
    description="Pipeline ELT Dedicado para UNGM (Naciones Unidas): Scraper Híbrido AJAX, Tika Fan-Out, RustFS S3, Postgres Bronze, dbt Silver y OpenMetadata.",
    tags=[
        "ungm",
        "united_nations",
        "procurement",
        "ajax_scraper",
        "tenders",
        "rust_worker",
        "tika",
        "bronze",
        "silver",
        "dbt",
        "openmetadata",
    ],
    custom_params=UNGM_CUSTOM_PARAMS,
    extra_env={
        "UNGM_SEARCH_ENDPOINT": "https://www.ungm.org/Public/Notice/Search",
        "UNGM_ACTIVE_ONLY": "false",
    },
)
