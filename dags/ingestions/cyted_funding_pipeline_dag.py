"""
DAG Dedicado: CYTED Funding Opportunities Pipeline (Iberoamérica)
================================================================
Pipeline ELT dedicado exclusivamente para el Programa Iberoamericano
de Ciencia y Tecnología para el Desarrollo (CYTED).
Monitorea convocatorias de I+D, Redes Temáticas, Foros y Becas desde www.cyted.org.

Arquitectura Medallion Efímera:
  1. Scrapy / Playwright (CytedSpider / Chromium Headless) -> Stream JSON
  2. Rust Worker -> Apache Tika (Fan-Out) -> RustFS S3
  3. Loader -> PostgreSQL bronze.cyted__funding_calls
  4. dbt run & test -> PostgreSQL silver.* (Unificación dimensional multimoneda)
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


# Parámetros personalizados para CYTED
CYTED_CUSTOM_PARAMS = {
    "target_url": Param(
        default="https://www.cyted.org/",
        type="string",
        description="URL principal del portal del Programa CYTED.",
    ),
    "target_year": Param(
        default=2026,
        type="integer",
        description="Año de la convocatoria CYTED a procesar (ej: 2026).",
    ),
    "scrape_limit": Param(
        default=50,
        type="integer",
        description="Límite de líneas temáticas o páginas a extraer en esta ejecución.",
    ),
    "include_active_redes": Param(
        default=True,
        type="boolean",
        description="Extraer listado de redes activas ya adjudicadas (web_redes.php) como outcomes históricos.",
    ),
    "download_binaries": Param(
        default=True,
        type="boolean",
        description="Descargar bases oficiales en PDF y guías del solicitante (/assets/img/cyted/...).",
    ),
    "use_browser": Param(
        default=True,
        type="boolean",
        description="Utilizar Playwright Chromium Headless para renderizado y descarga de anexos.",
    ),
}

# Instancia explícita del DAG para Airflow Scheduler
dag: DAG = build_funding_pipeline_dag(
    institution_id="cyted",
    institution_name="CYTED",
    spider_name="cyted",
    target_url="https://www.cyted.org/",
    schedule_interval="0 8 1 * *",  # Mensual: el día 1 de cada mes a las 08:00 UTC
    start_date=datetime(2026, 1, 1),
    default_scrape_limit=50,
    description="Pipeline ELT Dedicado para CYTED (Iberoamérica): Redes temáticas, foros, becas y proyectos IBEROEKA.",
    tags=[
        "cyted",
        "iberoamerica",
        "funding",
        "monolith_php",
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
    custom_params=CYTED_CUSTOM_PARAMS,
    extra_env={
        "CYTED_TARGET_YEAR": "2026",
        "CYTED_INCLUDE_OUTCOMES": "true",
    },
)
