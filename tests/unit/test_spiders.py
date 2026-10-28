"""
Unit Tests: Spider Registry, Instantiation and PRD Extraction Dimensions
"""

import os
import sys
import unittest
from bs4 import BeautifulSoup

# Asegurar que src/extractor esté en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src/extractor")))

from spiders import get_spider, list_spiders, SPIDER_REGISTRY


class TestIDCISpider(unittest.TestCase):
    def test_spider_registry_contains_expected(self):
        """Valida que los spiders especializados idci y cyted estén registrados."""
        self.assertIn("idci", SPIDER_REGISTRY)
        self.assertIn("idrc", SPIDER_REGISTRY)
        self.assertIn("cyted", SPIDER_REGISTRY)
        self.assertNotIn("generic", SPIDER_REGISTRY)

    def test_get_spider_instances(self):
        """Valida que get_spider retorne instancias válidas con metadatos correctos."""
        spider_idci = get_spider("idci")
        self.assertEqual(spider_idci.name, "idci")
        self.assertEqual(spider_idci.target_table, "idrc__funding_calls")
        self.assertEqual(spider_idci.source_system, "idrc")

        spider_idrc = get_spider("idrc")
        self.assertEqual(spider_idrc.name, "idci")
        self.assertEqual(spider_idrc.target_table, "idrc__funding_calls")

        spider_default = get_spider()
        self.assertEqual(spider_default.name, "idci")
        self.assertEqual(spider_default.target_table, "idrc__funding_calls")

    def test_list_spiders_returns_dict(self):
        """Valida el contrato de salida de list_spiders."""
        spiders = list_spiders()
        self.assertIsInstance(spiders, dict)
        self.assertIn("idci", spiders)
        self.assertNotIn("generic", spiders)

    def test_actionability_classification(self):
        """Valida la clasificación de accionabilidad según PRD Sección 1."""
        spider = get_spider("idci")
        self.assertEqual(
            spider._classify_actionability("Call for Proposals", "OPEN", "Proposals", ""),
            "actionable_opportunity",
        )
        self.assertEqual(
            spider._classify_actionability("Addendum 1 - Deadline extended", "OPEN", "Proposals", ""),
            "update",
        )
        self.assertEqual(
            spider._classify_actionability("Selected Grantees Announced", "CLOSED", "", ""),
            "outcome",
        )

    def test_modality_classification(self):
        """Valida la clasificación de modalidad según PRD Sección 2 (Dimensión 1)."""
        spider = get_spider("idci")
        self.assertEqual(
            spider._classify_modality(None, "Call for Applications", "John G. Bene Fellowship", ""),
            "fellowship_scholarship",
        )
        self.assertEqual(
            spider._classify_modality(None, "Concept notes", "Call for concept notes", ""),
            "expression_of_interest",
        )
        self.assertEqual(
            spider._classify_modality("Grant", "Proposals", "Research grants in climate", ""),
            "grant",
        )

    def test_financial_extraction(self):
        """Valida la extracción de condiciones financieras tipadas según PRD Sección 2 (Dimensión 5)."""
        spider = get_spider("idci")
        fin1 = spider._extract_financial_conditions("Up to CAD1,000,000 per project", "No cost-sharing required")
        self.assertEqual(fin1["currency"], "CAD")
        self.assertEqual(fin1["maximum_award"], 1000000)
        self.assertIs(fin1["cost_sharing_required"], False)

        fin2 = spider._extract_financial_conditions("Between CAD 200,000 and CAD 500,000", "Cost-sharing required for private partners")
        self.assertEqual(fin2["currency"], "CAD")
        self.assertEqual(fin2["minimum_award"], 200000)
        self.assertEqual(fin2["maximum_award"], 500000)
        self.assertIs(fin2["cost_sharing_required"], True)

    def test_binary_document_classification(self):
        """Valida la clasificación y asignación de ámbito (scope) según PRD Sección 3."""
        spider = get_spider("idci")
        binaries = [
            {"file_name": "Call_Guidelines_2026.pdf", "anchor_text": "Detailed call document"},
            {"file_name": "Survey_Monkey_Apply_General_Applicant_Guide.pdf", "anchor_text": "Setup guide"},
            {"file_name": "Budget_Template_AnnexA.xlsx", "anchor_text": "Budget model"},
        ]
        enriched = spider._classify_binary_documents(binaries, "https://idrc-crdi.ca/en/funding/test-call")
        self.assertEqual(enriched[0]["document_type"], "guidelines")
        self.assertEqual(enriched[0]["scope"], "opportunity_specific")

        self.assertEqual(enriched[1]["document_type"], "guidelines")
        self.assertEqual(enriched[1]["scope"], "program_general")

        self.assertEqual(enriched[2]["document_type"], "template")
        self.assertEqual(enriched[2]["scope"], "opportunity_specific")

    def test_cyted_spider_instantiation_and_contract(self):
        """Valida que CytedSpider cumpla con los contratos de BaseSpider y PRD."""
        spider = get_spider("cyted")
        self.assertEqual(spider.name, "cyted")
        self.assertEqual(spider.source_system, "cyted")
        self.assertEqual(spider.target_table, "cyted__funding_calls")
        self.assertEqual(spider.code_field, "call_code")

    def test_cyted_actionability_and_modality(self):
        """Valida la clasificación de accionabilidad y modalidad de CYTED."""
        spider = get_spider("cyted")
        self.assertEqual(
            spider._classify_actionability("Convocatoria Redes Temáticas 2026", "Abierta para presentación"),
            "actionable_opportunity",
        )
        self.assertEqual(
            spider._classify_actionability("Resolución definitiva de concesión", "Listado de redes aprobadas"),
            "outcome",
        )
        self.assertEqual(
            spider._classify_modality("Convocatoria Redes", "Asociaciones de grupos I+D"),
            "grant",
        )
        self.assertEqual(
            spider._classify_modality("Becas a emprendedores", "Estancias de investigación"),
            "fellowship_scholarship",
        )

    def test_cyted_eligibility_and_ecuador(self):
        """Valida elegibilidad de consorcio iberoamericano y membresía de Ecuador según PRD."""
        spider = get_spider("cyted")
        elig = spider._extract_eligibility("al menos seis países iberoamericanos miembros")
        self.assertEqual(elig["consortium_mode"], "consortium_mandatory")
        self.assertIn("Ecuador", elig["eligible_countries"])
        self.assertIs(elig["ecuador_eligible"], True)

    def test_cyted_binary_classification(self):
        """Valida la clasificación de documentos descargables de CYTED."""
        spider = get_spider("cyted")
        binaries = [
            {"file_name": "01_Convocatoria_oficial_bases_y_lineas_2026_SP.pdf", "anchor_text": "Bases oficiales"},
            {"file_name": "03_memoria_tecnica_redes_tematicas_SP.docx", "anchor_text": "Memoria Técnica"},
            {"file_name": "04_Formulario_de_evaluacion_externa_SP.pdf", "anchor_text": "Formulario de evaluación"},
            {"file_name": "05_Preguntas_mas_frecuentes_Convocatoria_SP.pdf", "anchor_text": "FAQs"},
        ]
        classified = spider._classify_binary_documents(binaries, "https://www.cyted.org/conteudo.php?idm=229")
        self.assertEqual(classified[0]["document_type"], "guidelines")
        self.assertEqual(classified[0]["scope"], "opportunity_specific")

        self.assertEqual(classified[1]["document_type"], "template")
        self.assertEqual(classified[2]["document_type"], "evaluation_rubric")
        self.assertEqual(classified[3]["document_type"], "faq_clarification")


if __name__ == "__main__":
    unittest.main()
