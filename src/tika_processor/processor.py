#!/usr/bin/env python3
"""
IDCI Apache Tika Ephemeral Processor (Fan-Out Lakehouse Pattern)
================================================================
Lee archivos crudos (binarios PDFs, Word, Excel, HTML, etc.) desde la
Landing Zone de RustFS S3, extrae texto limpio y metadatos estructurados
usando Apache Tika, y los persiste en la Processed Zone de RustFS S3
únicamente en formato texto (.txt) y JSON (.json).

Diseñado para ejecutarse bajo el patrón Fan-Out en contenedores efímeros
paralelos controlados por Apache Airflow:
  [⚡ idci_tika - Lote 1] ──► (Procesa archivos 1-500)
  [⚡ idci_tika - Lote 2] ──► (Procesa archivos 501-1000)
  [⚡ idci_tika - Lote 3] ──► (Procesa archivos 1001-1500)
"""

import os
import re
import sys
import json
import uuid
import hashlib
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import boto3
from botocore.client import Config
from tika import parser

# Logging estructurado hacia stderr para mantener stdout limpio para JSON/IPC
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("idci_tika")


def sanitize_str(text: Optional[str]) -> str:
    """Elimina caracteres nulos e incompatibles."""
    if not text:
        return ""
    return text.replace("\x00", "").replace("\u0000", "")


def get_s3_client(s3_endpoint: str, s3_access_key: str, s3_secret_key: str):
    """Inicializa cliente boto3 para RustFS S3."""
    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 5, "mode": "standard"},
            max_pool_connections=20,
        ),
    )


class TikaFanOutProcessor:
    """
    Procesador efímero de Apache Tika con soporte para particionamiento Fan-Out.
    """

    def __init__(
        self,
        s3_endpoint: str,
        s3_access_key: str,
        s3_secret_key: str,
        bucket_name: str = "opportunity-intelligence",
        institution: Optional[str] = None,
        chunk_id: str = "Lote-1",
        offset: int = 0,
        limit: int = 500,
        dry_run: bool = False,
    ):
        self.s3_endpoint = s3_endpoint
        self.s3_access_key = s3_access_key
        self.s3_secret_key = s3_secret_key
        self.bucket_name = bucket_name
        self.institution = (institution or "").lower().strip()
        self.chunk_id = chunk_id
        self.offset = max(0, offset)
        self.limit = max(1, limit)
        self.dry_run = dry_run
        self.s3_client = get_s3_client(s3_endpoint, s3_access_key, s3_secret_key)

    def discover_raw_files(self, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Descubre todos los archivos crudos en la Landing Zone de RustFS S3
        (binarios PDFs/Word bajo 'binaries/' y documentos crudos bajo 'documents/').
        """
        all_files = []
        prefixes = []

        if self.institution:
            clean_inst = re.sub(r"[^a-zA-Z0-9_]", "_", self.institution).strip("_")
            prefixes.append(f"binaries/{clean_inst}/")
            prefixes.append(f"documents/{clean_inst}/")
        else:
            prefixes.append("binaries/")
            prefixes.append("documents/")

        for prefix in prefixes:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            try:
                for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        key = obj["Key"]
                        # Evitar procesar directorios vacíos o archivos temporales
                        if key.endswith("/") or key.endswith(".tmp"):
                            continue
                        all_files.append({
                            "key": key,
                            "size": obj.get("Size", 0),
                            "last_modified": obj.get("LastModified").isoformat() if obj.get("LastModified") else "",
                            "prefix_type": "binary" if key.startswith("binaries/") else "document",
                        })
            except Exception as e:
                logger.warning(f"Aviso al listar objetos bajo prefijo '{prefix}': {e}")

        # Ordenar por fecha o key para garantizar particionamiento determinista en Fan-Out
        all_files.sort(key=lambda x: x["key"])
        return all_files

    def generate_plan(self, chunk_size: int = 500) -> List[Dict[str, Any]]:
        """
        Calcula el plan de particionamiento Fan-Out según el número total de archivos crudos.
        """
        files = self.discover_raw_files()
        total_files = len(files)
        plan = []

        if total_files == 0:
            logger.info("No se encontraron archivos crudos en Landing Zone para planificar.")
            return []

        chunk_count = (total_files + chunk_size - 1) // chunk_size
        logger.info(
            f"=== [Fan-Out Plan] Total archivos crudos: {total_files} | Tamaño de lote: {chunk_size} | Lotes calculados: {chunk_count} ==="
        )

        for i in range(chunk_count):
            start = i * chunk_size
            count = min(chunk_size, total_files - start)
            plan.append({
                "lote": i + 1,
                "chunk_id": f"Lote-{i + 1}",
                "offset": start,
                "limit": chunk_size,
                "files_count": count,
                "first_file_index": start + 1,
                "last_file_index": start + count,
            })

        return plan

    def process_file_with_tika(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Descarga el archivo crudo desde S3 Landing Zone, ejecuta extracción de texto
        y metadatos con Apache Tika y guarda los resultados limpios en RustFS S3 Processed Zone.
        """
        key = file_info["key"]
        logger.info(f"[{self.chunk_id}] Procesando con Apache Tika: {key} ({file_info.get('size', 0)} bytes)")

        # 1. Descargar objeto crudo desde S3 Landing Zone
        resp = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
        raw_bytes = resp["Body"].read()

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        filename = os.path.basename(key)

        # 2. Extracción con Apache Tika
        tika_result = parser.from_buffer(raw_bytes)
        tika_status = tika_result.get("status", 200)

        raw_content = tika_result.get("content") or ""
        extracted_text = sanitize_str(raw_content).strip()

        # Extraer metadatos limpios
        raw_metadata = tika_result.get("metadata") or {}
        clean_metadata = {}
        for k, v in raw_metadata.items():
            clean_k = sanitize_str(str(k)).strip()
            clean_v = sanitize_str(str(v)).strip() if not isinstance(v, list) else [sanitize_str(str(x)).strip() for x in v]
            clean_metadata[clean_k] = clean_v

        words_count = len(extracted_text.split()) if extracted_text else 0
        chars_count = len(extracted_text)

        # 3. Estructurar rutas inmutables para la Processed Zone en RustFS S3
        # Desglosar jerarquía de la key original: binaries/{source_system}/{code}/...
        key_parts = key.split("/")
        source_system = key_parts[1] if len(key_parts) > 1 else (self.institution or "general")
        code = key_parts[2] if len(key_parts) > 2 else "unknown"

        now_utc = datetime.now(timezone.utc)
        date_partition = f"year={now_utc.year}/month={now_utc.month:02d}/day={now_utc.day:02d}"

        base_clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", filename)
        text_key = f"processed/{source_system}/{code}/{date_partition}/{file_hash[:10]}_{base_clean_name}.txt"
        meta_key = f"processed/{source_system}/{code}/{date_partition}/{file_hash[:10]}_{base_clean_name}_meta.json"

        text_s3_uri = f"s3://{self.bucket_name}/{text_key}"
        meta_s3_uri = f"s3://{self.bucket_name}/{meta_key}"

        processed_record = {
            "source_system": source_system,
            "call_code": code,
            "source_s3_key": key,
            "source_s3_uri": f"s3://{self.bucket_name}/{key}",
            "source_filename": filename,
            "source_file_size": len(raw_bytes),
            "source_sha256": file_hash,
            "tika_status": tika_status,
            "tika_content_type": clean_metadata.get("Content-Type", "application/octet-stream"),
            "extracted_text_chars": chars_count,
            "extracted_text_words": words_count,
            "text_storage_uri": text_s3_uri,
            "metadata_storage_uri": meta_s3_uri,
            "processed_at": now_utc.isoformat(),
            "worker_chunk_id": self.chunk_id,
            "tika_metadata": clean_metadata,
        }

        if not self.dry_run:
            # A. Guardar texto plano procesado en RustFS S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=text_key,
                Body=extracted_text.encode("utf-8"),
                ContentType="text/plain; charset=utf-8",
            )

            # B. Guardar metadata estructurada JSON en RustFS S3
            meta_json = json.dumps(processed_record, ensure_ascii=False, indent=2)
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=meta_key,
                Body=sanitize_str(meta_json).encode("utf-8"),
                ContentType="application/json; charset=utf-8",
            )

            logger.info(
                f"[{self.chunk_id}] ✅ Persistido en Processed Zone: {text_s3_uri} ({chars_count} chars, {words_count} palabras)"
            )
        else:
            logger.info(f"[{self.chunk_id}] [Dry Run] Procesado {filename}: {chars_count} chars.")

        return processed_record

    def run_chunk(self) -> Dict[str, Any]:
        """
        Ejecuta el lote asignado al contenedor efímero [⚡ idci_tika - Lote X].
        """
        files = self.discover_raw_files()
        total_discovered = len(files)

        # Extraer el slice correspondiente a este Lote
        chunk_files = files[self.offset : self.offset + self.limit]
        chunk_total = len(chunk_files)

        first_idx = self.offset + 1 if chunk_total > 0 else 0
        last_idx = self.offset + chunk_total

        logger.info("=" * 75)
        logger.info(f"=== [⚡ idci_tika - {self.chunk_id}] Contenedor Efímero Iniciado ===")
        logger.info(f"-> Archivos totales en Landing Zone: {total_discovered}")
        logger.info(f"-> Rango asignado a este lote: Archivos {first_idx} a {last_idx} (Total: {chunk_total})")
        logger.info(f"-> Destino: RustFS S3 (Processed Zone: 'processed/')")
        logger.info("=" * 75)

        if chunk_total == 0:
            logger.info(f"[{self.chunk_id}] No hay archivos asignados en este rango ({self.offset} a {self.offset + self.limit}). Finalizando.")
            return {
                "chunk_id": self.chunk_id,
                "offset": self.offset,
                "limit": self.limit,
                "processed_count": 0,
                "items": [],
            }

        processed_items = []
        errors = 0

        for idx, f_info in enumerate(chunk_files, start=1):
            try:
                rec = self.process_file_with_tika(f_info)
                processed_items.append(rec)
            except Exception as e:
                errors += 1
                logger.error(f"[{self.chunk_id}] Error procesando archivo {f_info['key']}: {e}")

        # Guardar manifiesto de lote en RustFS Processed Zone
        batch_uuid = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc)
        date_partition = f"year={now_utc.year}/month={now_utc.month:02d}/day={now_utc.day:02d}"
        manifest_key = f"processed/manifests/{date_partition}/manifest_{self.chunk_id}_{batch_uuid}.json"
        manifest_uri = f"s3://{self.bucket_name}/{manifest_key}"

        manifest_data = {
            "chunk_id": self.chunk_id,
            "batch_uuid": batch_uuid,
            "processed_at": now_utc.isoformat(),
            "first_file_index": first_idx,
            "last_file_index": last_idx,
            "total_files_in_chunk": chunk_total,
            "successfully_processed": len(processed_items),
            "errors_count": errors,
            "manifest_uri": manifest_uri,
            "items": processed_items,
        }

        if not self.dry_run and processed_items:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=manifest_key,
                Body=sanitize_str(json.dumps(manifest_data, ensure_ascii=False, indent=2)).encode("utf-8"),
                ContentType="application/json; charset=utf-8",
            )
            logger.info(f"[{self.chunk_id}] 📜 Manifiesto de lote guardado en: {manifest_uri}")

        logger.info("=" * 75)
        logger.info(
            f"=== [⚡ idci_tika - {self.chunk_id}] Lote Finalizado: {len(processed_items)} procesados, "
            f"{errors} errores. El contenedor se autodestruirá (--rm). ==="
        )
        logger.info("=" * 75)

        return manifest_data


def main():
    parser = argparse.ArgumentParser(
        description="IDCI Apache Tika Ephemeral Processor (Fan-Out Lakehouse Pattern)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--institution",
        type=str,
        default=os.getenv("INSTITUTION_NAME", None),
        help="Institución a procesar (ej: IDRC, CYTED, UKRI). Si no se especifica, procesa toda la Landing Zone.",
    )
    parser.add_argument(
        "--chunk-id",
        type=str,
        default=os.getenv("TIKA_CHUNK_ID", "Lote-1"),
        help="Identificador del lote Fan-Out (ej: 'Lote-1', 'Lote-2', 'Lote-3').",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=int(os.getenv("TIKA_OFFSET", "0")),
        help="Índice inicial (0-based) de archivos a procesar en este lote (ej: 0, 500, 1000).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("TIKA_LIMIT", "500")),
        help="Cantidad máxima de archivos a procesar en este lote (default: 500).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Tamaño de lote para el planificador Fan-Out (default: 500).",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Modo Planificador: calcula y muestra en formato JSON el plan de lotes Fan-Out para Airflow sin procesar.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta la extracción en memoria sin escribir en RustFS S3.",
    )
    args = parser.parse_args()

    s3_endpoint = os.getenv("S3_ENDPOINT_URL", "http://rustfs:9000")
    s3_access_key = os.getenv("S3_ACCESS_KEY", "rustfsadmin")
    s3_secret_key = os.getenv("S3_SECRET_KEY", "rustfsadmin2026")
    s3_bucket = os.getenv("S3_BUCKET", "opportunity-intelligence")

    processor = TikaFanOutProcessor(
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        bucket_name=s3_bucket,
        institution=args.institution,
        chunk_id=args.chunk_id,
        offset=args.offset,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    if args.plan:
        plan = processor.generate_plan(chunk_size=args.chunk_size)
        print(json.dumps(plan, indent=2))
        return

    result = processor.run_chunk()
    return result


if __name__ == "__main__":
    main()
