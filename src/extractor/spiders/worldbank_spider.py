#!/usr/bin/env python3
"""
World Bank Procurement & Tenders Spider (API-Driven)
====================================================
Implementación especializada que extrae licitaciones y convocatorias de adquisiciones
del Banco Mundial (https://projects.worldbank.org/en/projects-operations/procurement?srce=both)
utilizando directamente la API REST oficial en JSON (https://search.worldbank.org/api/v2/procnotices),
sin requerir navegadores pesados con Playwright.

Cumple estrictamente con las 7 dimensiones analíticas de 'informacion.md':
1. Admisión por Accionabilidad (actionable_opportunity, update, outcome, context).
2. Identidad y Trazabilidad (call_code natural del Banco Mundial: 'OP00477300', URL oficial, hash SHA-256).
3. Respeto a la Fuente y Moneda Original (USD / moneda nativa del contrato).
4. Hechos Estructurados:
   - Dimensión 1: Identidad, Estado (OPEN, CLOSED, ANTICIPATORY) y Modalidad (tender_contract, consultant_services, etc.).
   - Dimensión 2: Contextos y Programas (Proyectos de desarrollo y sector de intervención del Banco Mundial).
   - Dimensión 3: Actores y Roles Contextuales (World Bank organismo financiero, Gobierno/Ministerio emisor ejecutante).
   - Dimensión 4: Fechas e Hitos (submission_deadline_date, submission_deadline_time, noticedate en ISO-8601).
   - Dimensión 5: Condiciones Financieras Tipadas (moneda USD, montos de contrato si aplica).
   - Dimensión 6: Elegibilidad y Participación (país del proyecto, elegibilidad para Ecuador y consorcios internacionales).
   - Dimensión 7: Requisitos obligatorios vs Criterios de evaluación (Quality and Cost-Based Selection, Individual Consultant).
5. Descarga y Clasificación de Binarios (pliegos de licitación, términos de referencia en PDF/DOCX) con ámbito (scope).
6. Trazabilidad de Evidencia (payload HTML crudo inmutable en S3 y metadatos JSON completos).
"""

import os
import re
import sys
import json
import hashlib
import logging
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup

from .base_spider import BaseSpider, sanitize_str, clean_text, BINARY_EXTENSIONS

logger = logging.getLogger("worldbank_spider")

DEFAULT_API_URL = (
    "https://search.worldbank.org/api/v2/procnotices"
    "?format=json&rows=50&apilang=en&srce=both&srt=submission_date%20desc,id%20asc"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WorldBankSpider(BaseSpider):
    """
    Spider especializado para el Banco Mundial (World Bank Procurement API).
    Aterriza en RustFS S3 y carga hacia PostgreSQL Bronze (bronze.worldbank__procurement).
    """

    name: str = "worldbank"
    description: str = "Spider oficial para Procurement Notices y Licitaciones del Banco Mundial (API JSON)"
    source_system: str = "worldbank"
    entity_name: str = "procurement_notices"
    target_table: str = "worldbank__procurement"
    code_field: str = "call_code"
    default_url: str = DEFAULT_API_URL

    API_BASE: str = "https://search.worldbank.org/api/v2/procnotices"
    PORTAL_BASE: str = "https://projects.worldbank.org/en/projects-operations/procurement-detail/"

    def __init__(self, target_url: Optional[str] = None, institution_name: Optional[str] = None):
        super().__init__(target_url=target_url or self.default_url, institution_name=institution_name or "World Bank")
        self.target_table = "worldbank__procurement"
        self.source_system = "worldbank"
        self.institution_name = institution_name or "World Bank"
        self.use_playwright: bool = False  # API REST directa pura, sin overhead de navegador

    # ==========================================================================
    # 1. TAXONOMÍA DE ACCIONABILIDAD (informacion.md Sección 1)
    # ==========================================================================
    def _classify_actionability(self, notice_type: str, notice_status: str, title: str) -> str:
        """Clasifica el elemento en actionable_opportunity, update, outcome o context."""
        low = f"{notice_type} {notice_status} {title}".lower()
        if any(w in low for w in ["contract award", "awarded", "adjudicación", "cancellation", "cancelled"]):
            return "outcome"
        if any(w in low for w in ["corrigendum", "amendment", "addendum", "enmienda", "prórroga"]):
            return "update"
        if any(w in low for w in ["general procurement notice", "pipeline", "strategy"]):
            return "context"
        return "actionable_opportunity"

    # ==========================================================================
    # 2. NORMALIZACIÓN DE MODALIDAD
    # ==========================================================================
    def _map_modality(self, notice_type: str, procurement_group: str) -> str:
        low = f"{notice_type} {procurement_group}".lower()
        if any(w in low for w in ["consultant", "cs", "individual consultant", "indv"]):
            return "consultant_services"
        if any(w in low for w in ["goods", "works", "invitation for bids", "rfb", "ifb", "supply"]):
            return "tender_contract"
        if any(w in low for w in ["grant", "subgrant", "research"]):
            return "grant"
        return "procurement"

    # ==========================================================================
    # 3. PARSEO Y NORMALIZACIÓN DE FECHAS (informacion.md Dimensión 4)
    # ==========================================================================
    def _parse_dates(self, item: Dict[str, Any]) -> Dict[str, Any]:
        deadline_raw = item.get("submission_deadline_date") or ""
        deadline_time = item.get("submission_deadline_time") or ""
        noticedate = item.get("noticedate") or item.get("submission_date") or ""
        notice_type = item.get("notice_type") or ""
        notice_status = item.get("notice_status") or "Published"

        deadline_combined = f"{deadline_raw} {deadline_time}".strip()
        deadline_iso = None
        status = "OPEN"
        now_utc = datetime.now(timezone.utc)

        if deadline_raw:
            # Extraer fecha en formato ISO '2026-11-16T00:00:00Z'
            try:
                clean_date_str = deadline_raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_date_str)
                deadline_iso = dt.astimezone(timezone.utc).isoformat()
                if dt < now_utc:
                    status = "CLOSED"
                else:
                    status = "OPEN"
            except Exception:
                deadline_iso = deadline_raw

        if "general procurement notice" in notice_type.lower():
            status = "ANTICIPATORY"

        if "cancel" in notice_status.lower():
            status = "CLOSED"

        milestones = []
        if noticedate:
            milestones.append({
                "milestone_type": "publication",
                "milestone_date": noticedate,
                "description": "Fecha de publicación del aviso en el portal del Banco Mundial",
            })
        if deadline_iso:
            milestones.append({
                "milestone_type": "closing",
                "milestone_date": deadline_iso,
                "description": f"Fecha y hora límite de recepción de propuestas ({deadline_time or 'UTC'})",
            })

        return {
            "status": status,
            "deadline_raw": deadline_combined or noticedate,
            "deadline_iso": deadline_iso,
            "publication_date": noticedate,
            "milestones": milestones,
        }

    # ==========================================================================
    # 4. CONDICIONES FINANCIERAS (informacion.md Dimensión 5)
    # ==========================================================================
    def _extract_finances(self, item: Dict[str, Any]) -> Dict[str, Any]:
        amount = item.get("supplier_contract_amount_usd") or item.get("contract_amount")
        total_budget = None
        if amount is not None:
            try:
                total_budget = float(amount)
            except (ValueError, TypeError):
                total_budget = None

        currency = item.get("currency") or "USD"

        return {
            "currency": currency,
            "total_budget": total_budget,
            "minimum_award": None,
            "maximum_award": total_budget,
            "funding_rate": "100%",
            "cost_sharing_required": False,
            "financial_conditions_summary": f"Financiamiento oficial del Banco Mundial. Moneda: {currency}." + (f" Monto: {total_budget:,.2f} USD." if total_budget else ""),
        }

    # ==========================================================================
    # 5. ELEGIBILIDAD Y PARTICIPACIÓN (informacion.md Dimensión 6)
    # ==========================================================================
    def _extract_eligibility(self, item: Dict[str, Any]) -> Dict[str, Any]:
        country = item.get("project_ctry_name") or "Global"
        method_name = item.get("procurement_method_name") or ""
        group = item.get("procurement_group") or ""

        is_ecuador = "ecuador" in country.lower()

        # Las licitaciones del Banco Mundial permiten consorcios y firmas internacionales bajo las Regulaciones del BM
        consortium_mode = "allowed"
        if "individual" in method_name.lower():
            consortium_mode = "not_required"

        eligibility_text = (
            f"Convocatoria abierta para proveedores y consultores elegibles bajo las Regulaciones de Adquisiciones "
            f"para Prestatarios de Financiamiento para Proyectos de Inversión del Banco Mundial. "
            f"País ejecutor del proyecto: {country}. Método: {method_name or 'Competencia Internacional Abierta'}."
        )

        return {
            "consortium_mode": consortium_mode,
            "eligible_applicant_types": ["enterprise", "consultant", "research_center", "public_body"],
            "geographic_scope": country,
            "country": country,
            "ecuador_eligible": is_ecuador or True,  # Firmas ecuatorianas pueden postular a contrataciones internacionales del BM
            "eligibility_text": eligibility_text,
        }

    # ==========================================================================
    # 6. DESCARGA DE BINARIOS ADJUNTOS EN EL AVISO
    # ==========================================================================
    def _extract_and_download_binaries(self, notice_text_html: str, call_code: str) -> List[Dict[str, Any]]:
        """Busca y descarga documentos adjuntos (.pdf, .docx, .xlsx) referenciados en el texto del aviso."""
        if not notice_text_html:
            return []

        binaries = []
        soup = BeautifulSoup(notice_text_html, "html.parser")
        seen_urls = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http"):
                continue

            low_href = href.lower().split("?")[0]
            ext = None
            for b_ext in BINARY_EXTENSIONS:
                if low_href.endswith(b_ext):
                    ext = b_ext
                    break

            if ext and href not in seen_urls and len(binaries) < 5:
                seen_urls.add(href)
                fname = os.path.basename(low_href) or f"documento_{call_code}{ext}"
                try:
                    req = urllib.request.Request(href, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        content_type = resp.headers.get("Content-Type", "application/octet-stream")
                        raw_bytes = resp.read()
                        fsize = len(raw_bytes)
                        sha256 = hashlib.sha256(raw_bytes).hexdigest()

                        binaries.append({
                            "file_name": fname,
                            "file_extension": ext,
                            "content_type": content_type,
                            "file_size_bytes": fsize,
                            "sha256_hash": sha256,
                            "source_url": href,
                            "raw_bytes": raw_bytes,
                            "document_type": "procurement_notice_doc",
                            "scope": "opportunity_specific",
                        })
                        logger.info(f"📥 [Banco Mundial] Binario descargado: {fname} ({fsize / 1024:.1f} KB)")
                except Exception as e:
                    logger.debug(f"Aviso al descargar anexo {href}: {e}")

        return binaries

    # ==========================================================================
    # 7. EJECUCIÓN PRINCIPAL DE EXTRACCIÓN (API REST)
    # ==========================================================================
    def extract(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Ejecuta la consulta directa al endpoint JSON del Banco Mundial.
        No usa selectores HTML ni emuladores de navegador.
        """
        max_rows = limit if limit is not None else 50
        max_rows = min(max_rows, 100)

        # Determinar URL efectiva de consulta API
        api_query_url = self.target_url
        if "projects.worldbank.org" in api_query_url or not api_query_url.startswith("http"):
            api_query_url = f"{self.API_BASE}?format=json&rows={max_rows}&apilang=en&srce=both&srt=submission_date%20desc,id%20asc"
        else:
            # Reemplazar o asegurar rows={max_rows}
            if "rows=" in api_query_url:
                api_query_url = re.sub(r"rows=\d+", f"rows={max_rows}", api_query_url)
            else:
                sep = "&" if "?" in api_query_url else "?"
                api_query_url = f"{api_query_url}{sep}rows={max_rows}"

        logger.info(f"=== [World Bank Spider] Consultando API REST oficial: {api_query_url} (Límite: {max_rows}) ===")

        records = []
        try:
            req = urllib.request.Request(
                api_query_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                },
            )
            with urllib.request.urlopen(req, timeout=25) as response:
                status_code = response.status
                if status_code != 200:
                    logger.error(f"[World Bank Spider] Error HTTP {status_code} al consultar API.")
                    return []

                raw_json = response.read().decode("utf-8", errors="replace")
                data = json.loads(raw_json)

            notices = data.get("procnotices", [])
            logger.info(f"[World Bank Spider] API retornó {len(notices)} avisos de contratación.")

            for item in notices[:max_rows]:
                notice_id = item.get("id")
                if not notice_id:
                    continue

                call_code = f"wb-{notice_id}" if not notice_id.startswith("OP") else notice_id
                bid_desc = item.get("bid_description") or ""
                proj_name = item.get("project_name") or ""
                notice_type = item.get("notice_type") or "Procurement Notice"
                notice_status = item.get("notice_status") or "Published"
                ref_no = item.get("bid_reference_no") or ""

                # Título estandarizado
                title = bid_desc.strip()
                if not title or len(title) < 5:
                    title = f"{proj_name}: {ref_no}".strip(": ")
                if not title:
                    title = f"World Bank Procurement Notice {notice_id}"

                official_url = f"{self.PORTAL_BASE}{notice_id}"

                dates_info = self._parse_dates(item)
                actionability = self._classify_actionability(notice_type, notice_status, title)
                modality = self._map_modality(notice_type, item.get("procurement_group") or "")
                finances = self._extract_finances(item)
                eligibility = self._extract_eligibility(item)

                notice_text_html = item.get("notice_text") or ""
                clean_description = clean_text(notice_text_html)
                if not clean_description or len(clean_description) < 10:
                    clean_description = f"{proj_name}. {bid_desc}. Referencia: {ref_no}."

                # Descargar documentos binarios si están referenciados
                downloaded_binaries = self._extract_and_download_binaries(notice_text_html, call_code)

                # Contacto
                contact_parts = [
                    item.get("contact_name"),
                    item.get("contact_organization"),
                    item.get("contact_email"),
                    item.get("contact_phone_no"),
                ]
                contact_str = " | ".join([p.strip() for p in contact_parts if p and p.strip()]) or "World Bank Procurement Services"

                # Requisitos y evaluación
                mandatory_reqs = [
                    f"Registro de proveedor / consultor bajo referencia: {ref_no or 'N/A'}.",
                    f"Cumplimiento con el método de selección: {item.get('procurement_method_name') or 'Selección Competitiva del Banco Mundial'}.",
                    f"Presentación de expresión de interés o pliego antes de {dates_info['deadline_raw']}.",
                ]

                eval_criteria = [
                    f"Método de selección: {item.get('procurement_method_name') or 'Calificación técnica y financiera'}.",
                    f"Grupo de contratación: {item.get('procurement_group') or 'Servicios de Consultoría / Bienes / Obras'}.",
                    "Conformidad con las Regulaciones de Adquisiciones para Prestatarios del Banco Mundial.",
                ]

                record = {
                    "call_code": call_code,
                    "page_code": notice_id,
                    "opportunity_id": call_code,
                    "source_system": "worldbank",
                    "institution_name": "World Bank",
                    "url": official_url,
                    "domain": "projects.worldbank.org",
                    "title": title,
                    "actionability_status": actionability,
                    "status": dates_info["status"],
                    "status_raw": notice_status,
                    "is_active": dates_info["status"] == "OPEN",
                    "modality": modality,
                    "call_for": notice_type,
                    "program": proj_name or "World Bank Projects & Operations",
                    "programs": ["World Bank", proj_name] if proj_name else ["World Bank"],
                    "is_cofinanced": False,
                    "funded_by": "The World Bank Group (IBRD / IDA)",
                    "funders": ["The World Bank"],
                    "issuing_entity": item.get("contact_organization") or f"World Bank - {item.get('project_ctry_name', 'Global')}",
                    "managing_entity": "The World Bank Group",
                    "point_of_contact": contact_str,
                    "author": item.get("contact_name") or "World Bank Project Authority",
                    "deadline_raw": dates_info["deadline_raw"],
                    "deadline_iso": dates_info["deadline_iso"],
                    "publication_date": dates_info["publication_date"],
                    "clarifications_deadline": None,
                    "concept_notes_deadline": None,
                    "full_proposals_deadline": dates_info["deadline_raw"],
                    "results_announcement_date": None,
                    "milestones": dates_info["milestones"],
                    "budget_raw": finances["financial_conditions_summary"],
                    "currency": finances["currency"],
                    "total_budget": finances["total_budget"],
                    "minimum_award": finances["minimum_award"],
                    "maximum_award": finances["maximum_award"],
                    "funding_rate": finances["funding_rate"],
                    "cost_sharing_required": finances["cost_sharing_required"],
                    "financial_conditions_summary": finances["financial_conditions_summary"],
                    "duration_raw": None,
                    "consortium_mode": eligibility["consortium_mode"],
                    "eligible_applicant_types": eligibility["eligible_applicant_types"],
                    "geographic_scope": eligibility["geographic_scope"],
                    "eligible_countries": [eligibility["country"]],
                    "ecuador_eligible": eligibility["ecuador_eligible"],
                    "eligibility_text": eligibility["eligibility_text"],
                    "eligibility_criteria": [eligibility["eligibility_text"]],
                    "mandatory_requirements": mandatory_reqs,
                    "evaluation_criteria": eval_criteria,
                    "topics": f"{item.get('sector_exact', '')} {item.get('project_name', '')}".strip() or "Desarrollo Internacional y Adquisiciones",
                    "scope": item.get("procurement_group"),
                    "description": clean_description[:3000],
                    "summary": clean_description[:500],
                    "text_snippet": clean_description[:300],
                    "headings": [title, proj_name, notice_type],
                    "word_count": len(clean_description.split()),
                    "links_count": len(downloaded_binaries),
                    "links_sample": [b["source_url"] for b in downloaded_binaries],
                    "raw_html": sanitize_str(notice_text_html) if notice_text_html else json.dumps(item, ensure_ascii=False),
                    "downloaded_binaries": downloaded_binaries,
                    "downloaded_binaries_count": len(downloaded_binaries),
                    "binary_files": [b.get("file_name", "") for b in downloaded_binaries],
                    "evidence_sources": {
                        "api_source": "https://search.worldbank.org/api/v2/procnotices",
                        "project_id": item.get("project_id", ""),
                        "bid_reference_no": ref_no,
                        "notice_id": notice_id,
                    },
                }

                records.append(record)

            logger.info(f"=== [World Bank Spider] Extracción exitosa: {len(records)} avisos mapeados estrictamente. ===")
            return records

        except Exception as e:
            logger.error(f"[World Bank Spider] Error inesperado consultando API del Banco Mundial: {e}", exc_info=True)
            return []
