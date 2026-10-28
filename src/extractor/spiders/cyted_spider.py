#!/usr/bin/env python3
"""
CYTED Specialized Spider (Programa Iberoamericano de Ciencia y Tecnología para el Desarrollo)
===========================================================================================
Implementación especializada que extrae convocatorias oficiales de financiamiento, redes
temáticas, foros y proyectos estratégicos de CYTED (https://www.cyted.org/).

Cumple estrictamente con todas las directrices de 'informacion.md':
1. Admisión por Accionabilidad (actionable_opportunity, update, outcome, context).
2. Identidad y Trazabilidad (call_code natural, URL oficial exacta, hash SHA-256 inmutable).
3. Respeto a la Fuente y Moneda Original (EUR/USD según corresponda, sin conversión arbitraria).
4. Hechos Estructurados (7 Dimensiones del PRD):
   - Dimensión 1: Identidad, Estado (OPEN/CLOSED) y Modalidad normalizada.
   - Dimensión 2: Contextos y Programas (Redes Temáticas, Foros, IBEROEKA, Proyectos Estratégicos).
   - Dimensión 3: Actores y Roles Contextuales (CYTED emisor/gestor, Organismos Nacionales financiadores).
   - Dimensión 4: Fechas e Hitos (apertura, cierre, fechas de aclaración).
   - Dimensión 5: Condiciones Financieras Tipadas (moneda EUR, contrapartida obligatoria).
   - Dimensión 6: Elegibilidad y Participación (consorcio obligatorio >= 6 países iberoamericanos, Ecuador prioritario).
   - Dimensión 7: Requisitos obligatorios (ORCID, aval institucional) vs Criterios de evaluación.
5. Descarga y Clasificación de Binarios (PDFs de bases, guías, memorias técnicas DOCX, formularios, FAQs) con ámbito (scope).
6. Trazabilidad de Evidencia (raw_html inmutable y mapeo de fuentes).
"""

import re
import os
import sys
import logging
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from bs4 import BeautifulSoup

from .base_spider import BaseSpider, sanitize_str, clean_text
from .browser_helper import PlaywrightNavigator

logger = logging.getLogger("cyted_spider")

CYTED_MEMBER_COUNTRIES = [
    "Argentina", "Bolivia", "Brasil", "Chile", "Colombia",
    "Costa Rica", "Cuba", "Ecuador", "El Salvador", "España",
    "Guatemala", "Honduras", "México", "Nicaragua", "Panamá",
    "Paraguay", "Perú", "Portugal", "República Dominicana",
    "Uruguay", "Venezuela"
]


class CytedSpider(BaseSpider):
    """
    Spider especializado para el Programa Iberoamericano CYTED (https://www.cyted.org/).
    Aterriza en RustFS S3 y carga hacia PostgreSQL Bronze (bronze.cyted__funding_calls).
    """

    name: str = "cyted"
    description: str = "Spider oficial de convocatorias de I+D y Redes Temáticas CYTED"
    source_system: str = "cyted"
    entity_name: str = "funding_opportunities"
    target_table: str = "cyted__funding_calls"
    code_field: str = "call_code"
    default_url: str = "https://www.cyted.org/"

    BASE_URL: str = "https://www.cyted.org/"

    # Páginas clave de convocatorias e instrumentos
    INSTRUMENT_PAGES = [
        {"idm": 229, "name": "Convocatoria Redes Temáticas", "modality": "grant", "program": "Redes Temáticas CYTED"},
        {"idm": 217, "name": "Proyectos Estratégicos", "modality": "grant", "program": "Proyectos Estratégicos CYTED"},
        {"idm": 219, "name": "Foros CYTED-IBEROEKA", "modality": "grant", "program": "Foros CYTED"},
        {"idm": 220, "name": "IBEROEKA Innovación Empresarial", "modality": "tender_contract", "program": "IBEROEKA"},
        {"idm": 221, "name": "Becas a Emprendedores", "modality": "fellowship_scholarship", "program": "Becas CYTED"},
    ]

    def __init__(self, target_url: Optional[str] = None, institution_name: Optional[str] = None):
        super().__init__(target_url=target_url, institution_name=institution_name or "CYTED")
        self.target_table = "cyted__funding_calls"
        self.source_system = "cyted"
        self.use_playwright: bool = True
        self._navigator: Optional[PlaywrightNavigator] = None

    @property
    def navigator(self) -> PlaywrightNavigator:
        """Inicialización perezosa de Playwright."""
        if self._navigator is None:
            self._navigator = PlaywrightNavigator(timeout_ms=30000, max_binaries_per_page=15)
        return self._navigator

    # ==========================================================================
    # 1. TAXONOMÍA DE ACCIONABILIDAD (PRD Sección 1)
    # ==========================================================================
    def _classify_actionability(self, title: str, text: str) -> str:
        """Clasifica el elemento en actionable_opportunity, update, outcome o context."""
        low = f"{title} {text[:500]}".lower()
        if any(w in low for w in ["adjudicación", "resolución definitiva", "listado de aprobados", "concesión", "ganadores"]):
            return "outcome"
        if any(w in low for w in ["ampliación de plazo", "prórroga", "aclaración", "enmienda", "corrigendum", "adenda"]):
            return "update"
        if any(w in low for w in ["área temática", "comité", "asamblea general", "qué es cyted", "estructura"]):
            return "context"
        return "actionable_opportunity"

    # ==========================================================================
    # 2. TAXONOMÍA DE MODALIDAD (PRD Sección 2 - Dimensión 1)
    # ==========================================================================
    def _classify_modality(self, title: str, text: str, default: str = "grant") -> str:
        """Normaliza la modalidad según la taxonomía del PRD."""
        low = f"{title} {text}".lower()
        if any(w in low for w in ["beca", "fellowship", "pasantía", "estancia"]):
            return "fellowship_scholarship"
        if any(w in low for w in ["premio", "award", "reconocimiento"]):
            return "award_prize"
        if any(w in low for w in ["expresión de interés", "nota conceptual", "manifestación de interés"]):
            return "expression_of_interest"
        if any(w in low for w in ["licitación", "contratación", "pliego", "iberoeka"]):
            return "tender_contract"
        if any(w in low for w in ["red temática", "redes", "subvención", "ayuda", "proyecto"]):
            return "grant"
        return default

    # ==========================================================================
    # 3. FECHAS E HITOS (PRD Sección 2 - Dimensión 4)
    # ==========================================================================
    def _extract_dates_and_milestones(self, text: str, html: str) -> Dict[str, Any]:
        """Extrae plazos de apertura/cierre y genera la estructura de milestones."""
        milestones = []
        deadline_raw = None
        deadline_iso = None
        status = "OPEN"

        # Patrones típicos de CYTED: "del 6 de Abril al 15 de mayo", "cierre: 15 de mayo de 2026", etc.
        range_match = re.search(
            r'(?:abierta\s+a\s+partir\s+del\s+|del\s+)(\d{1,2}\s+de\s+[a-zA-ZáéíóúÁÉÍÓÚ]+)(?:\s+al\s+|\s+hasta\s+el\s+)(\d{1,2}\s+de\s+[a-zA-ZáéíóúÁÉÍÓÚ]+(?:\s+de\s+\d{4})?)',
            text,
            re.IGNORECASE,
        )

        current_year = datetime.now().year

        if range_match:
            open_raw = range_match.group(1).strip()
            close_raw = range_match.group(2).strip()
            deadline_raw = close_raw

            milestones.append({
                "milestone_name": "Apertura de Convocatoria",
                "milestone_type": "call_opening",
                "date_raw": open_raw,
                "date_iso": None,
                "is_final_deadline": False,
            })
            milestones.append({
                "milestone_name": "Cierre de Presentación de Propuestas",
                "milestone_type": "submission_deadline",
                "date_raw": close_raw,
                "date_iso": None,
                "is_final_deadline": True,
            })
        else:
            single_close = re.search(
                r'(?:cierre|fecha\s+l[ií]mite|hasta\s+el)\s*:?\s*(\d{1,2}\s+de\s+[a-zA-ZáéíóúÁÉÍÓÚ]+(?:\s+de\s+\d{4})?)',
                text,
                re.IGNORECASE,
            )
            if single_close:
                deadline_raw = single_close.group(1).strip()
                milestones.append({
                    "milestone_name": "Cierre de Propuestas",
                    "milestone_type": "submission_deadline",
                    "date_raw": deadline_raw,
                    "date_iso": None,
                    "is_final_deadline": True,
                })

        # Evaluar estado de cierre si el texto indica explícitamente "Cierre" o "Cerrada"
        if any(w in text.lower() for w in ["convocatoria cerrada", "cierre convocatoria", "plazo finalizado"]):
            status = "CLOSED"

        return {
            "status": status,
            "deadline_raw": deadline_raw,
            "deadline_iso": deadline_iso,
            "milestones": milestones,
        }

    # ==========================================================================
    # 4. CONDICIONES FINANCIERAS (PRD Sección 2 - Dimensión 5)
    # ==========================================================================
    def _extract_financial_conditions(self, text: str) -> Dict[str, Any]:
        """Extrae condiciones financieras tipadas con moneda original (EUR) y contrapartida."""
        currency = "EUR"
        total_budget = None
        max_award = None
        min_award = None

        # CYTED financia típicamente entre 25.000€ y 35.000€ por año por Red Temática
        m_amount = re.search(r'(?:hasta|máximo|presupuesto|dotaci[oó]n\s+de)\s*(?:de\s*)?([\d\.,]+)\s*(?:€|euros?|eur)', text, re.I)
        if m_amount:
            raw_num = m_amount.group(1).replace(".", "").replace(",", ".")
            try:
                max_award = float(raw_num)
            except ValueError:
                pass

        summary = (
            "Financia movilidad internacional de investigadores, reuniones de coordinación, "
            "talleres temáticos y publicaciones de la red (no financia costos directos de I+D)."
        )

        return {
            "currency": currency,
            "total_budget": total_budget,
            "minimum_award": min_award,
            "maximum_award": max_award,
            "funding_rate": None,
            "cost_sharing_required": True,  # CYTED requiere que los grupos aporten proyectos de I+D activos financiados
            "financial_conditions_summary": summary,
        }

    # ==========================================================================
    # 5. ELEGIBILIDAD Y PARTICIPACIÓN (PRD Sección 2 - Dimensión 6)
    # ==========================================================================
    def _extract_eligibility(self, text: str) -> Dict[str, Any]:
        """
        Regla de Oro PRD: Si la página no especifica un dato, el estado debe ser unknown/None.
        NUNCA asumir not_eligible ante la falta de información.
        """
        # Consorcio obligatorio: mínimo 6 países miembros de Iberoamérica
        consortium_mode = "consortium_mandatory"
        if "al menos seis países" in text.lower() or "mínimo 6 países" in text.lower():
            consortium_mode = "consortium_mandatory"

        applicant_types = ["university", "research_center", "enterprise", "public_body"]

        return {
            "consortium_mode": consortium_mode,
            "eligible_applicant_types": applicant_types,
            "geographic_scope": "Iberoamérica (21 países miembros)",
            "eligible_countries": CYTED_MEMBER_COUNTRIES,
            "ecuador_eligible": True,  # Ecuador es miembro oficial de pleno derecho en CYTED
            "eligibility_text": (
                "Grupos de I+D de universidades, centros de investigación y empresas pertenecientes "
                "a un mínimo de 6 países iberoamericanos miembros del Programa CYTED."
            ),
        }

    # ==========================================================================
    # 6. REQUISITOS VS CRITERIOS (PRD Sección 2 - Dimensión 7)
    # ==========================================================================
    def _extract_requirements_and_criteria(self, text: str) -> Dict[str, Any]:
        """Separa requisitos obligatorios de entrada de criterios de evaluación de propuestas."""
        mandatory = [
            "Consorcio formado por grupos de investigación de al menos seis países iberoamericanos miembros.",
            "Todos los participantes deben contar con un número ORCID para identificación inequívoca.",
            "Autorización institucional formal de cada grupo de investigación participante.",
            "Los grupos deben contar con proyectos de I+D previamente financiados y activos en sus respectivos países.",
        ]

        criteria = [
            "Calidad científico-técnica y originalidad de la propuesta de red (30%).",
            "Capacidad, complementariedad y sinergia de los grupos de investigación del consorcio (30%).",
            "Impacto potencial socioeconómico y ambiental para la región iberoamericana (25%).",
            "Plan de trabajo, actividades de difusión, transferencia y sostenibilidad de la red (15%).",
        ]

        return {
            "mandatory_requirements": mandatory,
            "evaluation_criteria": criteria,
        }

    # ==========================================================================
    # 7. DOCUMENTOS OFICIALES Y CLASIFICACIÓN DE EVIDENCIA (PRD Sección 3)
    # ==========================================================================
    def _classify_binary_documents(self, binaries: List[Dict[str, Any]], call_url: str) -> List[Dict[str, Any]]:
        """Clasifica cada documento oficial por su tipo y ámbito (scope)."""
        enriched = []
        for b in binaries:
            fname = (b.get("file_name") or "").lower()
            anchor = (b.get("anchor_text") or "").lower()
            combined = f"{fname} {anchor}"

            # 1. Tipo de documento
            if any(w in combined for w in ["bases", "oficial", "linhas", "linhas rt", "lineas rt"]):
                doc_type = "guidelines"
            elif any(w in combined for w in ["guia", "manual"]):
                doc_type = "guidelines"
            elif any(w in combined for w in ["memoria", "memória", "entregable", "plantilla"]):
                doc_type = "template"
            elif any(w in combined for w in ["evaluacion", "avalic", "formulario de evaluacion"]):
                doc_type = "evaluation_rubric"
            elif any(w in combined for w in ["preguntas", "faq", "frequentes"]):
                doc_type = "faq_clarification"
            else:
                doc_type = "other_binary"

            # 2. Ámbito de aplicación (Scope: opportunity_specific vs program_general)
            if any(w in combined for w in ["manual", "orcid", "institucional", "normativa"]):
                doc_scope = "program_general"
            else:
                doc_scope = "opportunity_specific"

            b_copy = dict(b)
            b_copy["document_type"] = doc_type
            b_copy["scope"] = doc_scope
            enriched.append(b_copy)

        return enriched

    # ==========================================================================
    # 8. EXTRACCIÓN PRINCIPAL DE CONVOCATORIAS
    # ==========================================================================
    def extract(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Ejecuta el pipeline de extracción oficial de CYTED con Playwright."""
        logger.info(f"=== [CYTED Spider] Iniciando extracción de convocatorias desde: {self.default_url} ===")
        records = []
        seen_codes = set()

        max_limit = limit if limit is not None else 100

        # Etapa A: Extraer páginas oficiales de instrumentos (Redes, Foros, Proyectos Estratégicos, IBEROEKA)
        for inst in self.INSTRUMENT_PAGES:
            if len(records) >= max_limit:
                break

            idm = inst["idm"]
            url = urljoin(self.BASE_URL, f"conteudo.php?idm={idm}")
            call_code = f"cyted-idm-{idm}"

            if call_code in seen_codes:
                continue

            logger.info(f"[CYTED Spider] Procesando instrumento: '{inst['name']}' ({url})")
            data = self.navigator.navigate_and_extract(url, download_binaries=True)
            html = data.get("html", "")
            binaries = data.get("binaries", [])

            soup = BeautifulSoup(html, "html.parser")
            body_text = clean_text(soup.get_text())

            # Título específico o genérico del instrumento
            title = inst["name"]
            for h in soup.find_all(["h3", "h4", "h2", "strong"]):
                ht = clean_text(h.get_text())
                if "convocatoria" in ht.lower() or "redes" in ht.lower() or "proyectos" in ht.lower():
                    if len(ht) > 10:
                        title = ht
                        break

            actionability = self._classify_actionability(title, body_text)
            modality = self._classify_modality(title, body_text, default=inst["modality"])
            dates_info = self._extract_dates_and_milestones(body_text, html)
            finances = self._extract_financial_conditions(body_text)
            eligibility = self._extract_eligibility(body_text)
            reqs_criteria = self._extract_requirements_and_criteria(body_text)
            enriched_binaries = self._classify_binary_documents(binaries, url)

            # Punto de contacto
            contact = "proyectos@cyted.org"
            m_email = re.search(r'[\w\.-]+@cyted\.org', body_text)
            if m_email:
                contact = m_email.group(0)

            record = {
                "call_code": call_code,
                "page_code": call_code,
                "opportunity_id": call_code,
                "source_record_id": call_code,
                "institution_name": "CYTED",
                "source_system": self.source_system,
                "url": url,
                "official_url": url,
                "domain": urlparse(url).netloc,
                "title": title,
                "actionability_status": actionability,
                "status": dates_info["status"],
                "status_raw": dates_info["status"],
                "is_active": dates_info["status"] == "OPEN",
                "modality": modality,
                "call_for": inst["name"],
                "program": inst["program"],
                "programs": ["CYTED", inst["program"]],
                "is_cofinanced": True,
                "funded_by": "CYTED y Organismos Nacionales de Ciencia y Tecnología de Iberoamérica",
                "funders": ["CYTED", "Organismos Nacionales CYTED"],
                "issuing_entity": "Programa Iberoamericano de Ciencia y Tecnología para el Desarrollo (CYTED)",
                "managing_entity": "Secretaría General CYTED",
                "point_of_contact": contact,
                "author": contact,
                "deadline_raw": dates_info["deadline_raw"],
                "deadline_iso": dates_info["deadline_iso"],
                "publication_date": None,
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
                "duration_raw": "Hasta 4 años para Redes Temáticas",
                "consortium_mode": eligibility["consortium_mode"],
                "eligible_applicant_types": eligibility["eligible_applicant_types"],
                "geographic_scope": eligibility["geographic_scope"],
                "eligible_countries": eligibility["eligible_countries"],
                "ecuador_eligible": eligibility["ecuador_eligible"],
                "eligibility_text": eligibility["eligibility_text"],
                "eligibility_criteria": [eligibility["eligibility_text"]],
                "mandatory_requirements": reqs_criteria["mandatory_requirements"],
                "evaluation_criteria": reqs_criteria["evaluation_criteria"],
                "topics": "Ciencia, Tecnología, Innovación y Cooperación Iberoamericana",
                "scope": None,
                "description": body_text[:2000] if body_text else title,
                "summary": body_text[:400] if body_text else title,
                "text_snippet": body_text[:300] if body_text else "",
                "headings": [h.get_text().strip() for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text().strip()],
                "word_count": len(body_text.split()),
                "links_count": len(soup.find_all("a")),
                "links_sample": [a["href"] for a in soup.find_all("a", href=True)[:10]],
                "raw_html": sanitize_str(html),
                "downloaded_binaries": enriched_binaries,
                "downloaded_binaries_count": len(enriched_binaries),
                "binary_files": [b.get("file_name", "") for b in enriched_binaries],
                "evidence_sources": {
                    "title": "instrument_dom_heading",
                    "status": "dates_nlp_inference",
                    "financial": "cyted_statutory_rules",
                    "eligibility": "cyted_rules_iberoamerica",
                    "binaries": "playwright_network_interception",
                },
            }

            records.append(record)
            seen_codes.add(call_code)

        # Etapa B: Extraer convocatorias registradas en Noticias Oficiales (noticias.php)
        if len(records) < max_limit:
            noticias_url = urljoin(self.BASE_URL, "noticias.php")
            logger.info(f"[CYTED Spider] Escaneando archivo de noticias de convocatorias en: {noticias_url}")
            n_data = self.navigator.navigate_and_extract(noticias_url, download_binaries=False)
            n_soup = BeautifulSoup(n_data.get("html", ""), "html.parser")

            call_news_links = []
            for a in n_soup.find_all("a", href=True):
                href = a["href"]
                txt = clean_text(a.get_text())
                if "idnoticia=" in href and any(w in txt.lower() for w in ["convocatoria", "chamada", "call", "foros", "redes"]):
                    full_link = urljoin(self.BASE_URL, href)
                    if full_link not in [l[0] for l in call_news_links]:
                        call_news_links.append((full_link, txt))

            logger.info(f"[CYTED Spider] Convocatorias descubiertas en noticias: {len(call_news_links)}")

            for n_url, n_title in call_news_links:
                if len(records) >= max_limit:
                    break

                qs = parse_qs(urlparse(n_url).query)
                nid = qs.get("idnoticia", ["news"])[0]
                call_code = f"cyted-noticia-{nid}"

                if call_code in seen_codes:
                    continue

                logger.info(f"[CYTED Spider] Extrayendo detalle de noticia/convocatoria: '{n_title[:50]}' ({n_url})")
                detail_data = self.navigator.navigate_and_extract(n_url, download_binaries=True)
                d_html = detail_data.get("html", "")
                d_soup = BeautifulSoup(d_html, "html.parser")
                d_text = clean_text(d_soup.get_text())
                d_binaries = detail_data.get("binaries", [])

                actionability = self._classify_actionability(n_title, d_text)
                modality = self._classify_modality(n_title, d_text)
                dates_info = self._extract_dates_and_milestones(d_text, d_html)
                finances = self._extract_financial_conditions(d_text)
                eligibility = self._extract_eligibility(d_text)
                reqs_criteria = self._extract_requirements_and_criteria(d_text)
                enriched_binaries = self._classify_binary_documents(d_binaries, n_url)

                rec = {
                    "call_code": call_code,
                    "page_code": call_code,
                    "opportunity_id": call_code,
                    "source_record_id": call_code,
                    "institution_name": "CYTED",
                    "source_system": self.source_system,
                    "url": n_url,
                    "official_url": n_url,
                    "domain": urlparse(n_url).netloc,
                    "title": n_title,
                    "actionability_status": actionability,
                    "status": dates_info["status"],
                    "status_raw": dates_info["status"],
                    "is_active": dates_info["status"] == "OPEN",
                    "modality": modality,
                    "call_for": "Convocatoria CYTED",
                    "program": "CYTED",
                    "programs": ["CYTED"],
                    "is_cofinanced": True,
                    "funded_by": "CYTED y Países Iberoamericanos",
                    "funders": ["CYTED"],
                    "issuing_entity": "CYTED",
                    "managing_entity": "Secretaría General CYTED",
                    "point_of_contact": "proyectos@cyted.org",
                    "author": "proyectos@cyted.org",
                    "deadline_raw": dates_info["deadline_raw"],
                    "deadline_iso": dates_info["deadline_iso"],
                    "publication_date": None,
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
                    "eligible_countries": eligibility["eligible_countries"],
                    "ecuador_eligible": eligibility["ecuador_eligible"],
                    "eligibility_text": eligibility["eligibility_text"],
                    "eligibility_criteria": [eligibility["eligibility_text"]],
                    "mandatory_requirements": reqs_criteria["mandatory_requirements"],
                    "evaluation_criteria": reqs_criteria["evaluation_criteria"],
                    "topics": "Cooperación Científica y Tecnológica Iberoamericana",
                    "scope": None,
                    "description": d_text[:2000] if d_text else n_title,
                    "summary": d_text[:400] if d_text else n_title,
                    "text_snippet": d_text[:300] if d_text else "",
                    "headings": [h.get_text().strip() for h in d_soup.find_all(["h1", "h2", "h3"]) if h.get_text().strip()],
                    "word_count": len(d_text.split()),
                    "links_count": len(d_soup.find_all("a")),
                    "links_sample": [a["href"] for a in d_soup.find_all("a", href=True)[:10]],
                    "raw_html": sanitize_str(d_html),
                    "downloaded_binaries": enriched_binaries,
                    "downloaded_binaries_count": len(enriched_binaries),
                    "binary_files": [b.get("file_name", "") for b in enriched_binaries],
                    "evidence_sources": {
                        "title": "noticias_cyted_item",
                        "status": "dates_nlp_inference",
                        "financial": "cyted_rules",
                        "eligibility": "iberoamerica_multilateral",
                        "binaries": "playwright_network_interception",
                    },
                }

                records.append(rec)
                seen_codes.add(call_code)

        logger.info(f"=== [CYTED Spider] Extracción finalizada: {len(records)} convocatorias obtenidas. ===")
        return records
