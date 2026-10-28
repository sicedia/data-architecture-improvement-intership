"""
DAG Dedicado: CYTED Funding Opportunities Pipeline (Iberoamérica)
================================================================
Pipeline ELT dedicado exclusivamente para el Programa Iberoamericano
de Ciencia y Tecnología para el Desarrollo (CYTED).

Instrumentos monitoreados:
  - Convocatoria Redes Temáticas (idm=229)
  - Proyectos Estratégicos (idm=217)
  - Foros CYTED-IBEROEKA (idm=219)
  - Proyectos de Innovación IBEROEKA (idm=220)
  - Becas a Emprendedores (idm=221)
  - Convocatorias anunciadas en Noticias (noticias.php)

Arquitectura Medallion Efímera:
  1. Scrapy (CytedSpider / Chromium Headless) -> Stream JSON (14+ binarios)
  2. Rust Worker -> Apache Tika (Fan-Out) -> RustFS S3
  3. Loader -> PostgreSQL bronze.cyted__funding_calls
  4. dbt run & test -> PostgreSQL silver.* (unificación multimoneda y dimensiones)
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
    institution_id="cyted",
    institution_name="CYTED",
    spider_name="cyted",
    target_url="https://www.cyted.org/",
    schedule_interval="0 8 1 * *",  # Mensual: el día 1 de cada mes a las 08:00 UTC
    start_date=datetime(2026, 1, 1),
    default_scrape_limit=50,
    description="Pipeline ELT Dedicado para CYTED (Iberoamérica): Redes temáticas, foros, becas y proyectos IBEROEKA.",
    tags=["cyted", "iberoamerica", "funding", "rust_worker", "tika", "scraper", "loader", "s3", "bronze", "silver", "dbt", "openmetadata"],
)
