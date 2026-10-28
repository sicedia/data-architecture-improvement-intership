"""
DAG Dedicado: IDRC Funding Opportunities Pipeline (Canadá)
===========================================================
Pipeline ELT dedicado exclusivamente para el International Development Research Centre (IDRC).

Arquitectura Medallion Efímera:
  1. Scrapy (IDCISpider / Chromium Headless) -> Stream JSON
  2. Rust Worker -> Apache Tika (Fan-Out) -> RustFS S3
  3. Loader -> PostgreSQL bronze.idrc__funding_calls
  4. dbt run & test -> PostgreSQL silver.*
  5. OpenMetadata -> Linaje certificado
"""

import os
import sys
from datetime import datetime
from airflow import DAG

# Asegurar importación limpia desde el directorio dags
DAGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DAGS_DIR not in sys.path:
    sys.path.insert(0, DAGS_DIR)

from ingestions._pipeline_factory import build_funding_pipeline_dag

# Instancia explícita del DAG para Airflow Scheduler
dag: DAG = build_funding_pipeline_dag(
    institution_id="idrc",
    institution_name="IDRC",
    spider_name="idci",
    target_url="https://idrc-crdi.ca/en/funding",
    schedule_interval="0 6 * * 1",  # Semanal: cada lunes a las 06:00 UTC
    start_date=datetime(2026, 1, 1),
    default_scrape_limit=50,
    description="Pipeline ELT Dedicado para IDRC (Canadá): Convocatorias globales de investigación y desarrollo.",
    tags=["idrc", "canada", "funding", "rust_worker", "tika", "scraper", "loader", "s3", "bronze", "silver", "dbt", "openmetadata"],
)
