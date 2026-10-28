#!/usr/bin/env python3
"""
IDCI Spider (Motor Especializado con Cumplimiento Normativo del PRD)
===================================================================
Spider oficial para extraer convocatorias y oportunidades de financiamiento internacional
desde IDCI / IDRC (https://idrc-crdi.ca/en/funding) siguiendo estrictamente las políticas
del documento institucional 'informacion.md':

1. Admisión por Accionabilidad (actionable_opportunity, context, update, outcome).
2. Taxonomía de Identidad, Estado y Modalidad (grant, fellowship, award, tender, etc.).
3. Contextos y Cofinanciamiento (múltiples programas e iniciativas).
4. Actores y Roles Contextuales (funders, issuing_entity, managing_entity, poc).
5. Cronograma e Hitos Temporales (apertura, aclaraciones, propuestas, fallos).
6. Condiciones Financieras Fieles (moneda ISO, total_budget, min/max award, cost-sharing).
7. Elegibilidad y Participación (consorcio, tipos de solicitantes, elegibilidad Ecuador).
8. Requisitos Obligatorios vs Criterios de Evaluación Ponderados.
9. Evidencia y Documentos Oficiales Descargados con Clasificación y Hash SHA-256.
10. Trazabilidad de Evidencia, Gobernanza Medallion y Manejo Estricto de Incertidumbre.
"""

import os
import re
import time
import random
import logging
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup

from .base_spider import BaseSpider, clean_text, sanitize_str, BINARY_EXTENSIONS

logger = logging.getLogger("spider_engine")


class IDCISpider(BaseSpider):
    name: str = "idci"
    description: str = "Spider oficial especializado para convocatorias y oportunidades de IDCI / IDRC"
    source_system: str = "idrc"
    entity_name: str = "funding_opportunities"
    target_table: str = "idrc__funding_calls"
    code_field: str = "call_code"
    default_url: str = "https://idrc-crdi.ca/en/funding"

    BASE_URL: str = "https://idrc-crdi.ca"

    def __init__(self, target_url: Optional[str] = None, institution_name: Optional[str] = None):
        super().__init__(target_url=target_url, institution_name=institution_name)
        # Mantener target_table oficial ('idrc__funding_calls') para IDRC/IDCI por defecto
        if not self.institution_name or self.institution_name.upper() in ("IDRC", "IDCI"):
            self.institution_name = self.institution_name or "IDRC"
            self.target_table = "idrc__funding_calls"
            self.source_system = "idrc"
        elif self.institution_name:
            clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", self.institution_name.lower().strip()).strip("_")
            if clean_slug:
                self.target_table = clean_slug
                self.source_system = clean_slug

    def _is_binary_url(self, url: str) -> bool:
        """Determina si una URL apunta directamente a un archivo binario (PDF, docx, etc.)."""
        clean_path = url.split("?")[0].split("#")[0].lower()
        return clean_path.endswith(BINARY_EXTENSIONS)

    def _generate_page_code(self, url: str) -> str:
        """Genera un código slug identificador seguro y legible a partir de la URL."""
        parsed = urlparse(url)
        path = parsed.path.strip("/").replace("/", "_")
        if not path:
            path = "funding_call"
        raw_slug = path.split("_")[-1] if "_" in path else path
        clean_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_slug)
        return clean_slug[:120].strip("_")

    # ==========================================================================
    # 1. ADMISIÓN POR ACCIONABILIDAD (PRD Sección 1)
    # ==========================================================================
    def _classify_actionability(
        self, title: str, status: str, call_for: Optional[str], text: str
    ) -> str:
        """
        Clasifica el elemento en:
        - actionable_opportunity: Postulante puede tomar la decisión de aplicar con plazos o requisitos propios.
        - context: Contenedor macro (programa o marco de financiamiento sin aplicación directa).
        - update: Enmienda, aclaración, adenda o extensión de plazo.
        - outcome: Adjudicación o contratos ya cerrados (resultados publicados).
        """
        combined = f"{title} {call_for or ''} {text[:500]}".lower()

        if any(w in combined for w in ["corrigendum", "addendum", "deadline extended", "amendment", "erratum"]):
            return "update"
        if any(w in combined for w in ["award recipients", "grantees announced", "selected projects", "contract awarded"]):
            return "outcome"
        if any(w in combined for w in ["funding strategy", "guidance on applying", "managing your funds"]):
            return "context"

        # Por defecto, si tiene plazo o permite postular, es una oportunidad accionable
        return "actionable_opportunity"

    # ==========================================================================
    # 2. TAXONOMÍA DE MODALIDAD (PRD Sección 2 - Dimensión 1)
    # ==========================================================================
    def _classify_modality(
        self, award_type: Optional[str], call_for: Optional[str], title: str, text: str
    ) -> str:
        """
        Normaliza la modalidad según la taxonomía del PRD:
        - grant (subvención / fondos no reembolsables)
        - fellowship_scholarship (beca / pasantía de investigación)
        - award_prize (premio / reconocimiento)
        - tender_contract (licitación / contratación de servicios)
        - expression_of_interest (nota conceptual / manifestación de interés)
        - other (otra modalidad)
        """
        combined = f"{award_type or ''} {call_for or ''} {title} {text[:600]}".lower()

        if any(w in combined for w in ["fellowship", "scholarship", "student award", "doctoral award", "master award"]):
            return "fellowship_scholarship"
        if any(w in combined for w in ["concept note", "expression of interest", "manifestación de interés"]):
            return "expression_of_interest"
        if any(w in combined for w in ["prize", "recognition", "award competition"]):
            return "award_prize"
        if any(w in combined for w in ["tender", "procurement", "request for bids", "request for proposals for services", "rfp"]):
            return "tender_contract"
        if any(w in combined for w in ["grant", "proposals", "research grant", "funding call", "subvención"]):
            return "grant"

        return "other"

    # ==========================================================================
    # 3. CONTEXTOS Y PROGRAMAS (PRD Sección 2 - Dimensión 2)
    # ==========================================================================
    def _extract_programs_and_cofinancing(
        self, soup: BeautifulSoup, html: str, funded_by: Optional[str]
    ) -> Tuple[List[str], bool]:
        """Extrae la lista estructurada de programas asociados y detecta si hay cofinanciamiento."""
        programs = []
        # Buscar en Drupal field-program
        prog_container = soup.find(class_=re.compile(r'field--name-field-program', re.I))
        if prog_container:
            for item in prog_container.find_all(class_=re.compile(r'field__item|entity-reference', re.I)):
                t = clean_text(item.get_text())
                if t and t not in programs:
                    programs.append(t)
            if not programs:
                raw_txt = clean_text(prog_container.get_text())
                raw_txt = re.sub(r'^(?:Programs?|Programas?)\s*', '', raw_txt, flags=re.I).strip()
                if raw_txt:
                    programs.append(raw_txt)

        # Detectar cofinanciamiento
        is_cofinanced = False
        f_by = (funded_by or "").lower()
        if any(sep in f_by for sep in [",", " and ", " y ", "&", "in partnership with"]):
            is_cofinanced = True
        if len(programs) > 1:
            is_cofinanced = True

        return programs, is_cofinanced

    # ==========================================================================
    # 4. ACTORES Y ROLES CONTEXTUALES (PRD Sección 2 - Dimensión 3)
    # ==========================================================================
    def _extract_actors_and_roles(
        self, soup: BeautifulSoup, html: str, funded_by: Optional[str], poc: Optional[str]
    ) -> Dict[str, Any]:
        """
        Extrae y desglosa los actores involucrados según su rol contextual:
        - funders: Organismos que aportan fondos.
        - issuing_entity: Entidad emisora/publicadora oficial.
        - managing_entity: Entidad o secretaría gestora del programa.
        - contracting_authority: Autoridad contratante (en caso de licitaciones).
        - point_of_contact: Contacto oficial.
        """
        funders = []
        if funded_by:
            # Separar por comas, 'and', '&'
            raw_tokens = re.split(r',|\band\b|&', funded_by, flags=re.I)
            for tok in raw_tokens:
                clean_tok = clean_text(tok)
                clean_tok = re.sub(r'^(?:Funded by|Financiado por)\s*', '', clean_tok, flags=re.I).strip()
                if clean_tok and clean_tok not in funders:
                    funders.append(clean_tok)

        if not funders:
            funders = ["IDRC / CRDI"]

        issuing_entity = "IDRC / CRDI (International Development Research Centre)"
        managing_entity = None
        contracting_authority = None

        # Detectar secretaría o gestor específico si se menciona en el texto
        m_manage = re.search(r'(?:managed by|administered by|secretariat:?)\s*([A-Za-z0-9\s,\-\.]+)', html[:3000], re.I)
        if m_manage:
            managing_entity = clean_text(m_manage.group(1))[:100]

        return {
            "funders": funders,
            "issuing_entity": issuing_entity,
            "managing_entity": managing_entity or "IDRC",
            "contracting_authority": contracting_authority,
            "point_of_contact": poc,
        }

    # ==========================================================================
    # 5. FECHAS E HITOS (PRD Sección 2 - Dimensión 4)
    # ==========================================================================
    def _extract_milestones_and_dates(
        self, soup: BeautifulSoup, html: str, deadline_raw: Optional[str], deadline_iso: Optional[str], text: str
    ) -> Dict[str, Any]:
        """
        Extrae cronograma completo: apertura, aclaraciones, cartas de intención,
        propuestas completas y fallos.
        """
        milestones = []
        clarifications_deadline = None
        concept_notes_deadline = None
        full_proposals_deadline = deadline_raw
        results_date = None

        # 1. Hito de Cierre Principal (Deadline)
        if deadline_raw:
            milestones.append({
                "milestone_name": "Submission Deadline (Cierre de Postulación)",
                "milestone_type": "submission_deadline",
                "date_raw": deadline_raw,
                "date_iso": deadline_iso,
                "is_final_deadline": True,
            })

        # 2. Hito de Preguntas / Aclaraciones
        m_qa = re.search(
            r'(?:questions|queries|inquiries|aclaraciones)[^.\n]*?(?:before|until|by|antes del?)\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}(?:\s*(?:at|-)?\s*[\d:]+\s*(?:[ap]\.?m\.?|ET|EDT|UTC))?)',
            text,
            re.I,
        )
        if m_qa:
            clarifications_deadline = clean_text(m_qa.group(1))
            milestones.append({
                "milestone_name": "Clarifications & Inquiries Deadline (Límite de Consultas)",
                "milestone_type": "clarifications_deadline",
                "date_raw": clarifications_deadline,
                "date_iso": None,
                "is_final_deadline": False,
            })

        # 3. Hito de Información / Webinar
        m_webinar = re.search(
            r'(?:information session|webinar|sesión informativa)[^.\n]*?(?:on|el)\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            text,
            re.I,
        )
        if m_webinar:
            milestones.append({
                "milestone_name": "Information Session / Webinar",
                "milestone_type": "information_session",
                "date_raw": clean_text(m_webinar.group(1)),
                "date_iso": None,
                "is_final_deadline": False,
            })

        # 4. Hito de Resultados / Fallos
        m_results = re.search(
            r'(?:notification of results|announcement of results|successful applicants notified|fallo)[^.\n]*?(?:by|in|en)\s*([A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            text,
            re.I,
        )
        if m_results:
            results_date = clean_text(m_results.group(1))
            milestones.append({
                "milestone_name": "Results Announcement (Notificación de Resultados)",
                "milestone_type": "results_announcement",
                "date_raw": results_date,
                "date_iso": None,
                "is_final_deadline": False,
            })

        return {
            "clarifications_deadline": clarifications_deadline,
            "concept_notes_deadline": concept_notes_deadline,
            "full_proposals_deadline": full_proposals_deadline,
            "results_announcement_date": results_date,
            "milestones": milestones,
        }

    # ==========================================================================
    # 6. CONDICIONES FINANCIERAS (PRD Sección 2 - Dimensión 5)
    # ==========================================================================
    def _extract_financial_conditions(self, budget_raw: Optional[str], text: str) -> Dict[str, Any]:
        """
        Extrae montos desglosados en moneda original: total_budget, minimum_award,
        maximum_award, funding_rate y cost_sharing_required.
        """
        if not budget_raw:
            return {
                "currency": "CAD",
                "total_budget": None,
                "minimum_award": None,
                "maximum_award": None,
                "funding_rate": None,
                "cost_sharing_required": None,
                "financial_conditions_summary": "",
            }

        # 1. Moneda de Origen
        curr = "CAD"
        raw_upper = f"{budget_raw} {text[:500]}".upper()
        if "USD" in raw_upper or "US$" in raw_upper:
            curr = "USD"
        elif "EUR" in raw_upper or "€" in raw_upper:
            curr = "EUR"
        elif "GBP" in raw_upper or "£" in raw_upper:
            curr = "GBP"

        # 2. Extracción numérica robusta
        cleaned_budget = re.sub(r'(?i)(CAD|USD|EUR|GBP|CA\$|US\$|\$)', ' ', budget_raw)
        nums = [int(m.replace(',', '')) for m in re.findall(r'\b(?:\d{1,3}(?:,\d{3})+|\d{4,})\b', cleaned_budget)]

        total_budget = None
        min_award = None
        max_award = None

        if nums:
            low_b = budget_raw.lower()
            if "between" in low_b and len(nums) >= 2:
                min_award = min(nums)
                max_award = max(nums)
            elif any(k in low_b for k in ["up to", "maximum", "max", "per project", "per award"]):
                max_award = max(nums)
            elif "total" in low_b:
                total_budget = max(nums)
            else:
                max_award = nums[0]

        # 3. Contraparte obligatoria (cost-sharing)
        cost_sharing_required = None
        low_txt = text.lower()
        if any(w in low_txt for w in ["no cost-sharing", "no cost sharing", "no matching funds", "no co-financing"]):
            cost_sharing_required = False
        elif any(w in low_txt for w in ["cost-sharing", "cost sharing", "matching funds", "co-financing"]):
            cost_sharing_required = True

        # 4. Tasa de financiamiento (funding rate)
        funding_rate = None
        m_rate = re.search(r'(?:funds? up to|covers? up to|financia hasta)\s*(\d{1,3})%', text, re.I)
        if m_rate:
            funding_rate = f"{m_rate.group(1)}%"

        return {
            "currency": curr,
            "total_budget": total_budget,
            "minimum_award": min_award,
            "maximum_award": max_award,
            "funding_rate": funding_rate,
            "cost_sharing_required": cost_sharing_required,
            "financial_conditions_summary": budget_raw,
        }

    # ==========================================================================
    # 7. ELEGIBILIDAD Y PARTICIPACIÓN (PRD Sección 2 - Dimensión 6)
    # ==========================================================================
    def _extract_eligibility(self, soup: BeautifulSoup, text: str) -> Dict[str, Any]:
        """
        Extrae la sección de elegibilidad, tipos de solicitante, modalidad de consorcio
        y evaluación explícita de Ecuador bajo el manejo estricto de incertidumbre.
        """
        # Extraer texto de la sección Eligibility
        elig_text = ""
        for h in soup.find_all(["h2", "h3", "h4"]):
            if "eligib" in h.get_text().lower():
                curr = h.find_next_sibling()
                parts = []
                while curr and curr.name not in ["h2", "h3", "h4"]:
                    t = curr.get_text(" ", strip=True)
                    if t:
                        parts.append(t)
                    curr = curr.find_next_sibling()
                elig_text = " ".join(parts)
                break

        low = (elig_text or text).lower()

        # 1. Tipos de solicitantes admitidos
        applicant_types = []
        if any(w in low for w in ["universit", "higher education"]):
            applicant_types.append("university")
        if any(w in low for w in ["research organization", "research institution", "think tank", "research-focused"]):
            applicant_types.append("research_institution")
        if any(w in low for w in ["ngo", "non-governmental", "civil society", "cso", "not-for-profit"]):
            applicant_types.append("ngo")
        if any(w in low for w in ["private sector", "enterprise", "company", "sme", "start-up"]):
            applicant_types.append("private_sector")
        if any(w in low for w in ["student", "doctoral", "master", "individual researcher", "fellow", "postdoctoral"]):
            applicant_types.append("individual")
        if any(w in low for w in ["government", "public sector", "ministry"]):
            applicant_types.append("government")

        # 2. Modalidad de Consorcio
        consortium_mode = "unknown"
        if any(w in low for w in ["must apply as a consortium", "consortium required", "collaborative teams required", "consortia must"]):
            consortium_mode = "consortium_mandatory"
        elif any(w in low for w in ["consortium", "consortia", "collaboration encouraged", "partnerships welcomed", "joint applications"]):
            consortium_mode = "consortium_optional"
        elif "individual" in applicant_types and len(applicant_types) == 1:
            consortium_mode = "individual_only"

        # 3. Alcance Geográfico y Elegibilidad de Ecuador
        geographic_scope = "Global / General"
        eligible_countries = []
        ecuador_eligible = None  # None = unknown (Regla: Prohibido asumir not_eligible)

        if "ecuador" in low:
            ecuador_eligible = True
            eligible_countries.append("Ecuador")
            geographic_scope = "Latin America / Regional (Incluye Ecuador)"
        elif any(w in low for w in ["latin america", "latin american", "south america", "américa latina"]):
            ecuador_eligible = True
            geographic_scope = "Latin America and the Caribbean (LAC)"
        elif any(w in low for w in ["low- and middle-income countries", "lmics", "developing countries", "global south"]):
            # Ecuador es considerado LMIC / Global South en muchos programas internacionales de IDRC
            geographic_scope = "Low- and Middle-Income Countries (LMICs) / Global South"
            # Si el programa restringe a otra región específica (ej. sólo África o sólo Asia):
            if any(w in low for w in ["african lmics", "in africa", "sub-saharan africa"]) and not ("latin" in low or "global south" in low):
                ecuador_eligible = False
                geographic_scope = "African LMICs"
            elif any(w in low for w in ["only canadians", "canadian university"]) and not ("developing countries" in low or "global south" in low):
                ecuador_eligible = False
                geographic_scope = "Canada"
            else:
                # Regla de Oro: mantener unknown si no se especifica explícitamente lista de países
                ecuador_eligible = None
        elif any(w in low for w in ["only canadians", "canadians and permanent residents"]):
            ecuador_eligible = False
            geographic_scope = "Canada"
        elif any(w in low for w in ["african", "africa"]):
            ecuador_eligible = False
            geographic_scope = "Africa"

        # Criterios estructurados
        eligibility_criteria = []
        if elig_text:
            sentences = [s.strip() for s in elig_text.split(".") if len(s.strip()) > 15]
            eligibility_criteria = sentences[:6]

        return {
            "eligibility_text": clean_text(elig_text)[:3000] if elig_text else "",
            "consortium_mode": consortium_mode,
            "eligible_applicant_types": applicant_types,
            "geographic_scope": geographic_scope,
            "eligible_countries": eligible_countries,
            "ecuador_eligible": ecuador_eligible,
            "eligibility_criteria": eligibility_criteria,
        }

    # ==========================================================================
    # 8. REQUISITOS OBLIGATORIOS VS CRITERIOS DE EVALUACIÓN (PRD Sección 2 - Dimensión 7)
    # ==========================================================================
    def _extract_requirements_and_criteria(self, soup: BeautifulSoup, text: str) -> Dict[str, Any]:
        """
        Distingue requisitos obligatorios eliminatorios (para admitir postulación)
        de criterios de evaluación (cómo puntúan las propuestas).
        """
        mandatory_requirements = []
        evaluation_criteria = []

        low_text = text.lower()

        # Requisitos obligatorios comunes
        if "legally" in low_text and "registered" in low_text:
            mandatory_requirements.append("Personería jurídica / Organización legalmente registrada")
        if "institutional capacity" in low_text:
            mandatory_requirements.append("Capacidad institucional y financiera verificable")
        if "canadian university" in low_text:
            mandatory_requirements.append("Matrícula activa en universidad canadiense admitida")
        if "gender" in low_text:
            mandatory_requirements.append("Consideración de igualdad de género en la propuesta de investigación")

        # Criterios de evaluación
        for h in soup.find_all(["h2", "h3", "h4"]):
            htxt = h.get_text().lower()
            if any(w in htxt for w in ["evaluation criteria", "selection criteria", "criterios de evaluación"]):
                curr = h.find_next_sibling()
                while curr and curr.name not in ["h2", "h3", "h4"]:
                    for li in curr.find_all("li"):
                        t_li = clean_text(li.get_text())
                        if t_li and len(t_li) > 5:
                            evaluation_criteria.append(t_li[:250])
                    curr = curr.find_next_sibling()
                break

        return {
            "mandatory_requirements": mandatory_requirements,
            "evaluation_criteria": evaluation_criteria[:10],
        }

    # ==========================================================================
    # 9. DOCUMENTOS OFICIALES Y METADATOS DE EVIDENCIA (PRD Sección 3)
    # ==========================================================================
    def _classify_binary_documents(self, binaries: List[Dict[str, Any]], call_url: str) -> List[Dict[str, Any]]:
        """
        Enriquece cada binario descargado clasificando su tipo y ámbito de aplicación:
        - document_type: guidelines, template, faq_clarification, procurement, policy, other_binary.
        - scope: opportunity_specific vs program_general.
        """
        enriched = []
        for b in binaries:
            fname = (b.get("file_name") or "").lower()
            anchor = (b.get("anchor_text") or "").lower()
            combined = f"{fname} {anchor}"

            # 1. Tipo de documento
            if any(w in combined for w in ["guideline", "guide", "call for proposal", "tor", "terms of reference", "rfp"]):
                doc_type = "guidelines"
            elif any(w in combined for w in ["template", "form", "budget", "plantilla"]):
                doc_type = "template"
            elif any(w in combined for w in ["faq", "frequently asked", "q&a", "addendum", "corrigendum", "aclaraci"]):
                doc_type = "faq_clarification"
            elif any(w in combined for w in ["procurement", "contract", "pliego"]):
                doc_type = "procurement"
            elif any(w in combined for w in ["policy", "guidance", "manual", "general"]):
                doc_type = "policy"
            else:
                doc_type = "other_binary"

            # 2. Ámbito de aplicación (Scope)
            if any(w in combined for w in ["general applicant guide", "surveymonkey", "setup guide", "institutional policy"]):
                doc_scope = "program_general"
            else:
                doc_scope = "opportunity_specific"

            b_copy = dict(b)
            b_copy["document_type"] = doc_type
            b_copy["scope"] = doc_scope
            enriched.append(b_copy)

        return enriched

    def _extract_field_by_label(self, label: str, soup: BeautifulSoup, html: str) -> Optional[str]:
        """Busca patrones de campos Drupal: etiqueta y su valor adyacente."""
        for lbl_elem in soup.find_all(class_=re.compile(r'(views-label|field__label)', re.I)):
            lbl_text = lbl_elem.get_text()
            if label.lower() in lbl_text.lower():
                parent = lbl_elem.parent
                if parent:
                    content = parent.find(class_=re.compile(r'(field-content|field__item|field--item)', re.I))
                    if content:
                        return clean_text(content.get_text())
                sibling = lbl_elem.find_next_sibling()
                if sibling:
                    return clean_text(sibling.get_text())

        label_slug = label.lower().replace(" ", "-")
        field_container = soup.find(class_=re.compile(rf'field--name-field-(?:award-)?{label_slug}', re.I))
        if field_container:
            val = clean_text(field_container.get_text())
            val = re.sub(rf"^{label}\s*", "", val, flags=re.IGNORECASE)
            val = re.sub(r"^\(?s\)?\s*", "", val, flags=re.IGNORECASE)
            if val:
                return val.strip()

        pattern1 = (
            rf'(?:views-label|field__label)[^>]*>[^<]*{label}[^<]*</span>\s*'
            r'<(?:span|div)[^>]*class=\"[^\"]*field-content[^\"]*\"[^>]*>(.*?)</(?:span|div)>'
        )
        m1 = re.search(pattern1, html, re.IGNORECASE | re.DOTALL)
        if m1:
            return clean_text(m1.group(1))

        pattern2 = rf'<div[^>]*class=\"[^\"]*field--name-field-(?:award-)?{label_slug}[^\"]*\"[^>]*>(.*?)</div>\s*</div>'
        m2 = re.search(pattern2, html, re.IGNORECASE | re.DOTALL)
        if m2:
            val = clean_text(m2.group(1))
            val = re.sub(rf"^{label}\s*", "", val, flags=re.IGNORECASE)
            val = re.sub(r"^\(?s\)?\s*", "", val, flags=re.IGNORECASE)
            return val.strip()

        return None

    def _parse_funding_list(self, html: str, base_url: Optional[str] = None) -> Tuple[List[Dict[str, str]], List[str]]:
        """Extrae las URLs de convocatorias y páginas de paginación del listado usando BeautifulSoup."""
        calls = []
        next_pages = []
        if not html:
            return calls, next_pages

        soup = BeautifulSoup(html, "html.parser")
        base = base_url or self.BASE_URL
        exclude_paths = {
            "/en/funding/applying",
            "/en/funding/resources-idrc-grantees",
            "/en/funding/managing-funds",
            "/en/funding/applying-funding",
            "/en/funding",
            "/en/funding/",
        }
        seen_urls = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            anchor_text = clean_text(a.get_text())
            abs_url = urljoin(base, href)
            parsed = urlparse(abs_url)
            clean_path = parsed.path.rstrip("/")

            if (
                ("/funding/" in abs_url or "/en/funding" in abs_url)
                and clean_path not in [p.rstrip("/") for p in exclude_paths]
                and len(clean_path.split("/")) >= 3
                and abs_url not in seen_urls
            ):
                seen_urls.add(abs_url)
                call_code = clean_path.split("/")[-1]
                calls.append({
                    "url": abs_url,
                    "path": clean_path,
                    "title": anchor_text or call_code,
                    "call_code": call_code,
                })

        # Detección de paginación (Drupal pager: a.pager__link, ?page=X)
        for p_link in soup.find_all("a", href=True):
            href = p_link["href"].strip()
            if "page=" in href:
                abs_page_url = urljoin(base, href)
                if abs_page_url not in next_pages and abs_page_url != base:
                    next_pages.append(abs_page_url)

        logger.info(f"[IDCISpider] Convocatorias descubiertas en la página de listado: {len(calls)}")
        return calls, next_pages

    def _parse_call_details(self, url: str) -> Dict[str, Any]:
        """
        Visita una convocatoria específica y extrae todos sus atributos detallados con Playwright,
        enriqueciendo todas las dimensiones exigidas por 'informacion.md'.
        """
        # Si la URL apunta a un archivo binario directo:
        if self._is_binary_url(url):
            logger.info(f"[IDCISpider] Descargando archivo binario directo: {url}")
            b_meta = self.navigator.download_binary(url)
            if not b_meta:
                return {}
            call_code = self._generate_page_code(url)
            fname = b_meta.get("file_name", "document")
            inst_label = self.institution_name or "IDRC"
            enriched_b = self._classify_binary_documents([b_meta], url)

            return {
                "call_code": call_code,
                "page_code": call_code,
                "opportunity_id": call_code,
                "source_record_id": call_code,
                "institution_name": inst_label,
                "source_system": self.source_system,
                "url": url,
                "official_url": url,
                "domain": urlparse(url).netloc,
                "title": fname,
                "actionability_status": "actionable_opportunity",
                "status": "OPEN",
                "status_raw": "Open",
                "is_active": True,
                "modality": "other",
                "call_for": "Convocatoria Oficial (Documento Adjunto)",
                "program": inst_label,
                "programs": [inst_label],
                "is_cofinanced": False,
                "funded_by": inst_label,
                "funders": [inst_label],
                "issuing_entity": inst_label,
                "managing_entity": inst_label,
                "contracting_authority": None,
                "point_of_contact": None,
                "author": None,
                "deadline_raw": None,
                "deadline_iso": None,
                "publication_date": None,
                "clarifications_deadline": None,
                "concept_notes_deadline": None,
                "full_proposals_deadline": None,
                "results_announcement_date": None,
                "milestones": [],
                "budget_raw": None,
                "currency": "CAD",
                "total_budget": None,
                "minimum_award": None,
                "maximum_award": None,
                "funding_rate": None,
                "cost_sharing_required": None,
                "financial_conditions_summary": "",
                "duration_raw": None,
                "consortium_mode": "unknown",
                "eligible_applicant_types": [],
                "geographic_scope": "General",
                "eligible_countries": [],
                "ecuador_eligible": None,
                "eligibility_text": "",
                "eligibility_criteria": [],
                "mandatory_requirements": [],
                "evaluation_criteria": [],
                "topics": "General",
                "scope": None,
                "description": f"Documento oficial de convocatoria: {fname} ({b_meta.get('content_type')})",
                "summary": f"Archivo binario ({b_meta.get('file_extension')}) tamaño: {b_meta.get('file_size_bytes')} bytes",
                "text_snippet": "",
                "headings": [],
                "word_count": 0,
                "links_count": 0,
                "links_sample": [],
                "raw_html": "",
                "downloaded_binaries": enriched_b,
                "downloaded_binaries_count": 1,
                "binary_files": [fname],
                "evidence_sources": {"source": "direct_binary_url"},
            }

        logger.info(f"[IDCISpider] Extrayendo detalle con Chromium headless: {url}")
        page_res = self.fetch_page_with_browser(url, download_binaries=True)
        html = page_res.get("html", "")
        binaries = page_res.get("binaries", [])

        if not html:
            html = self.fetch_html(url)

        if not html and not binaries:
            return {}

        soup = BeautifulSoup(html, "html.parser")
        domain = urlparse(url).netloc

        # 1. Título
        title = ""
        if soup.h1:
            title = clean_text(soup.h1.get_text())
        if not title and soup.title and soup.title.string:
            title = clean_text(soup.title.string)
        if not title:
            title = page_res.get("title") or ""

        call_code = url.rstrip("/").split("/")[-1].split("?")[0]

        # 2. Atributos estructurados de la cabecera Drupal
        status_raw = self._extract_field_by_label("Status", soup, html)
        if not status_raw:
            if "Closed" in html:
                status_raw = "Closed"
            elif "Open" in html:
                status_raw = "Open"
            else:
                status_raw = "Open"

        status = "OPEN"
        if "closed" in status_raw.lower():
            status = "CLOSED"
        elif any(k in status_raw.lower() for k in ["anticipat", "upcoming"]):
            status = "ANTICIPATORY"
        elif "cancel" in status_raw.lower():
            status = "CANCELLED"

        call_for = (
            self._extract_field_by_label("Call For", soup, html)
            or self._extract_field_by_label("Type", soup, html)
            or "Convocatoria General"
        )
        award_type = self._extract_field_by_label("funding awards type", soup, html)

        deadline_raw = self._extract_field_by_label("Deadline", soup, html)
        budget_raw = self._extract_field_by_label("Budget", soup, html)
        duration_raw = self._extract_field_by_label("Duration", soup, html)
        program = (
            self._extract_field_by_label("Program", soup, html)
            or self._extract_field_by_label("Programs", soup, html)
        )
        funded_by = self._extract_field_by_label("Funded By", soup, html) or "IDRC / CRDI"
        topics = (
            self._extract_field_by_label("Topic", soup, html)
            or self._extract_field_by_label("Topic(s)", soup, html)
        )
        poc = self._extract_field_by_label("Point of contact", soup, html)
        scope = self._extract_field_by_label("Scope", soup, html)

        deadline_iso = None
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag and time_tag.get("datetime"):
            deadline_iso = time_tag["datetime"]
        elif re.search(r'<time[^>]*datetime=\"([^\"]+)\"[^>]*>', html):
            m = re.search(r'<time[^>]*datetime=\"([^\"]+)\"[^>]*>', html)
            if m:
                deadline_iso = m.group(1)

        # 3. Encabezados H1, H2, H3
        headings = []
        for tag in soup.find_all(["h1", "h2", "h3"]):
            txt = clean_text(tag.get_text())
            if txt and len(txt) > 2:
                headings.append({"level": tag.name, "text": txt[:250]})

        # 4. Enlaces descubiertos
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            anchor_text = clean_text(a.get_text())
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            abs_l_url = urljoin(url, href)
            links.append({
                "text": anchor_text[:100] if anchor_text else "Enlace",
                "url": abs_l_url,
                "is_internal": urlparse(abs_l_url).netloc == domain,
            })

        # 5. Cuerpo y texto descriptivo
        body_container = soup.find(class_=re.compile(r'field--name-body', re.I))
        if body_container:
            body_text = clean_text(body_container.get_text())
        else:
            body_text = scope or ""

        if not body_text:
            main_copy = BeautifulSoup(html, "html.parser")
            for junk in main_copy(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
                junk.decompose()
            body_text = clean_text(main_copy.get_text())

        words = body_text.split()
        inst_label = self.institution_name or "IDRC"

        # 6. ENRIQUECIMIENTO NORMATIVO DEL PRD ('informacion.md')
        actionability_status = self._classify_actionability(title, status, call_for, body_text)
        modality = self._classify_modality(award_type, call_for, title, body_text)
        programs, is_cofinanced = self._extract_programs_and_cofinancing(soup, html, funded_by)
        actors = self._extract_actors_and_roles(soup, html, funded_by, poc)
        dates_milestones = self._extract_milestones_and_dates(soup, html, deadline_raw, deadline_iso, body_text)
        financial = self._extract_financial_conditions(budget_raw, body_text)
        eligibility = self._extract_eligibility(soup, body_text)
        reqs_criteria = self._extract_requirements_and_criteria(soup, body_text)
        enriched_binaries = self._classify_binary_documents(binaries, url)

        # Mapa de fuentes de evidencia para gobernanza
        evidence_sources = {
            "title": "h1_dom",
            "status": "drupal_award_status",
            "dates": "drupal_award_deadline_and_time_tag",
            "financial": "drupal_budget_field_and_text_nlp",
            "eligibility": "html_eligibility_heading_section",
            "binaries": "playwright_network_interception",
        }

        return {
            # 1. Identidad y Trazabilidad (PRD Sec. 1 y 2.1)
            "call_code": call_code,
            "page_code": call_code,
            "opportunity_id": call_code,
            "source_record_id": call_code,
            "institution_name": inst_label,
            "source_system": self.source_system,
            "url": url,
            "official_url": url,
            "domain": domain,
            "title": title or call_code,

            # 2. Estado, Accionabilidad y Modalidad (PRD Sec. 1 y 2.1)
            "actionability_status": actionability_status,
            "status": status,
            "status_raw": status_raw,
            "is_active": (status == "OPEN"),
            "modality": modality,
            "opportunity_type": call_for or modality,
            "call_for": call_for,

            # 3. Contextos y Programas (PRD Sec. 2.2)
            "program": program or (programs[0] if programs else inst_label),
            "programs": programs,
            "is_cofinanced": is_cofinanced,

            # 4. Actores y Roles Contextuales (PRD Sec. 2.3)
            "funded_by": funded_by,
            "funders": actors.get("funders", [inst_label]),
            "issuing_entity": actors.get("issuing_entity", "IDRC / CRDI"),
            "managing_entity": actors.get("managing_entity"),
            "contracting_authority": actors.get("contracting_authority"),
            "point_of_contact": poc,
            "author": poc,

            # 5. Fechas e Hitos (PRD Sec. 2.4)
            "deadline_raw": deadline_raw,
            "deadline_iso": deadline_iso,
            "publication_date": dates_milestones.get("publication_date"),
            "clarifications_deadline": dates_milestones.get("clarifications_deadline"),
            "concept_notes_deadline": dates_milestones.get("concept_notes_deadline"),
            "full_proposals_deadline": dates_milestones.get("full_proposals_deadline"),
            "results_announcement_date": dates_milestones.get("results_announcement_date"),
            "milestones": dates_milestones.get("milestones", []),

            # 6. Condiciones Financieras (PRD Sec. 2.5)
            "budget_raw": budget_raw,
            "currency": financial.get("currency", "CAD"),
            "total_budget": financial.get("total_budget"),
            "minimum_award": financial.get("minimum_award"),
            "maximum_award": financial.get("maximum_award"),
            "funding_rate": financial.get("funding_rate"),
            "cost_sharing_required": financial.get("cost_sharing_required"),
            "financial_conditions_summary": financial.get("financial_conditions_summary", budget_raw or ""),
            "duration_raw": duration_raw,

            # 7. Elegibilidad y Participación (PRD Sec. 2.6)
            "consortium_mode": eligibility.get("consortium_mode", "unknown"),
            "eligible_applicant_types": eligibility.get("eligible_applicant_types", []),
            "geographic_scope": eligibility.get("geographic_scope", "General"),
            "eligible_countries": eligibility.get("eligible_countries", []),
            "ecuador_eligible": eligibility.get("ecuador_eligible"),
            "eligibility_text": eligibility.get("eligibility_text", ""),
            "eligibility_criteria": eligibility.get("eligibility_criteria", []),

            # 8. Requisitos vs Criterios (PRD Sec. 2.7)
            "mandatory_requirements": reqs_criteria.get("mandatory_requirements", []),
            "evaluation_criteria": reqs_criteria.get("evaluation_criteria", []),

            # 9. Documentos Oficiales Descargados - Evidencia (PRD Sec. 3)
            "downloaded_binaries": enriched_binaries,
            "downloaded_binaries_count": len(enriched_binaries),
            "binary_files": [b.get("file_name") for b in enriched_binaries],

            # 10. Contenido Textual y Metadatos de Auditoría
            "topics": topics,
            "scope": scope,
            "description": (body_text[:2000] if body_text else None),
            "summary": (body_text[:3500] if body_text else ""),
            "text_snippet": (body_text[:3500] if body_text else ""),
            "headings": headings[:25],
            "word_count": len(words),
            "links_count": len(links),
            "links_sample": links[:30],
            "raw_html": sanitize_str(html),

            # 11. Gobernanza y Linaje (PRD Sec. 4)
            "evidence_sources": evidence_sources,
        }

    def extract(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Extrae el listado y detalle de convocatorias de IDCI / IDRC."""
        start_url = self.target_url or self.default_url
        if not start_url.startswith(("http://", "https://")):
            start_url = f"https://{start_url}"

        clean_path = urlparse(start_url).path.rstrip("/")
        # Si la URL suministrada apunta directamente a una convocatoria individual o a un binario:
        if self._is_binary_url(start_url) or (clean_path and clean_path not in ("/en/funding", "/funding", "")):
            logger.info(f"[IDCISpider] URL directa individual recibida: {start_url}")
            try:
                rec = self._parse_call_details(start_url)
                return [rec] if rec else []
            finally:
                self.close()

        logger.info(f"[IDCISpider] Obteniendo listado de convocatorias desde: {start_url}")
        list_html = self.fetch_html(start_url)
        call_links, next_pages = self._parse_funding_list(list_html, base_url=start_url)

        max_records = limit if limit and limit > 0 else None

        # Paginación si el límite solicitado supera la primera página
        visited_pages = {start_url}
        page_queue = list(next_pages)
        while max_records and len(call_links) < max_records and page_queue:
            next_url = page_queue.pop(0)
            if next_url in visited_pages:
                continue
            visited_pages.add(next_url)
            logger.info(f"[IDCISpider] Explorando página adicional de listado: {next_url}")
            sub_html = self.fetch_html(next_url)
            sub_links, sub_next = self._parse_funding_list(sub_html, base_url=next_url)
            for sl in sub_links:
                if not any(c["url"] == sl["url"] for c in call_links):
                    call_links.append(sl)
            for sn in sub_next:
                if sn not in visited_pages and sn not in page_queue:
                    page_queue.append(sn)

        if max_records is not None:
            call_links = call_links[:max_records]
            logger.info(f"[IDCISpider] Límite de extracción aplicado: {len(call_links)} convocatorias.")

        records = []
        try:
            for idx, item in enumerate(call_links, start=1):
                try:
                    logger.info(f"[IDCISpider] [{idx}/{len(call_links)}] Extrayendo convocatoria: {item['url']}")
                    rec = self._parse_call_details(item["url"])
                    if rec:
                        records.append(rec)
                    time.sleep(random.uniform(0.5, 1.0))
                except Exception as e:
                    logger.error(f"[IDCISpider] Error procesando {item['url']}: {e}")
        finally:
            self.close()

        logger.info(f"[IDCISpider] Extracción completada: {len(records)} convocatorias procesadas exitosamente.")
        return records


# Alias de compatibilidad
IDRCSpider = IDCISpider
