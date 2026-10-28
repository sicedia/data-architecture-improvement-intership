#!/usr/bin/env python3
"""
IDCI Opportunity & Web Intelligence Extractor (Modular Lakehouse Engine)
========================================================================
Flujo desacoplado en dos etapas independientes (Data Lakehouse Pattern):
1. Extractor (Web -> RustFS S3): Ejecuta el Spider especializado IDCI
   con el nombre institucional configurado y almacena artefactos en RustFS S3.
2. Loader (RustFS S3 -> PostgreSQL Bronze): Lee el manifest del lote crudo
   directamente desde RustFS S3 y lo ingesta en la tabla Bronze correspondiente
   (bronze.idrc__funding_calls),
   preservando trazabilidad, hashing y metadatos de auditoría institucional.
"""

import os
import sys
import logging
import argparse
from typing import Dict, Any, Optional

# Añadir directorio actual al path para importar el paquete spiders
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spiders import get_spider, list_spiders, SPIDER_REGISTRY

# Configuración de logging estructurado (dirigido a stderr para mantener stdout limpio para streams)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("idci_scraper")


def extract_and_land_to_rustfs(
    spider_name: str = "idci",
    target_url: Optional[str] = None,
    institution_name: Optional[str] = None,
    limit: Optional[int] = None,
    s3_endpoint: str = "http://rustfs:9000",
    s3_access_key: str = "rustfsadmin",
    s3_secret_key: str = "rustfsadmin2026",
    bucket_name: str = "opportunity-intelligence",
    use_playwright: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Función 1: Web Scraping oficial -> RustFS S3 (Landing Zone Inmutable).
    Ejecuta el Spider especificado con soporte para Playwright Chromium headless,
    evasión de JavaScript y descarga de archivos binarios (PDFs, Word, etc.).
    """
    spider = get_spider(spider_name, target_url=target_url, institution_name=institution_name)
    spider.use_playwright = use_playwright
    inst_label = spider.institution_name or spider.source_system
    engine_label = "Playwright Chromium Headless" if use_playwright else "HTTP Standard"
    logger.info(
        f"=== [ETAPA 1/2] Extracción Web con Spider '{spider.name}' (Institución: {inst_label} | Motor: {engine_label}) hacia RustFS S3 ==="
    )
    records = spider.extract(limit=limit)

    return spider.land_to_rustfs(
        records=records,
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket_name=bucket_name,
        dry_run=dry_run,
    )


def load_rustfs_to_postgres_bronze(
    spider_name: str = "idci",
    institution_name: Optional[str] = None,
    s3_endpoint: str = "http://rustfs:9000",
    s3_access_key: str = "rustfsadmin",
    s3_secret_key: str = "rustfsadmin2026",
    bucket_name: str = "opportunity-intelligence",
    db_conn_str: str = "",
    batch_id: Optional[str] = None,
    batch_uri: Optional[str] = None,
) -> int:
    """
    Función 2: RustFS S3 (Landing Zone) -> PostgreSQL Bronze (Data Warehouse).
    Descarga el manifest del Spider y lo ingesta en su tabla Bronze correspondiente.
    """
    spider = get_spider(spider_name, institution_name=institution_name)
    logger.info(
        f"=== [ETAPA 2/2] Carga desde RustFS S3 hacia 'bronze.{spider.target_table}' "
        f"(Institución: {spider.institution_name or spider.source_system}) ==="
    )
    return spider.load_to_postgres(
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket_name=bucket_name,
        db_conn_str=db_conn_str,
        batch_id=batch_id,
        batch_uri=batch_uri,
    )


def main():
    available_spiders = list(SPIDER_REGISTRY.keys())
    parser = argparse.ArgumentParser(
        description="IDCI Modular Web Intelligence Scraper & Lakehouse Ingestion Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--spider",
        type=str,
        default=os.getenv("SPIDER_NAME", "idci"),
        help=f"Nombre de la araña a ejecutar: {available_spiders} (default: 'idci').",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=os.getenv("TARGET_URL", None),
        help="URL específica a scrapear.",
    )
    parser.add_argument(
        "--institution",
        "--institution-name",
        type=str,
        default=os.getenv("INSTITUTION_NAME", None),
        help="Nombre o sigla de la institución a scrapear (ej: CYTED, IDRC, Harvard).",
    )
    parser.add_argument(
        "--step",
        choices=["all", "extract", "load", "stream"],
        default="all",
        help="Etapa a ejecutar: 'extract' (Web -> RustFS S3), 'load' (RustFS S3 -> Postgres Bronze), 'stream' (Web -> stream para Rust Worker), o 'all' (ambas).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Ruta de archivo para guardar el stream JSON (en caso de no redirigir stdout).",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help="UUID del batch específico a cargar en Postgres (solo para --step load).",
    )
    parser.add_argument(
        "--batch-uri",
        type=str,
        default=None,
        help="URI S3 directa (s3://bucket/key) del manifest a cargar (solo para --step load).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Límite máximo de registros o páginas a scrapear.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecutar scraping en memoria sin escribir en RustFS S3 ni PostgreSQL.",
    )
    parser.add_argument(
        "--browser",
        dest="use_playwright",
        action="store_true",
        default=os.getenv("USE_PLAYWRIGHT", "true").lower() in ("true", "1", "yes"),
        help="Habilita el ayudante de navegación Playwright con Chromium en modo oculto (headless) (default: True).",
    )
    parser.add_argument(
        "--no-browser",
        dest="use_playwright",
        action="store_false",
        help="Deshabilita Playwright y utiliza el motor HTTP estándar.",
    )
    parser.add_argument(
        "--download-binaries",
        dest="download_binaries",
        action="store_true",
        default=True,
        help="Descarga automáticamente archivos binarios asociados (PDFs, Word, Excel, etc.) a RustFS S3 (default: True).",
    )
    parser.add_argument(
        "--no-binaries",
        dest="download_binaries",
        action="store_false",
        help="Omite la descarga de archivos binarios.",
    )
    parser.add_argument(
        "--list-spiders",
        action="store_true",
        help="Muestra las arañas disponibles con sus tablas destino y finaliza.",
    )
    args = parser.parse_args()

    # Opción para listar arañas disponibles
    if args.list_spiders:
        spiders_info = list_spiders()
        print("\n=== ARAÑAS DISPONIBLES EN IDCI ===")
        for key, info in spiders_info.items():
            print(f"\n🕷️  Spider: '{key}'")
            print(f"   Descripción : {info['description']}")
            print(f"   Tabla Bronze: {info['target_table']}")
            print(f"   Código PK   : {info['code_field']}")
            print(f"   URL Default : {info['default_url']}")
        print("\n")
        return

    spider_name = args.spider.lower().strip()
    if spider_name not in SPIDER_REGISTRY:
        raise ValueError(
            f"Spider desconocido: '{args.spider}'. Disponibles: {available_spiders}. Usa --list-spiders para más info."
        )

    # Variables de entorno con defaults
    s3_endpoint = os.getenv("S3_ENDPOINT_URL", "http://rustfs:9000")
    s3_access_key = os.getenv("S3_ACCESS_KEY", "rustfsadmin")
    s3_secret_key = os.getenv("S3_SECRET_KEY", "rustfsadmin2026")
    s3_bucket = os.getenv("S3_BUCKET", "opportunity-intelligence")

    db_host = os.getenv("POSTGRES_HOST", "postgres")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_user = os.getenv("POSTGRES_USER", "idci_admin")
    db_pass = os.getenv("POSTGRES_PASSWORD", "secure_password_2026")
    db_name = os.getenv("POSTGRES_DB", "idci_analytics")
    db_conn_str = f"host={db_host} port={db_port} user={db_user} password={db_pass} dbname={db_name}"

    limit = args.limit
    if limit is None and os.getenv("SCRAPE_LIMIT"):
        try:
            limit = int(os.getenv("SCRAPE_LIMIT"))
        except ValueError:
            limit = None

    institution = args.institution or os.getenv("INSTITUTION_NAME")

    logger.info(
        f"=== Pipeline IDCI - Spider: '{spider_name}' | Institución: '{institution or 'Auto'}' | "
        f"Paso: {args.step.upper()} | Límite: {limit} ==="
    )

    batch_meta = None

    # MODO STREAM: Web -> Stream JSON para Rust Worker (Scrapy extrae metadatos y binarios iniciales)
    if args.step == "stream":
        spider = get_spider(spider_name, target_url=args.url, institution_name=institution)
        spider.use_playwright = args.use_playwright
        inst_label = spider.institution_name or spider.source_system
        engine_label = "Playwright Chromium Headless" if args.use_playwright else "HTTP Standard"
        logger.info(
            f"=== [Modo Stream] Extracción Web con Spider '{spider.name}' ({inst_label} | {engine_label}) hacia Rust Worker ==="
        )
        records = spider.extract(limit=limit)

        import base64
        import json
        import uuid

        # Convertir bytes binarios a base64 para transmisión estructurada segura
        for rec in records:
            for b in rec.get("downloaded_binaries", []):
                if "raw_bytes" in b and b["raw_bytes"]:
                    b["raw_bytes_base64"] = base64.b64encode(b["raw_bytes"]).decode("ascii")
                    del b["raw_bytes"]

        batch_id = str(uuid.uuid4())
        envelope = {
            "batch_id": batch_id,
            "institution_name": institution or spider.institution_name or "idrc",
            "source_system": spider.source_system,
            "spider": spider.name,
            "target_table": getattr(spider, "target_table", None) or f"{spider.source_system}__funding_calls",
            "total_records": len(records),
            "records": records,
        }

        stream_json = json.dumps(envelope, ensure_ascii=False)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(stream_json)
            logger.info(f"Stream JSON escrito en {args.output} ({len(records)} registros)")
        else:
            print(stream_json)
        return

    # ETAPA 1: Web -> RustFS S3
    if args.step in ("extract", "all"):
        batch_meta = extract_and_land_to_rustfs(
            spider_name=spider_name,
            target_url=args.url,
            institution_name=institution,
            limit=limit,
            s3_endpoint=s3_endpoint,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
            bucket_name=s3_bucket,
            use_playwright=args.use_playwright,
            dry_run=args.dry_run,
        )

        if args.dry_run:
            logger.info("Dry run finalizado. Saliendo sin persistir.")
            return

    # ETAPA 2: RustFS S3 -> PostgreSQL Bronze
    if args.step in ("load", "all"):
        target_uri = args.batch_uri
        target_batch_id = args.batch_id
        if args.step == "all" and batch_meta:
            target_uri = batch_meta.get("batch_uri")
            target_batch_id = batch_meta.get("batch_id")

        load_rustfs_to_postgres_bronze(
            spider_name=spider_name,
            institution_name=institution,
            s3_endpoint=s3_endpoint,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
            bucket_name=s3_bucket,
            db_conn_str=db_conn_str,
            batch_id=target_batch_id,
            batch_uri=target_uri,
        )

    logger.info(f"=== Pipeline IDCI finalizado exitosamente para spider '{spider_name}' ===")


if __name__ == "__main__":
    main()
