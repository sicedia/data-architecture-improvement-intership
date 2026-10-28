#!/usr/bin/env python3
"""
Base Spider & Lakehouse Ingestion Engine
========================================
Define la interfaz abstracta 'BaseSpider' y las operaciones estándar del Data Lakehouse
para aterrizar artefactos crudos en RustFS (S3) y cargarlos en PostgreSQL Bronze.
Soporta creación dinámica de tablas Bronze por nombre institucional (ej: bronze.ukri,
bronze.cyted, bronze.opportunity), subida concurrente a S3 y sanitización estricta.
"""

import abc
import os
import re
import sys
import json
import uuid
import hashlib
import logging
import urllib.request
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from .browser_helper import PlaywrightNavigator, BINARY_EXTENSIONS

logger = logging.getLogger("spider_engine")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BINARY_EXTENSIONS = (
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".rar", ".7z",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".avi", ".mov", ".mp3", ".wav", ".ogg",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".exe", ".bin", ".iso", ".dmg",
)


def get_s3_client(s3_endpoint: str, s3_access_key: str, s3_secret_key: str):
    """Inicializa y retorna el cliente boto3 configurado para RustFS S3."""
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 5, "mode": "standard"},
            max_pool_connections=25,
        ),
    )


def sanitize_str(text: Optional[str]) -> str:
    """Elimina caracteres nulos incompatibles con PostgreSQL (\\u0000 / \\x00)."""
    if not text:
        return ""
    return text.replace("\x00", "").replace("\u0000", "")


def clean_text(html_fragment: str) -> str:
    """Elimina etiquetas HTML, normaliza espacios en blanco y filtra caracteres nulos."""
    if not html_fragment:
        return ""
    text = re.sub(r"<[^>]+>", " ", html_fragment)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = sanitize_str(text)
    return re.sub(r"\s+", " ", text).strip()


class BaseSpider(abc.ABC):
    """
    Clase base para todos los spiders del proyecto.
    Define metadatos, ciclo de vida de scraping y métodos de persistencia S3 + Bronze.
    """

    name: str = "base"
    description: str = "Spider base abstracto"
    source_system: str = "opportunity"
    entity_name: str = "funding_opportunities"
    target_table: str = "opportunity"
    code_field: str = "call_code"
    default_url: str = ""

    def __init__(self, target_url: Optional[str] = None, institution_name: Optional[str] = None):
        self.target_url = target_url or self.default_url
        self.institution_name = (institution_name or "").strip()
        if self.institution_name and self.target_table == "opportunity":
            clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", self.institution_name.lower().strip()).strip("_")
            if clean_slug:
                self.source_system = clean_slug
                self.target_table = f"{clean_slug}__funding_calls"
        self.use_playwright: bool = os.getenv("USE_PLAYWRIGHT", "true").lower() in ("true", "1", "yes")
        self._navigator: Optional[PlaywrightNavigator] = None

    @property
    def navigator(self) -> PlaywrightNavigator:
        """Instancia o retorna el ayudante de navegación Playwright activo."""
        if self._navigator is None:
            self._navigator = PlaywrightNavigator(headless=True)
            self._navigator.start()
        return self._navigator

    def fetch_page_with_browser(
        self,
        url: str,
        download_binaries: bool = True,
        max_binaries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Navega con Chromium en modo oculto (headless), burla bloqueos de JavaScript
        y descarga archivos binarios adjuntos (PDFs, Word, Excel, etc.).
        """
        if self.use_playwright:
            try:
                res = self.navigator.navigate_and_extract(
                    url,
                    download_binaries=download_binaries,
                    max_binaries=max_binaries,
                )
                if res.get("html") or res.get("is_binary"):
                    return res
            except Exception as e:
                logger.warning(f"Aviso con Playwright en {url} ({e}), ejecutando fallback HTTP...")

        # Fallback HTTP estándar
        html = self.fetch_html(url)
        return {
            "url": url,
            "title": "",
            "html": html,
            "status_code": 200 if html else 500,
            "is_binary": False,
            "binaries": [],
        }

    def close(self):
        """Cierra el ayudante de navegación y libera Chromium."""
        if self._navigator:
            try:
                self._navigator.close()
            except Exception:
                pass
            self._navigator = None

    def fetch_html(self, url: str, max_retries: int = 3, initial_delay: float = 1.5) -> str:
        """Descarga el contenido HTML de una URL con soporte Playwright y reintentos HTTP."""
        clean_url_path = url.split("?")[0].split("#")[0].lower()
        if clean_url_path.endswith(BINARY_EXTENSIONS):
            logger.info(f"Omitiendo descarga de archivo binario como HTML: {url}")
            return ""

        # Intentar renderizado dinámico con Chromium headless si está habilitado
        if self.use_playwright:
            try:
                res = self.navigator.navigate_and_extract(url, download_binaries=False)
                if res.get("html"):
                    return sanitize_str(res["html"])
            except Exception as e:
                logger.debug(f"Aviso al navegar con Playwright en fetch_html: {e}")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        req = urllib.request.Request(url, headers=headers)

        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    content_type = response.headers.get_content_type()
                    if content_type and not any(ct in content_type.lower() for ct in ["html", "xml", "text"]):
                        logger.warning(f"Omitiendo URL con Content-Type no-HTML ({content_type}): {url}")
                        return ""
                    raw_bytes = response.read(15 * 1024 * 1024)
                    decoded = raw_bytes.decode("utf-8", errors="replace")
                    return sanitize_str(decoded)
            except Exception as e:
                if attempt == max_retries:
                    logger.warning(f"Fallo al conectar a {url} tras {max_retries} intentos: {e}")
                    return ""
                wait_time = initial_delay * (2 ** (attempt - 1)) + random.uniform(0.3, 0.8)
                time.sleep(wait_time)
        return ""

    @abc.abstractmethod
    def extract(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Método obligatorio a implementar por cada spider."""
        pass

    # ==========================================================================
    # ETAPA 1: Web -> RustFS S3 (Landing Zone Concurrente)
    # ==========================================================================
    def land_to_rustfs(
        self,
        records: List[Dict[str, Any]],
        s3_endpoint: str = "http://rustfs:9000",
        s3_access_key: str = "rustfsadmin",
        s3_secret_key: str = "rustfsadmin2026",
        bucket_name: str = "opportunity-intelligence",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Aterriza los registros crudos y la evidencia HTML en RustFS S3 concurrentemente."""
        inst_label = self.institution_name or self.source_system
        logger.info(
            f"=== [Landing S3] Guardando {len(records)} registros para spider '{self.name}' "
            f"(Institución: '{inst_label}' | Tabla Bronze: 'bronze.{self.target_table}') ==="
        )
        extracted_at = datetime.now(timezone.utc).isoformat()
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        date_partition = f"year={now.year}/month={now.month:02d}/day={now.day:02d}"

        batch_key = f"landing/{self.source_system}/{self.entity_name}/{date_partition}/batch_{batch_id}.json"
        batch_uri = f"s3://{bucket_name}/{batch_key}"

        if dry_run:
            logger.info("[Dry Run] Modo de prueba activo. No se persistirán datos en S3.")
            return {
                "spider": self.name,
                "batch_id": batch_id,
                "batch_uri": batch_uri,
                "bucket_name": bucket_name,
                "total_records": len(records),
                "records": records,
            }

        s3_client = get_s3_client(s3_endpoint, s3_access_key, s3_secret_key)

        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except Exception:
            logger.info(f"Creando bucket S3: {bucket_name}")
            try:
                s3_client.create_bucket(Bucket=bucket_name)
            except Exception as err:
                logger.warning(f"Aviso al crear bucket: {err}")

        landing_uris: Dict[str, str] = {"_batch_uri": batch_uri}

        def _upload_record_task(record: Dict[str, Any]) -> Tuple[str, str]:
            code = str(record.get(self.code_field) or record.get("call_code") or record.get("page_code") or "unknown")
            if self.institution_name and not record.get("institution_name"):
                record["institution_name"] = self.institution_name

            # Subir archivos binarios descargados (PDFs, Word, Excel, etc.) a RustFS S3
            if record.get("downloaded_binaries"):
                for b_item in record["downloaded_binaries"]:
                    fname = b_item.get("file_name", "document.bin")
                    b_hash = b_item.get("sha256_hash", "")[:12]
                    bin_key = f"binaries/{self.source_system}/{code}/{b_hash}_{fname}"
                    raw_b = b_item.get("raw_bytes")
                    if not raw_b and b_item.get("local_path") and os.path.exists(b_item["local_path"]):
                        try:
                            with open(b_item["local_path"], "rb") as f_bin:
                                raw_b = f_bin.read()
                        except Exception as read_err:
                            logger.warning(f"Aviso al leer binario local {b_item['local_path']}: {read_err}")

                    if raw_b:
                        try:
                            s3_client.put_object(
                                Bucket=bucket_name,
                                Key=bin_key,
                                Body=raw_b,
                                ContentType=b_item.get("content_type", "application/octet-stream"),
                            )
                            b_s3_uri = f"s3://{bucket_name}/{bin_key}"
                            b_item["s3_uri"] = b_s3_uri
                            landing_uris[f"{code}__bin__{fname}"] = b_s3_uri
                            logger.info(f"Archivo binario persistido en S3: {b_s3_uri} ({len(raw_b)} bytes)")
                        except Exception as bin_err:
                            logger.warning(f"Error subiendo binario {fname} a S3: {bin_err}")

                    # Remover raw_bytes para que json.dumps sea seguro y ligero
                    b_item.pop("raw_bytes", None)

            rec_str = json.dumps(record, ensure_ascii=False, indent=2)
            rec_str_clean = sanitize_str(rec_str)
            rec_hash = hashlib.sha256(rec_str_clean.encode("utf-8")).hexdigest()[:12]

            item_key = f"landing/{self.source_system}/raw_payloads/{date_partition}/{code}_{rec_hash}.json"
            s3_client.put_object(
                Bucket=bucket_name,
                Key=item_key,
                Body=rec_str_clean.encode("utf-8"),
                ContentType="application/json",
            )
            item_uri = f"s3://{bucket_name}/{item_key}"

            if record.get("raw_html"):
                doc_key = f"documents/{self.source_system}/{code}/source_evidence_{rec_hash}.html"
                try:
                    s3_client.put_object(
                        Bucket=bucket_name,
                        Key=doc_key,
                        Body=sanitize_str(record["raw_html"]).encode("utf-8"),
                        ContentType="text/html; charset=utf-8",
                    )
                except Exception as doc_err:
                    logger.warning(f"Aviso al subir documento HTML para {code}: {doc_err}")

            return code, item_uri

        max_workers = min(12, max(2, os.cpu_count() or 4))
        logger.info(f"Iniciando subida concurrente a S3 con {max_workers} hilos de ejecución...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_code = {executor.submit(_upload_record_task, rec): rec for rec in records}
            for future in as_completed(future_to_code):
                try:
                    code, uri = future.result()
                    landing_uris[code] = uri
                except Exception as exc:
                    rec_failed = future_to_code[future]
                    logger.error(f"Error subiendo registro '{rec_failed.get(self.code_field)}' a S3: {exc}")

        batch_data = {
            "spider": self.name,
            "institution_name": self.institution_name or self.source_system,
            "data_product": "opportunity_intelligence",
            "source_system": self.source_system,
            "entity_name": self.entity_name,
            "target_table": self.target_table,
            "code_field": self.code_field,
            "batch_id": batch_id,
            "date_partition": date_partition,
            "batch_uri": batch_uri,
            "extracted_at": extracted_at,
            "source_url": self.target_url,
            "total_records": len(records),
            "landing_uris": landing_uris,
            "records": records,
        }

        s3_client.put_object(
            Bucket=bucket_name,
            Key=batch_key,
            Body=sanitize_str(json.dumps(batch_data, ensure_ascii=False, indent=2)).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info(f"Manifest del lote guardado en RustFS S3: {batch_uri}")

        return {
            "spider": self.name,
            "institution_name": self.institution_name,
            "target_table": self.target_table,
            "batch_id": batch_id,
            "batch_uri": batch_uri,
            "bucket_name": bucket_name,
            "batch_key": batch_key,
            "total_records": len(records),
            "extracted_at": extracted_at,
        }

    # ==========================================================================
    # ETAPA 2: RustFS S3 -> PostgreSQL Bronze (Con Creación Dinámica de Tablas)
    # ==========================================================================
    def find_target_s3_batch(
        self,
        s3_client,
        bucket_name: str,
        batch_id: Optional[str] = None,
        batch_uri: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Resuelve el bucket y key exacto en S3 del manifest a cargar."""
        if batch_uri:
            uri_clean = batch_uri.replace("s3://", "")
            parts = uri_clean.split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
            return bucket_name, parts[0]

        candidate_buckets = [bucket_name]
        if bucket_name != "idrc-raw":
            candidate_buckets.append("idrc-raw")

        prefix = f"landing/{self.source_system}/{self.entity_name}/"

        if batch_id:
            target_suffix = f"batch_{batch_id}.json"
            for b in candidate_buckets:
                try:
                    resp = s3_client.list_objects_v2(Bucket=b, Prefix=prefix)
                    for obj in resp.get("Contents", []):
                        if obj["Key"].endswith(target_suffix):
                            return b, obj["Key"]
                except Exception:
                    continue
            raise FileNotFoundError(f"No se encontró el manifest para batch_id '{batch_id}' en S3 ({prefix}).")

        # Buscar el lote más reciente bajo el prefijo
        for b in candidate_buckets:
            try:
                resp = s3_client.list_objects_v2(Bucket=b, Prefix=prefix)
                contents = [obj for obj in resp.get("Contents", []) if obj["Key"].endswith(".json")]
                if contents:
                    contents.sort(key=lambda x: x["LastModified"], reverse=True)
                    return b, contents[0]["Key"]
            except Exception:
                continue

        # Fallback a búsqueda general en landing/
        for b in candidate_buckets:
            try:
                resp = s3_client.list_objects_v2(Bucket=b, Prefix="landing/")
                contents = [
                    obj for obj in resp.get("Contents", [])
                    if obj["Key"].endswith(".json") and "batch_" in obj["Key"]
                ]
                if contents:
                    contents.sort(key=lambda x: x["LastModified"], reverse=True)
                    return b, contents[0]["Key"]
            except Exception:
                continue

        raise FileNotFoundError(f"No se encontraron lotes de ingesta en S3 bajo el prefijo '{prefix}'.")

    def load_to_postgres(
        self,
        s3_endpoint: str = "http://rustfs:9000",
        s3_access_key: str = "rustfsadmin",
        s3_secret_key: str = "rustfsadmin2026",
        bucket_name: str = "opportunity-intelligence",
        db_conn_str: str = "",
        batch_id: Optional[str] = None,
        batch_uri: Optional[str] = None,
    ) -> int:
        """Carga el lote crudo de RustFS S3 a la tabla Bronze institucional en PostgreSQL."""
        import psycopg2

        s3_client = get_s3_client(s3_endpoint, s3_access_key, s3_secret_key)
        target_bucket, target_key = self.find_target_s3_batch(
            s3_client=s3_client,
            bucket_name=bucket_name,
            batch_id=batch_id,
            batch_uri=batch_uri,
        )
        resolved_batch_uri = f"s3://{target_bucket}/{target_key}"
        logger.info(f"Leyendo lote desde S3: {resolved_batch_uri}")

        s3_response = s3_client.get_object(Bucket=target_bucket, Key=target_key)
        raw_manifest_content = s3_response["Body"].read().decode("utf-8", errors="replace")
        manifest_data = json.loads(sanitize_str(raw_manifest_content))

        records = manifest_data.get("records", [])
        batch_id_val = manifest_data.get("batch_id") or str(uuid.uuid4())
        extracted_at = manifest_data.get("extracted_at") or datetime.now(timezone.utc).isoformat()
        landing_uris = manifest_data.get("landing_uris", {})
        batch_inst_name = manifest_data.get("institution_name") or self.institution_name or self.source_system

        # Resolver tabla destino según manifest o spider
        target_table_name = manifest_data.get("target_table") or getattr(self, "target_table", None)
        if not target_table_name:
            if self.institution_name:
                clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", self.institution_name.lower().strip()).strip("_")
                if clean_slug:
                    target_table_name = clean_slug
            else:
                target_table_name = "idrc__funding_calls"

        logger.info(
            f"=== [Loader Bronze] Cargando lote para institución '{batch_inst_name}' "
            f"hacia tabla 'bronze.{target_table_name}' ==="
        )

        if not records:
            logger.warning(f"El manifest {resolved_batch_uri} no contiene registros para ingestar.")
            return 0

        conn = psycopg2.connect(db_conn_str)
        cur = conn.cursor()

        # 1. Asegurar que la tabla Bronze específica para esta institución exista en PostgreSQL
        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS bronze."{target_table_name}" (
                call_code text NOT NULL,
                institution_name text NULL,
                payload jsonb NOT NULL,
                _ingested_at timestamptz DEFAULT now() NOT NULL,
                _batch_id uuid NOT NULL,
                _landing_uri text NOT NULL,
                _source_record_id text NULL,
                _record_hash text NULL,
                _extracted_at timestamptz NULL,
                CONSTRAINT "{target_table_name}__pkey" PRIMARY KEY (call_code, _batch_id)
            );
            CREATE INDEX IF NOT EXISTS "idx_bronze_{target_table_name}_batch" 
                ON bronze."{target_table_name}" USING btree (_batch_id);
            CREATE INDEX IF NOT EXISTS "idx_bronze_{target_table_name}_code" 
                ON bronze."{target_table_name}" USING btree (call_code);
            CREATE INDEX IF NOT EXISTS "idx_bronze_{target_table_name}_inst" 
                ON bronze."{target_table_name}" USING btree (institution_name);
        """
        cur.execute(create_table_sql)
        conn.commit()

        # 2. Inserción con UPSERT en la tabla Bronze de la institución
        insert_sql = f"""
            INSERT INTO bronze."{target_table_name}" (
                call_code,
                institution_name,
                payload,
                _ingested_at,
                _batch_id,
                _landing_uri,
                _source_record_id,
                _record_hash,
                _extracted_at
            ) VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s)
            ON CONFLICT (call_code, _batch_id) DO UPDATE SET
                institution_name = EXCLUDED.institution_name,
                payload = EXCLUDED.payload,
                _ingested_at = NOW(),
                _landing_uri = EXCLUDED._landing_uri,
                _record_hash = EXCLUDED._record_hash,
                _extracted_at = EXCLUDED._extracted_at;
        """

        inserted_count = 0
        error_count = 0

        for item in records:
            code = str(item.get("call_code") or item.get("page_code") or item.get(self.code_field) or "unknown")
            item_inst = item.get("institution_name") or batch_inst_name
            item["institution_name"] = item_inst
            item["call_code"] = code

            payload_raw = json.dumps(item, ensure_ascii=False)
            payload_clean = sanitize_str(payload_raw)

            record_hash = hashlib.sha256(payload_clean.encode("utf-8")).hexdigest()
            specific_uri = landing_uris.get(code, f"{resolved_batch_uri}#{code}")

            try:
                cur.execute("SAVEPOINT row_savepoint;")
                cur.execute(
                    insert_sql,
                    (
                        code,
                        item_inst,
                        payload_clean,
                        batch_id_val,
                        specific_uri,
                        code,
                        record_hash,
                        extracted_at,
                    ),
                )
                cur.execute("RELEASE SAVEPOINT row_savepoint;")
                inserted_count += 1
            except Exception as row_err:
                cur.execute("ROLLBACK TO SAVEPOINT row_savepoint;")
                error_count += 1
                logger.warning(f"Aviso: Registro '{code}' omitido por error ({row_err}).")

        conn.commit()
        cur.close()
        conn.close()

        logger.info(
            f"Lote finalizado: {inserted_count} registros cargados exitosamente a bronze.\"{target_table_name}\" "
            f"({error_count} omitidos por error)."
        )
        return inserted_count
