  ### 1. Principios del Scraper por cada Pagina (Adquisicion de Datos)
  El documento establece que el scraper es un componente de adquisicion independiente cuya unica funcion es capturar la
  verdad de la fuente, sin emitir juicios ni recomendaciones:

  • Admision por Accionabilidad (Unidad Candidata):
      • No todo lo que hay en una pagina es una "Oportunidad". Antes de guardarlo, clasifica el elemento en:
          • actionable_opportunity: Solo si un postulante puede tomar la decisión concreta de aplicar/ofertar de forma
          independiente (tiene plazos, requisitos o presupuestos propios).
          • context: Es un contenedor (un programa macro, una convocatoria que solo agrupa tópicos).
          • update: Enmiendas, aclaraciones, extensiones de plazo.
          • outcome: Adjudicaciones o contratos cerrados (no son oportunidades para postular).
      • Ejemplo: Si una convocatoria europea tiene varios Topics o una licitación tiene varios Lotes, cada lote/tópico con
      presupuesto propio es una Oportunidad independiente; la convocatoria padre es su Contexto de Oportunidad.
  • Identidad y Trazabilidad:
      • El título NO es la identidad: Nunca uses el título como clave primaria; dos convocatorias con títulos similares
      pueden ser distintas. Conserva siempre el ID oficial de la fuente (call_id, notice_id, etc.).
      • Guarda la URL oficial exacta de origen y la fecha/hora de la captura.
  • Respeto a la Fuente y Multilingüismo:
      • Conserva títulos, resúmenes y descripciones en su idioma original.
      • Conserva montos económicos en su moneda original (USD, CAD, EUR). No apliques conversiones de divisas en el scraper.
  • Preservación Cruda (Data Lake / S3 / RustFS):
      • Guarda el payload crudo íntegro (JSON o HTML de la página) en el almacenamiento de objetos antes de transformar.
  ──────
  ### 2. Información Específica que Debes Extraer
  El modelo conceptual divide los atributos en hechos estructurados y verificables:
   Dimensión                    │ Qué debes extraer de la página             │ Regla de Oro del PRD
  ──────────────────────────────┼────────────────────────────────────────────┼─────────────────────────────────────────────
   Identidad y Estado           │ ID oficial de la fuente, título, resumen,  │ Una oportunidad cerrada no se elimina; se
                                │ modalidad (grant, licitación, premio,      │ conserva para trazabilidad histórica.
                                │ beca, expresión de interés), estado        │
                                │ (abierta, próxima, cerrada, cancelada).    │
   Contextos y Programas        │ Programa o iniciativa a la que pertenece   │ Una oportunidad puede no tener programa o
                                │ la oportunidad.                            │ tener múltiples programas asociados
                                │                                            │ (cofinanciamiento).
   Actores y Roles Contextuales │ Organismos involucrados: Financiador,      │ Los roles son contextuales. Una misma
                                │ emisor, autoridad contratante, entidad     │ entidad puede ser financiadora y gestora a
                                │ gestora.                                   │ la vez.
   Fechas e Hitos               │ No solo apertura y cierre; extraer fechas  │ Los estados "abierta ahora" o "cierra en 5
                                │ de aclaraciones, presentación de cartas de │ días" se calculan dinámicamente; no son
                                │ intención, propuestas completas, fallos.   │ campos fijos.
   Condiciones Financieras      │ Presupuesto total (total_budget), monto    │ Siempre tipadas con su moneda de origen.
                                │ mínimo/máximo (minimum_award,              │
                                │ maximum_award), porcentaje de              │
                                │ financiamiento (funding_rate), contraparte │
                                │ obligatoria (cost_sharing_required).       │
   Elegibilidad y Participación │ • Modalidad: Individual, consorcio         │ Participar vs. Financiamiento: Una entidad
                                │ obligatorio u opcional.• Tipos de          │ puede ser admitida para participar pero no
                                │ solicitante admitidos: Universidad, ONG,   │ tener derecho a recibir fondos.
                                │ empresa, persona natural, etc.•            │
                                │ Elegibilidad geográfica: Países (Ecuador   │
                                │ prioritario), regiones o zonas             │
                                │ específicas.                               │
   Requisitos vs. Criterios     │ • Requisitos: Condiciones obligatorias a   │ No confundir requisitos (obligatorios para
                                │ cumplir (auditorías, certificados,         │ entrar) con criterios de evaluación (cómo
                                │ experiencia mínima).• Criterios de         │ puntúan).
                                │ evaluación: Ponderaciones oficiales (ej.   │
                                │ Excelencia 50%, Impacto 30%).              │

  │ Important
  │ Manejo de Incertidumbre: Si la página no especifica un dato de elegibilidad o fecha, el estado debe ser unknown. El PRD
  │ prohíbe taxativamente asumir not_eligible ante la falta de información.
  ──────
  ### 3. Documentos Oficiales que Debes Descargar (Evidencia)
  El producto no se basa solo en texto web; gran parte de las reglas reales están dentro de los archivos adjuntos.

  #### ¿Qué documentos descargar?

  1. Bases y Guías de la Convocatoria: Terms of Reference (ToR), Call Guidelines, Request for Proposals (RFP).
  2. Pliegos de Contratación: Especificaciones técnicas, términos administrativos.
  3. Formularios y Anexos: Plantillas de presupuesto, modelos de propuesta técnica.
  4. Preguntas Frecuentes y Aclaraciones: FAQs, Addenda, Corrigendum.
  5. Políticas Generales del Programa: Documentos de financiamiento marco.
  #### Metadatos necesarios al descargar cada documento:
  • URL de descarga oficial.
  • Ámbito de aplicación: Indicar si el documento aplica a esa oportunidad específica, a todo el programa o a la agencia en
  general (esto evita volver a descargar la misma política general cientos de veces).
  • Integridad: Calcular y guardar el hash (SHA-256) del archivo descargado.
  ──────
  ### 4. Gobernanza y Normalización (Arquitectura Medallion y Linaje)
  Para que la información cumpla con los estándares institucionales y pueda gobernarse en OpenMetadata:

    [Web Scraper / Fuente Oficial]
           │ (Descarga cruda de HTML/JSON/PDF)
           ▼
    [RustFS S3 / Landing]  ──▶  Conserva archivos originales inmutables con hashes SHA-256
           │ (Ingesta e inserción fiel a la fuente)
           ▼
    [PostgreSQL: Bronze]   ──▶  Tablas raw auditadas (ej. bronze.idrc__funding_calls)
           │ (Normalización declarativa con dbt Core)
           ▼
    [PostgreSQL: Silver]   ──▶  Modelos normalizados (silver.fct_opportunities, dim_*)
           │ (Trazabilidad y linaje de columnas)
           ▼
    [OpenMetadata Catalog] ──▶  Gobierno de datos, linaje visual y catalogo institucional

  #### Trazabilidad de Evidencia:
  Cada hecho derivado (especialmente si en el futuro usas extraccion por IA/LLM o Tika) debe poder responder: ¿Por qué el
  sistema afirma esto?:

  • Indicar el origen: ¿Vino de un campo estructurado de la web, de una regla determinista o de la extracción de un PDF?
  • Guardar la referencia exacta: Documento, página, sección o fragmento textual citado.
  • Registrar el método y modelo: Si intervino IA, registrar el modelo utilizado y el nivel de confianza.
  ──────
  ### 5. Lo que NUNCA debe hacer el Scraper (Fuera de Alcance)

  La Regla de Decisión (Sección 21) define que el producto solo almacena lo que es verdadero sobre la oportunidad
  independientemente de quién la consulte:

NO calcular afinidad: No clasificar si la oportunidad "es buena para CEDIA" o "relevante para tal universidad". Eso le corresponde a las aplicaciones consumidoras de matching.
NO rankear por usuario: No alterar los campos para priorizar investigadores específicos.
NO inventar datos: Si falta información en la web, se cataloga como unknown, conservando la trazabilidad.



Estructura de Datos Objetivo (Contrato para tu Agente)
{
  "unit_type": "actionable_opportunity", 
  "source_metadata": {
    "source_id": "WB-P-123456-PROC-001", 
    "source_url": "https://projects.worldbank.org/en/projects-operations/procurement-detail/...",
    "scraped_at": "2026-10-28T13:00:00Z"
  },
  "identity_and_state": {
    "title": "Procurement of IT Equipment and Software Licenses",
    "summary": "Supply of servers and core licenses for national modernization...",
    "modality": "licitacion_internacional", 
    "status": "abierta" 
  },
  "contexts_and_programs": {
    "parent_program_id": "P123456",
    "parent_program_name": "Digital Ecuador Transformation Project"
  },
  "actors_and_roles": {
    "financiador": "World Bank",
    "emisor": "Ministerio de Telecomunicaciones",
    "autoridad_contratante": "Unidad Ejecutora del Proyecto"
  },
  "dates_and_milestones": {
    "publication_date": "2026-10-15T00:00:00Z",
    "submission_deadline": "2026-12-01T23:59:00Z",
    "clarification_deadline": "2026-11-15T00:00:00Z",
    "award_notice_date": "unknown"
  },
  "financial_conditions": {
    "total_budget": 1500000.00,
    "currency": "USD",
    "minimum_award": "unknown",
    "maximum_award": 1500000.00,
    "funding_rate": 100.0,
    "cost_sharing_required": false
  },
  "eligibility_and_participation": {
    "modality_type": "consorcio_permitido",
    "applicant_types": ["empresa", "joint_venture"],
    "eligible_geographies": ["Ecuador", "Global"]
  },
  "requirements_vs_criteria": {
    "mandatory_requirements": [
      "Experiencia mínima de 5 años en suministro de infraestructura crítica",
      "Certificación ISO 9001 vigente"
    ],
    "evaluation_criteria": [
      { "criterion": "Oferta técnica", "weight_percentage": 70.0 },
      { "criterion": "Oferta económica", "weight_percentage": 30.0 }
    ]
  },
  "official_documents": [
    {
      "doc_name": "Request for Bids (RfB)",
      "download_url": "https://projects.worldbank.org/.../rfb_file.pdf",
      "scope": "opportunity_specific",
      "sha256_hash": "pending_extraction"
    }
  ]
}
