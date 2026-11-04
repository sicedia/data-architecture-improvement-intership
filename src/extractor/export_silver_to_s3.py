"""
Exportador de Capa Silver a RustFS S3 (Opportunity Intelligence)
================================================================
Extrae las tablas intermedias transformadas (_int) y dimensionales desde
PostgreSQL (esquema 'silver') y las persiste estructuradamente en RustFS S3:
  s3://opportunity-intelligence/silver/{institution}/{table_name}/year=YYYY/month=MM/data_{timestamp}.json
  s3://opportunity-intelligence/silver/{institution}/{table_name}/latest.json

Cumple con:
  - Particionado temporal compatible con Lakehouse / Athena / DuckDB.
  - Serialización robusta de tipos Postgres (UUID, Datetime, Decimal).
  - Manejo de incertidumbre y esquemas vacíos (graceful empty export).
  - idempotencia y actualización de 'latest.json' para consumo directo.
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any, List

import boto3
import botocore.client
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (silver_s3_exporter) %(message)s",
)
logger = logging.getLogger("silver_s3_exporter")


class CustomJsonEncoder(json.JSONEncoder):
    """Serializador JSON para tipos comunes de bases de datos relacionales."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


def get_s3_client(endpoint_url: str, access_key: str, secret_key: str):
    """Crea un cliente S3 configurado con addressing path-style para RustFS/MinIO."""
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=botocore.client.Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def ensure_bucket(s3_client, bucket_name: str):
    """Garantiza la existencia del bucket en RustFS S3."""
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except botocore.exceptions.ClientError:
        try:
            s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' creado exitosamente en RustFS S3.")
        except Exception as e:
            logger.warning(f"Aviso al verificar/crear bucket {bucket_name}: {e}")


def get_postgres_connection():
    """Obtiene una conexión a PostgreSQL usando variables de entorno estándar."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "idci_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "secure_password_2026"),
        dbname=os.getenv("POSTGRES_DB", "idci_analytics"),
        connect_timeout=10,
    )


INSTITUTION_TABLE_MAP = {
    "idrc": [
        "idrc_opportunities_int",
        "idrc_actors_int",
        "idrc_financial_conditions_int",
        "idrc_milestones_int",
        "idrc_documents_int",
    ],
    "cyted": [
        "cyted_opportunities_int",
        "cyted_actors_int",
        "cyted_financial_conditions_int",
        "cyted_milestones_int",
        "cyted_documents_int",
    ],
    "worldbank": [
        "worldbank_opportunities_int",
        "worldbank_actors_int",
        "worldbank_financial_conditions_int",
        "worldbank_milestones_int",
        "worldbank_documents_int",
    ],
    "ungm": [
        "ungm_opportunities_int",
        "ungm_actors_int",
        "ungm_financial_conditions_int",
        "ungm_milestones_int",
        "ungm_documents_int",
    ],
    "marts": [
        "fct_opportunities",
        "dim_opportunity_actors",
        "dim_opportunity_contexts",
        "dim_opportunity_financial_conditions",
        "dim_opportunity_milestones",
        "dim_opportunity_documents",
        "int_opportunities__unified",
    ],
}


def export_table_to_s3(
    pg_conn,
    s3_client,
    bucket_name: str,
    institution: str,
    table_name: str,
) -> Dict[str, Any]:
    """Extrae una tabla de silver, la serializa y la sube a RustFS S3."""
    logger.info(f"Extrayendo tabla silver.{table_name} para exportar a S3...")
    now = datetime.utcnow()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    timestamp_str = now.strftime("%Y%m%dT%H%M%SZ")

    with pg_conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Consultar si la tabla existe en silver
        cur.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'silver' AND table_name = %s
            );
            """,
            (table_name,),
        )
        exists = cur.fetchone()["exists"]
        if not exists:
            logger.warning(f"La tabla silver.{table_name} no existe en la base de datos. Saltando.")
            return {"table": table_name, "status": "skipped_not_found", "count": 0}

        cur.execute(f'SELECT * FROM "silver"."{table_name}";')
        rows = cur.fetchall()
        count = len(rows)

    records = [dict(r) for r in rows]
    json_bytes = json.dumps(records, cls=CustomJsonEncoder, indent=2).encode("utf-8")

    # Claves S3
    partition_key = f"silver/{institution}/{table_name}/year={year}/month={month}/data_{timestamp_str}.json"
    latest_key = f"silver/{institution}/{table_name}/latest.json"

    # Subir versión particionada y versión latest
    s3_client.put_object(
        Bucket=bucket_name,
        Key=partition_key,
        Body=json_bytes,
        ContentType="application/json",
        Metadata={
            "institution": institution,
            "table_name": table_name,
            "record_count": str(count),
            "exported_at": now.isoformat(),
        },
    )

    s3_client.put_object(
        Bucket=bucket_name,
        Key=latest_key,
        Body=json_bytes,
        ContentType="application/json",
        Metadata={
            "institution": institution,
            "table_name": table_name,
            "record_count": str(count),
            "exported_at": now.isoformat(),
        },
    )

    s3_uri = f"s3://{bucket_name}/{partition_key}"
    latest_uri = f"s3://{bucket_name}/{latest_key}"
    logger.info(f"✅ silver.{table_name} ({count} filas) -> {s3_uri} y {latest_uri}")

    return {
        "table": table_name,
        "count": count,
        "partition_uri": s3_uri,
        "latest_uri": latest_uri,
        "size_bytes": len(json_bytes),
    }


def export_silver_data(
    institution: str,
    include_marts: bool = False,
    s3_endpoint: str = "http://rustfs:9000",
    s3_access_key: str = "rustfsadmin",
    s3_secret_key: str = "rustfsadmin2026",
    s3_bucket: str = "opportunity-intelligence",
) -> List[Dict[str, Any]]:
    """Coordina la exportación de tablas Silver para una institución dada o 'all'."""
    institution = institution.lower().strip()
    s3_client = get_s3_client(s3_endpoint, s3_access_key, s3_secret_key)
    ensure_bucket(s3_client, s3_bucket)

    pg_conn = get_postgres_connection()

    institutions_to_process = []
    if institution == "all":
        institutions_to_process = ["idrc", "cyted", "worldbank", "ungm"]
    elif institution in INSTITUTION_TABLE_MAP:
        institutions_to_process = [institution]
    else:
        # Tratar de mapear o buscar por prefijo
        matched = [k for k in INSTITUTION_TABLE_MAP if k in institution]
        if matched:
            institutions_to_process = [matched[0]]
        else:
            raise ValueError(f"Institución '{institution}' no reconocida. Opciones: idrc, cyted, worldbank, ungm, all")

    results = []
    try:
        for inst in institutions_to_process:
            tables = INSTITUTION_TABLE_MAP.get(inst, [])
            logger.info(f"=== Exportando {len(tables)} tablas Silver para '{inst}' ===")
            for table in tables:
                res = export_table_to_s3(pg_conn, s3_client, s3_bucket, inst, table)
                results.append(res)

        if include_marts or institution == "all":
            logger.info("=== Exportando tablas de Marts Consolidados (Kimball) ===")
            for table in INSTITUTION_TABLE_MAP.get("marts", []):
                res = export_table_to_s3(pg_conn, s3_client, s3_bucket, "marts", table)
                results.append(res)

    finally:
        pg_conn.close()

    logger.info(f"=== Exportación Silver a S3 finalizada con éxito ({len(results)} tablas procesadas) ===")
    return results


def main():
    parser = argparse.ArgumentParser(description="Exportar tablas Silver de Postgres a RustFS S3")
    parser.add_argument(
        "--institution",
        type=str,
        default="all",
        help="Institución a exportar: idrc, cyted, worldbank, ungm, marts o all",
    )
    parser.add_argument(
        "--include-marts",
        action="store_true",
        help="Incluir exportación de los marts dimensionales de Kimball",
    )
    parser.add_argument(
        "--s3-endpoint",
        type=str,
        default=os.getenv("S3_ENDPOINT_URL", "http://rustfs:9000"),
        help="Endpoint de S3/RustFS",
    )
    parser.add_argument(
        "--s3-access-key",
        type=str,
        default=os.getenv("S3_ACCESS_KEY", "rustfsadmin"),
        help="Access key de S3",
    )
    parser.add_argument(
        "--s3-secret-key",
        type=str,
        default=os.getenv("S3_SECRET_KEY", "rustfsadmin2026"),
        help="Secret key de S3",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=os.getenv("S3_BUCKET", "opportunity-intelligence"),
        help="Nombre del bucket en S3",
    )

    args = parser.parse_args()

    export_silver_data(
        institution=args.institution,
        include_marts=args.include_marts,
        s3_endpoint=args.s3_endpoint,
        s3_access_key=args.s3_access_key,
        s3_secret_key=args.s3_secret_key,
        s3_bucket=args.bucket,
    )


if __name__ == "__main__":
    main()
