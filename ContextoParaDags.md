worldbank
Para la ingesta del portal de Adquisiciones del Banco Mundial projects.worldbank.org, debes usar un enfoque híbrido: consumir su API REST pública para metadatos estructurados y usar un Scraper (HTML/PDF) para documentos y reglas de elegibilidad.

1. Contexto de Ingesta: Hibrida
Qué ofrece la API (Y sus Endpoints): El Banco Mundial cuenta con APIs públicas que entregan JSON estructurado, ideales para la capa Bronze sin parsear HTML:
Avisos de Adquisiciones (actionable_opportunity / update): [https://search.worldbank.org/api/v2/procnotices?format=json&qterm=*&os=0&rows=100](https://search.worldbank.org/api/v2/procnotices?format=json&qterm=*&os=0&rows=100)
Proyectos Padre (context): [https://search.worldbank.org/api/v2/projects?format=json&id=P123456](https://search.worldbank.org/api/v2/projects?format=json&id=P123456)
Contratos Adjudicados (outcome): [https://search.worldbank.org/api/v2/contractawards?format=json](https://search.worldbank.org/api/v2/contractawards?format=json)
Por qué necesitas el Scraper como complemento obligatorio: La API oficial solo entrega metadatos de cabecera (fechas límite, IDs, país y proyecto). No entrega de forma estructurada los montos estimados por licitación, porcentajes de evaluación, requisitos obligatorios (ej. ISO 9001) ni los enlaces directos a todos los pliegos adjuntos. El scraper debe visitar la URL del aviso (source_url), capturar el HTML íntegro del anuncio y descargar los PDFs (Request for Bids / ToR) hacia RustFS S3 para extraer de ahí las condiciones financieras y criterios reales.
2. Puntos Clave de Arquitectura (Reglas de Ingesta)
Clasificación de Accionabilidad (unit_type):
context: El Proyecto macro (ej. P123456) y los General Procurement Notices (GPN) son solo contenedores informativos.
actionable_opportunity: Solo los Specific Procurement Notices (SPN) y Request for Expressions of Interest (REOI). Si un SPN se divide en varios Lotes con presupuesto propio, cada lote se separa como registro independiente apuntando al mismo parent_program_id.
outcome: Todo registro proveniente del endpoint contractawards.
Preservación en Landing (RustFS S3): Antes de mapear a bronze, guarda tanto el payload JSON del endpoint como el DOM HTML renderizado y los PDFs descargados con su sha256_hash.
Regla de Incertidumbre (unknown): En el Banco Mundial, el presupuesto estimado (total_budget) rara vez está público en adquisiciones de bienes para no sesgar las ofertas; el scraper debe inyectar "unknown" en lugar de asumir 0 o heredar erróneamente el presupuesto total del proyecto padre (P123456).
3. Diccionario de Datos (Mapeo Fuente → Contrato Agente)
Campo del Contrato	Origen Técnico	Campo en Fuente (API / DOM / PDF)	Tipo	Regla de Transformación y Linaje
unit_type	Derivado (Regla)	notice_type (API)	String	Si es SPN/REOI → actionable_opportunity; si es GPN → context; si viene de contractawards → outcome.
source_metadata.source_id	API JSON	id (Notice ID)	String	Clave primaria inmutable (ej. OP00123456). Nunca usar el título.
source_metadata.source_url	API / Scraper	url	String	URL canónica del detalle de la licitación.
identity_and_state.title	API JSON	notice_text / project_name	String	Conservar en idioma original (usualmente EN, ES o FR).
identity_and_state.modality	API JSON	procurement_method_name	String	Mapear códigos oficiales (ej. RFB, QCBS, DIR) sin traducir forzosamente en Bronze.
identity_and_state.status	API / Dinámico	notice_status + submission_date	String	No eliminar cerradas. Calcular estado comparando submission_deadline vs. timestamp actual.
contexts_and_programs.parent_program_id	API JSON	project_id	String	ID oficial del proyecto contenedor (ej. P123456).
actors_and_roles.financiador	Constante / API	"World Bank" (IBRD / IDA)	String	Rol contextual fijo para esta fuente.
actors_and_roles.autoridad_contratante	Scraper (HTML)	contact_organization / borrower	String	Extraer de la sección de contacto de la agencia ejecutora en el aviso.
dates_and_milestones.publication_date	API JSON	noticedate	ISO8601	Normalizar a UTC.
dates_and_milestones.submission_deadline	API JSON	submission_date	ISO8601	Normalizar a UTC. Si no existe (ej. en un GPN), asignar "unknown".
dates_and_milestones.clarification_deadline	Scraper (PDF)	Sección Instructions to Bidders	ISO8601	Extraer vía parser documental/LLM indicando página y cita; si no consta, "unknown".
financial_conditions.total_budget	Scraper (PDF/HTML)	Texto del anuncio o Bid Data Sheet	Float / Str	Atención: No usar el monto del proyecto padre. Si el pliego lo oculta, usar "unknown".
financial_conditions.currency	Scraper (PDF/HTML)	Moneda declarada junto al presupuesto	String	Conservar código ISO original (USD, EUR, etc.) sin convertir.
eligibility_and_participation.*	Scraper (PDF)	Sección Eligible Countries / Bidders	Array	Por defecto en licitaciones internacionales del BM aplica "Global" salvo exclusiones por sanciones; confirmar en el PDF.
requirements_vs_criteria.*	Scraper (PDF)	Sección Evaluation and Qualification	Object	Extraer estrictamente del PDF adjunto registrando documento, página y modelo extractor para linaje en OpenMetadata.
official_documents[]	Scraper (DOM)	Enlaces <a href="*.pdf/*.docx">	Array	Descargar a S3, calcular sha256_hash en ingesta y clasificar scope (opportunity_specific para el RfB, agency_general para regulaciones estándar del BM).


IDRC
Para el portal de financiamiento del IDRC ([https://idrc-crdi.ca/en/funding](https://idrc-crdi.ca/en/funding)), el Web Scraper (HTML + Descarga de Documentos/FAQs) es la estrategia superior y obligatoria, descartando el uso de APIs.

1. Contexto de Ingesta: ¿Por qué Scraper en IDRC

1. Ausencia de API Pública de Convocatorias: El portal del IDRC está construido sobre Drupal (renderizado del lado del servidor - SSR) y tiene deshabilitados o restringidos al público los endpoints de jsonapi para los nodos de convocatorias (funding). Además, la postulación real se externaliza a un portal cerrado (SurveyMonkey Apply) que requiere autenticación y no expone catálogos públicos vía REST.
2. Estructura Semiestructurada en HTML: La página listado (/en/funding) divide limpiamente las convocatorias en dos bloques del DOM: Open calls y Closed calls (con paginación histórica), lo que facilita cumplir la Regla de Oro de no eliminar oportunidades cerradas.
3. Fragmentación de la Evidencia (Web + Subpáginas FAQ + PDFs): En IDRC, la página principal de una convocatoria muestra una tabla lateral de metadatos (Programa, Fecha límite, Presupuesto en texto libre, Países), pero las reglas críticas de elegibilidad, topes de sub-grants (ej. 20% máximo a terceros, 13% costos indirectos) y criterios de evaluación ponderados viven dentro de:
  ⚬ Enlaces a subpáginas HTML de FAQs (ej. /en/funding/frequently-asked-questions-...).
  ⚬ Documentos PDF/Word enlazados en la sección "More details" (Detailed call for proposals document, plantillas Excel de presupuesto).

2. Puntos Clave de Arquitectura para bronze.idrc__funding_calls

⚬ Clasificación de Accionabilidad (unit_type):
  ⚬ actionable_opportunity: Cada enlace hijo dentro de Open calls y Closed calls (ej. John G. Bene Fellowship 2026, Supporting STISA 2034).
  ⚬ Caso Especial (Sub-oportunidades por País): En convocatorias multilaterales del IDRC (como 2026 International Joint Initiative...), el anuncio define techos presupuestarios y monedas distintas según la agencia nacional cofinanciadora (ej. Ghana en GHS, Indonesia en IDR, Zimbabue en USD). El nodo general actúa como context y cada tramo nacional con presupuesto propio puede modelarse o desagregarse en silver conservando el vínculo padre.
  ⚬ update: Las páginas de FAQs adjuntas a cada llamado y los avisos de versión ("Please note that this page will be updated regularly. This version is current as of...").
⚬ Identidad y Trazabilidad (source_id): IDRC no muestra un código alfanumérico visible en el texto del título. Debes extraer el Drupal Node ID (nid) del código fuente HTML (presente en la etiqueta <link rel="shortlink" href="[https://idrc-crdi.ca/en/node/XXXXX](https://idrc-crdi.ca/en/node/XXXXX)"> o clases del <body>) combinado con el slug canónico de la URL (ej. IDRC-NODE-XXXXX).
⚬ Trilingüismo Nativo (EN / FR / ES): El portal publica convocatorias en inglés (/en/), francés (/fr/) y español (/es/), y ocasionalmente adjunta PDFs en portugués. El scraper debe capturar la página en su idioma original sin traducir, vinculando las variantes idiomáticas mediante las etiquetas <link rel="alternate" hreflang="..."> del <head>.
⚬ Moneda Original: IDRC opera principalmente en Dólares Canadienses (CAD), pero en convocatorias conjuntas usa monedas locales o USD. Prohibido convertir en la ingesta.

3. Diccionario de Datos (Mapeo IDRC → Contrato Agente)

Campo del Contrato	Origen Técnico	Selector / Campo en Fuente IDRC	Tipo	Regla de Transformación y Linaje
unit_type	Derivado (Regla)	Estructura de página	String	Convocatorias en listado → actionable_opportunity. Páginas informativas (/en/funding/applying, /managing-funds) → context. Páginas de FAQ específicas → update / evidencia adjunta.
source_metadata.source_id	Scraper (HTML <head>)	<link rel="shortlink"> (node/{id}) o URL slug	String	Extraer el ID numérico interno de Drupal (IDRC-{node_id}). Nunca usar el título.
source_metadata.source_url	Scraper	<link rel="canonical">	String	URL exacta de la convocatoria (ej. [https://idrc-crdi.ca/en/funding/](https://idrc-crdi.ca/en/funding/)...).
identity_and_state.title	Scraper (DOM)	<h1> de la página de detalle	String	Conservar texto íntegro en el idioma de captura.
identity_and_state.summary	Scraper (DOM)	Sección Scope (primeros párrafos)	String	Extraer el texto plano de la sección Scope.
identity_and_state.modality	Scraper (DOM)	Metadato lateral Call for + Type	String	Concatenar o mapear valores de origen: Proposals, Concept notes, Expressions of interest, Letters of interest, Applications (Fellowships) + Grant.
identity_and_state.status	Scraper (DOM) + Regla	Metadato Status (Open / Closed) + Deadline	String	Conservar todas las de la sección Closed calls. Verificar dinámicamente contra la fecha/hora de cierre (ET → UTC).
contexts_and_programs.parent_program_name	Scraper (DOM)	Metadato lateral Programs	Array/Str	Extraer los enlaces/textos bajo Programs (ej. "Global Health", "Education and Science", "Science Granting Councils Initiative (SGCI)").
actors_and_roles.financiador	Scraper (DOM)	Metadato Funded by	Array/Str	Por defecto "International Development Research Centre (IDRC)" + cofinanciadores listados (ej. "Global Affairs Canada (GAC)", "FCDO", "Wellcome").
actors_and_roles.emisor	Constante / DOM	"IDRC" + Point of contact	String	Capturar el correo oficial de Point of contact (ej. SGCSSA@idrc.ca) como metadato de trazabilidad del emisor.
dates_and_milestones.publication_date	Scraper (DOM / Meta)	Meta article:published_time o nota de versión	ISO8601	Si el HTML no expone fecha de publicación en el DOM ni en meta tags, asignar "unknown".
dates_and_milestones.submission_deadline	Scraper (DOM)	Metadato lateral Deadline	ISO8601	Parsear formato "Friday, September 25, 2026 - 23:59 ET" y convertir zona horaria del Este (America/Toronto) a UTC.
dates_and_milestones.clarification_deadline	Scraper (HTML/PDF)	Cuerpo de texto / FAQ	ISO8601	Buscar fechas límite de consultas por correo o fechas de Information Webinars (ej. "contact ... by August 09, 2026"). Si no existe, "unknown".
dates_and_milestones.award_notice_date	Scraper (HTML/PDF)	Cronograma en el cuerpo o PDF	ISO8601	Extraer hito "Applicants Notified of Funding Decisions" (ej. 2027-07-21). Si no se menciona, "unknown".
financial_conditions.total_budget	Scraper (DOM/PDF)	Metadato Budget / PDF	Float/Str	Extraer si se menciona la bolsa global o multiplicar cuando es explícito (ej. "Up to six grants of up to CAD 1.2 million each" → 7200000.00). Si solo da tope por proyecto, dejar total_budget en "unknown".
financial_conditions.currency	Scraper (DOM)	Metadato Budget	String	Extraer código ISO (CAD, USD, GHS, IDR, etc.).
financial_conditions.minimum_award / maximum_award	Scraper (DOM)	Metadato Budget	Float/Str	Parsear rangos como "Ranging from CAD50,000 to CAD300,000" (minimum_award: 50000, maximum_award: 300000) o "up to CAD 1.2 million" (minimum_award: "unknown", maximum_award: 1200000).
financial_conditions.cost_sharing_required	Scraper (FAQ / PDF)	Sección Local contributions / Co-funding en FAQ	Boolean	En IDRC, las Contributory grants exigen "local contributions" (en efectivo o especie). Si el FAQ o PDF no lo detalla aún, colocar "unknown".
eligibility_and_participation.modality_type	Scraper (DOM/PDF)	Sección Eligibility	String	Detectar si exige consorcio ("consortium consisting of one lead... and two to four co-applicant organizations") o permite postulación individual.
eligibility_and_participation.applicant_types	Scraper (DOM/PDF)	Sección Eligibility	Array	Extraer entidades admitidas (usualmente personas jurídicas: universidades, centros de investigación, ONGs; o personas naturales solo en becas como John G. Bene Fellowship).
eligibility_and_participation.eligible_geographies	Scraper (DOM/PDF)	Metadato lateral Countries + Lista en texto	Array	Extraer lista explícita del bloque Countries o texto (ej. países de África Subsahariana o lista DAC de países de ingresos bajos y medios - LMICs, donde entra Ecuador cuando la convocatoria es para el Global South / LAC).
requirements_vs_criteria.mandatory_requirements	Scraper (DOM/PDF/FAQ)	Sección Eligibility + Políticas Generales	Array	Extraer viñetas obligatorias: personalidad jurídica, solvencia financiera, cumplimiento de política STRAC de Canadá, límite de 13% de costos indirectos, etc.
requirements_vs_criteria.evaluation_criteria	Scraper (PDF)	Documento Detailed call for proposals	Array	Los pesos porcentuales de evaluación casi nunca están en el HTML; deben extraerse del PDF de bases adjunto registrando página y modelo en el linaje. Si el PDF no da pesos, "unknown".
official_documents[]	Scraper (DOM)	Sección More details y Applying for funding	Array	Descargar a RustFS S3 con sha256_hash y clasificar el scope:
• opportunity_specific: Detailed call for proposals document (PDF), FAQs de la convocatoria, Budget template (Excel).
• agency_general: General Terms and Conditions for a Grant Agreement, Account setup guide for SurveyMonkey Apply, STRAC Attestation (descargar una sola vez desde /en/funding/applying).

4. Ejemplo de Salida JSON (Contrato Aplicado a un Caso Real de IDRC)

{
  "unit_type": "actionable_opportunity",
  "source_metadata": {
    "source_id": "IDRC-supporting-stisa-2034-sgci-multilateral-research-call",
    "source_url": "https://idrc-crdi.ca/en/funding/supporting-stisa-2034-sgci-multilateral-research-call-advancing-africas-science-technology",
    "scraped_at": "2026-10-28T16:50:00Z"
  },
  "identity_and_state": {
    "title": "Supporting STISA 2034: SGCI Multilateral Research Call advancing Africa's Science, Technology and Innovation priorities",
    "summary": "The SGCI Multilateral Research Call in support of STISA-2034 will fund collaborative, multi-country research projects that advance Africa's science, technology and innovation priorities and contribute to sustainable development outcomes across the continent.",
    "modality": "Expressions of interest - Grant",
    "status": "cerrada"
  },
  "contexts_and_programs": {
    "parent_program_id": "SGCI",
    "parent_program_name": "Education and Science | Science Granting Councils Initiative in Sub-Saharan Africa"
  },
  "actors_and_roles": {
    "financiador": "IDRC, Participating African Science Granting Councils, Government of Norway, FCDO, Wellcome",
    "emisor": "International Development Research Centre (IDRC)",
    "autoridad_contratante": "Science Granting Councils Initiative in Sub-Saharan Africa (SGCSSA@idrc.ca)"
  },
  "dates_and_milestones": {
    "publication_date": "unknown",
    "submission_deadline": "2026-09-26T03:59:00Z",
    "clarification_deadline": "unknown",
    "award_notice_date": "unknown"
  },
  "financial_conditions": {
    "total_budget": "unknown",
    "currency": "CAD",
    "minimum_award": 50000.00,
    "maximum_award": 300000.00,
    "funding_rate": "unknown",
    "cost_sharing_required": "unknown"
  },
  "eligibility_and_participation": {
    "modality_type": "consorcio_obligatorio",
    "applicant_types": ["eligible_institution_types"],
    "eligible_geographies": [
      "Botswana", "Burkina Faso", "Côte d'Ivoire", "Ethiopia", "Ghana", "Kenya",
      "Malawi", "Mozambique", "Namibia", "Nigeria", "Rwanda", "Senegal",
      "Sierra Leone", "South Africa", "Tanzania", "Togo", "Uganda", "Zambia", "Zimbabwe"
    ]
  },
  "requirements_vs_criteria": {
    "mandatory_requirements": [
      "Consortium consisting of one lead applicant organization and two to four co-applicant organizations from participating SGCI countries",
      "Nominate a full-time principal investigator",
      "Demonstrate the capacity to manage research funding",
      "Propose research that aligns with at least one of the call's five thematic streams (Agriculture, Health, AI and Digital technologies, Energy, Environment)"
    ],
    "evaluation_criteria": "unknown"
  },
  "official_documents": [
    {
      "doc_name": "Detailed call for proposals document",
      "download_url": "https://idrc-crdi.ca/sites/default/files/sp/...",
      "scope": "opportunity_specific",
      "sha256_hash": "pending_extraction"
    },
    {
      "doc_name": "Frequently asked questions (FAQ)",
      "download_url": "https://idrc-crdi.ca/en/funding/...",
      "scope": "opportunity_specific",
      "sha256_hash": "pending_extraction"
    },
    {
      "doc_name": "SurveyMonkey Apply Account setup guide",
      "download_url": "https://idrc-crdi.ca/en/funding/applying",
      "scope": "agency_general",
      "sha256_hash": "pending_extraction"
    }
  ]
}


cyted

Para el portal del Programa CYTED ([https://www.cyted.org/](https://www.cyted.org/)), debes utilizar exclusivamente un Web Scraper (HTML + Extracción de PDFs), ya que es una aplicación monolítica en PHP sin API pública.

1. Contexto de Ingesta:  Scraper en CYTED

⚬ Arquitectura Legacy en PHP (Ruralbit): El sitio está construido sobre scripts PHP tradicionales renderizados del lado del servidor (conteudo.php?idm=..., noticias.php, web_redes.php). No cuenta con endpoints REST, GraphQL ni feeds JSON abiertos.
⚬ Reglas de Negocio Encapsuladas en PDFs: Las páginas HTML de CYTED son minimalistas; actúan como meros tableros de anuncios. Los plazos exactos con zona horaria, topes presupuestarios por año, composición mínima de los consorcios y las Líneas de Investigación abiertas se publican dentro de archivos PDF alojados en rutas estáticas (/assets/img/cyted/Convocatoria%202026/...).

2. Puntos Clave de Arquitectura para bronze.cyted__funding_calls

⚬ Clasificación de Accionabilidad (unit_type) — El Modelo de "Líneas Temáticas":
  ⚬ context: La página general de instrumentos (conteudo.php?idm=218 para Redes, idm=229 para la Convocatoria Anual).
  ⚬ actionable_opportunity: En la convocatoria anual de Redes Temáticas, CYTED aprueba líneas específicas divididas en 7 Áreas (Agroalimentación, Salud, Desarrollo Industrial, Desarrollo Sostenible, TIC, Ciencia y Sociedad, Energía; ej. Línea 3.2: Procesos industriales sostenibles con IA o Línea 5.1: Documentación científica en IA de código abierto). Cada línea temática —o cada instrumento independiente como Becas a Emprendedores, Foros Empresa-Academia o Proyectos en Temas Estratégicos— debe registrarse con su propio ID compuesto.
  ⚬ outcome: Los registros en web_redes.php (Listado de Redes Activas, con códigos como 226RT0193 o 225RT0168) son redes ya adjudicadas. No deben mezclarse como oportunidades abiertas, sino ingerirse como outcome para trazabilidad histórica.
⚬ Identidad y Trazabilidad (source_id): Como el HTML usa parámetros genéricos (?idm=229) que se sobrescriben cada año, el scraper nunca debe usar solo el idm como clave primaria. Debe construir un ID determinista combinando el año, el instrumento y el código de línea o noticia: ej. CYTED-2026-RT-LINEA-5.1 o CYTED-NOTICIA-1617.
⚬ Bilingüismo (ES / PT): CYTED opera oficialmente en Español (Castellano) y Portugués. Los documentos PDF suelen duplicarse en carpetas /Castellano/ y /Portugues/. Captura el idioma original sin traducir.
⚬ Moneda Original (EUR): Toda la contabilidad de CYTED (Secretaría General en Madrid) está denominada en Euros (EUR).

3. Diccionario de Datos (Mapeo CYTED → Contrato Agente)

Campo del Contrato	Origen Técnico	Selector / Ubicación en CYTED	Tipo	Regla de Transformación y Linaje
unit_type	Derivado (Regla)	URL / Sección del menú	String	Convocatorias abiertas/cerradas (idm=229 + PDF de bases) → actionable_opportunity. web_redes.php → outcome. Descripción de Áreas → context.
source_metadata.source_id	Derivado (PDF/URL)	Año + Instrumento + Código de Línea / idnoticia	String	Generar clave compuesta inmutable (ej. CYTED-2026-RT-5.1 o CYTED-2026-RT-GENERAL).
source_metadata.source_url	Scraper	[https://www.cyted.org/conteudo.php?idm=229](https://www.cyted.org/conteudo.php?idm=229)	String	Guardar tanto la URL de la página contenedora como la URL directa del PDF de la convocatoria.
identity_and_state.title	Scraper (HTML/PDF)	Título en noticias.php o encabezado de Línea en PDF	String	Ej. "Convocatoria CYTED 2026 - Redes Temáticas (Línea 5.1: Plataforma IA de código abierto)".
identity_and_state.modality	Scraper (DOM)	Menú Instrumentos	String	Valores posibles: Redes Temáticas, Proyectos en Temas Estratégicos, Foros Empresa-Academia, IBEROEKA, Becas a Emprendedores, Redes Eméritas.
identity_and_state.status	Dinámico / Noticias	Fecha de cierre en PDF vs. Reloj UTC	String	Conservar convocatorias pasadas (cerrada). Calcular dinámicamente comparando con la hora de Madrid (Europe/Madrid).
contexts_and_programs.parent_program_name	Scraper (DOM/PDF)	Áreas Temáticas (1 a 7) + ODS	String	Asociar al Área correspondiente (ej. "Área 5: Tecnologías de la Información y Comunicación (TIC)") y etiquetas ODS.
actors_and_roles.financiador	Constante / PDF	"Programa CYTED" + "Organismos Nacionales de Ciencia y Tecnología (ONCYTs)"	String	En Redes Temáticas financia la Secretaría General; en Proyectos Estratégicos cofinancian los ONCYTs de cada país (en Ecuador: SENESCYT / CEDIA como aliado estratégico).
actors_and_roles.autoridad_contratante	Scraper (Footer/PDF)	"Secretaría General CYTED (sgral@cyted.org)"	String	Extraído del pie de página y sección de consultas de la Guía del Solicitante.
dates_and_milestones.publication_date	Scraper (HTML/PDF)	Fecha en noticias.php / apertura en PDF	ISO8601	Convertir la fecha de apertura oficial (ej. 6 de abril de 2026) a formato ISO UTC.
dates_and_milestones.submission_deadline	Scraper (PDF)	Sección 8. Plazo de presentación en PDF	ISO8601	Crítico: Convertir la hora local de Madrid (17:00 h CEST) a UTC (15:00:00Z).
financial_conditions.total_budget	Scraper (PDF)	Sección Financiamiento en PDF	Float/Str	Para una Red Temática de hasta 4 años a razón de 20.000 €/año → 80000.00 (o "unknown" si se evalúa el fondo global de la convocatoria).
financial_conditions.currency	Scraper (PDF)	Símbolo € / texto euros	String	Fijo "EUR".
financial_conditions.maximum_award	Scraper (PDF)	Límite anual / total en Bases	Float	20000.00 (anual para Redes Temáticas, máximo 4 años).
financial_conditions.cost_sharing_required	Scraper (PDF)	Sección Financiamiento / Cofinanciación	Boolean	true (CYTED solo financia movilidad, talleres y coordinación; los grupos deben aportar sus propios costos de I+D y adjuntar cartas de compromiso si hay cofinanciación).
eligibility_and_participation.modality_type	Scraper (PDF)	Sección 2. Solicitantes / Requisitos	String	Fijo "consorcio_obligatorio" (mínimo de grupos e instituciones de diferentes países iberoamericanos).
eligibility_and_participation.applicant_types	Scraper (PDF)	Sección 2. Solicitantes	Array	["universidad", "centro_investigacion", "empresa", "ong"] (Grupos de I+D públicos o privados y empresas de Iberoamérica).
eligibility_and_participation.eligible_geographies	Scraper (DOM/PDF)	Estructura > Organismos Nacionales (22 países)	Array	Lista de los 22 países miembros de CYTED, que incluye explícitamente a Ecuador junto con Argentina, Brasil, Chile, Colombia, España, México, Portugal, Perú, etc.
requirements_vs_criteria.mandatory_requirements	Scraper (PDF)	Documento 01_Convocatoria_oficial_bases...pdf	Array	Extraer del PDF (ej. mínimo 6 grupos de al menos 6 países iberoamericanos distintos, duración máxima 48 meses, no superar 20.000 € el primer año).
requirements_vs_criteria.evaluation_criteria	Scraper (HTML/PDF)	conteudo.php?idm=218 y PDF de Bases	Array	Extraer criterios oficiales (Calidad científico-técnica, Productividad del coordinador/grupos, Viabilidad/sostenibilidad, Adecuación del presupuesto) y sus ponderaciones exactas del PDF.
official_documents[]	Scraper (DOM)	Enlaces en /assets/img/cyted/...	Array	Descargar a RustFS S3 con sha256_hash:
• 01_Convocatoria_oficial_bases_y_lineas_2026_SP.pdf (opportunity_specific)
• 02_Guia_del_solicitante.pdf (opportunity_specific)
• Formularios y Memoria Técnica (opportunity_specific)
• Normativa general en Documentación > Normativa (agency_general).

4. Ejemplo de Salida JSON (Contrato Aplicado a CYTED 2026)

{
  "unit_type": "actionable_opportunity",
  "source_metadata": {
    "source_id": "CYTED-2026-RT-LINEA-5.1",
    "source_url": "https://www.cyted.org/conteudo.php?idm=229",
    "scraped_at": "2026-10-28T16:55:00Z"
  },
  "identity_and_state": {
    "title": "Convocatoria CYTED 2026 - Redes Temáticas: Línea 5.1 Plataforma para integrar documentación científica iberoamericana en una IA de código abierto",
    "summary": "Asociación de grupos de investigación y empresas de Iberoamérica para implementar un sistema de clasificación automática de artículos científicos, análisis de tendencias y colaboración mediante herramientas de IA de código abierto.",
    "modality": "Redes Temáticas (Subvención a la coordinación e intercambio)",
    "status": "cerrada"
  },
  "contexts_and_programs": {
    "parent_program_id": "CYTED-AREA-5-TIC",
    "parent_program_name": "Programa Iberoamericano de Ciencia y Tecnología para el Desarrollo (CYTED) - Área 5: Tecnologías de la Información y Comunicación (TIC)"
  },
  "actors_and_roles": {
    "financiador": "Programa CYTED (Secretaría General y Organismos Nacionales Signatarios)",
    "emisor": "Secretaría General de CYTED",
    "autoridad_contratante": "Secretaría General del Programa CYTED (Madrid, España - sgral@cyted.org)"
  },
  "dates_and_milestones": {
    "publication_date": "2026-04-06T00:00:00Z",
    "submission_deadline": "2026-05-15T15:00:00Z",
    "clarification_deadline": "unknown",
    "award_notice_date": "2026-10-27T00:00:00Z"
  },
  "financial_conditions": {
    "total_budget": 80000.00,
    "currency": "EUR",
    "minimum_award": "unknown",
    "maximum_award": 20000.00,
    "funding_rate": "unknown",
    "cost_sharing_required": true
  },
  "eligibility_and_participation": {
    "modality_type": "consorcio_obligatorio",
    "applicant_types": ["universidad", "centro_investigacion", "empresa"],
    "eligible_geographies": [
      "Argentina", "Bolivia", "Brasil", "Chile", "Colombia", "Costa Rica", "Cuba",
      "Ecuador", "El Salvador", "España", "Guatemala", "Honduras", "México",
      "Nicaragua", "Panamá", "Paraguay", "Perú", "Portugal", "República Dominicana",
      "Uruguay", "Venezuela"
    ]
  },
  "requirements_vs_criteria": {
    "mandatory_requirements": [
      "Duración máxima de 4 años (48 meses)",
      "Ninguna propuesta podrá solicitar más de 20.000 EUR para el primer año",
      "Participación mínima de grupos de investigación/empresas de diferentes países iberoamericanos miembros de CYTED según bases",
      "Presentación exclusiva a través de la plataforma electrónica (Área de Gestión CYTED) con Memoria Técnica y cartas de compromiso de cofinanciación"
    ],
    "evaluation_criteria": [
      { "criterion": "Calidad científico-técnica de la propuesta", "weight_percentage": "unknown" },
      { "criterion": "Calidad y productividad científico-técnica del coordinador y de los grupos de trabajo", "weight_percentage": "unknown" },
      { "criterion": "Viabilidad y sostenibilidad de la propuesta", "weight_percentage": "unknown" },
      { "criterion": "Adecuación del presupuesto", "weight_percentage": "unknown" }
    ]
  },
  "official_documents": [
    {
      "doc_name": "Convocatoria Oficial: Bases y líneas de investigación abiertas 2026",
      "download_url": "https://www.cyted.org/assets/img/cyted/Convocatoria%202026/Castellano/01_Convocatoria_oficial_bases_y_lineas_2026_SP.pdf",
      "scope": "opportunity_specific",
      "sha256_hash": "pending_extraction"
    },
    {
      "doc_name": "Guía del Solicitante (Redes Temáticas)",
      "download_url": "https://www.cyted.org/assets/img/cyted/02.Guia_del_solicitante_2024.pdf",
      "scope": "opportunity_specific",
      "sha256_hash": "pending_extraction"
    }
  ]
}

UN Global Marketplace(UNGM)

Para el portal del Mercado Global de las Naciones Unidas ([https://www.ungm.org/Public/Notice](https://www.ungm.org/Public/Notice)), debes utilizar un Scraper Híbrido (Consumo de Endpoints AJAX internos + Extracción de HTML/PDFs), ya que su API oficial OData v4 es privada para agencias de la ONU.

1. Contexto de Ingesta: API Y Scraper en UNGM

⚬ Por qué NO puedes usar la API Oficial (developer.ungm.org): UNGM cuenta con una API basada en OData v4 ([https://www.ungm.org/API/Notices](https://www.ungm.org/API/Notices)), pero está diseñada para que las agencias de la ONU publiquen avisos desde sus sistemas ERP y exige autenticación OAuth2 (Authorization Code Grant) con una cuenta institucional de funcionario de la ONU (UNGM UN staff user). Los proveedores o sistemas externos no tienen acceso libre de lectura masiva.
⚬ Endpoints Públicos Auxiliares (Sí disponibles sin token): Puedes usar estos endpoints REST públicos para poblar tus catálogos maestros (dim_* en Silver):
  ⚬ Tipos de oportunidad: GET [https://www.ungm.org/API/NoticeTypes](https://www.ungm.org/API/NoticeTypes)
  ⚬ Tipos de competencia: GET [https://www.ungm.org/API/NoticeTypesOfCompetitions](https://www.ungm.org/API/NoticeTypesOfCompetitions)
  ⚬ Niveles de registro exigidos: GET [https://www.ungm.org/API/RegistrationLevels](https://www.ungm.org/API/RegistrationLevels)
⚬ Cómo debe funcionar el Scraper (AJAX + DOM + PDF):
  1. Listado Paginado (Endpoint interno POST): La interfaz de /Public/Notice carga los resultados dinámicamente haciendo una petición POST [https://www.ungm.org/Public/Notice/Search](https://www.ungm.org/Public/Notice/Search) enviando un JSON con filtros (PageIndex, PageSize, IsActive, etc.). Tu scraper debe consultar este endpoint directamente para evitar usar navegadores pesados (Playwright/Selenium) en el paginado.
  2. Detalle del Aviso (GET /Public/Notice/{notice_id}): Cada fila devuelve un ID numérico único (ej. [https://www.ungm.org/Public/Notice/312633](https://www.ungm.org/Public/Notice/312633)). El scraper descarga ese HTML (que se organiza en pestañas: General, Documents, Contacts, Links, UNSPSC codes, Revisions).
  3. Descarga de Pliegos (/Public/Notice/DownloadDocument?...): Gran parte de los requisitos, presupuestos y ponderaciones técnicas viven exclusivamente en los PDFs adjuntos en la pestaña Documents.

2. Puntos Clave de Arquitectura para bronze.ungm__notices

⚬ Clasificación de Accionabilidad (unit_type):
  ⚬ actionable_opportunity: Avisos con tipo Request for proposal (RFP), Invitation to bid (ITB), Request for quotation (RFQ), Grant support - call for proposal, Call for implementing partners, Call for individual consultants y Request for EOI.
  ⚬ context: Avisos tipo Request for information (RFI) o Pre-bid notice (son exploratorios o anuncios previos, aún no adjudican contrato) y los Planes Anuales de Adquisiciones (Procurement Plans).
  ⚬ update: En UNGM, las enmiendas se reflejan agregando un sufijo de versión a la referencia (ej. UNDP-MNE-00888,1 o UNDP-BWA-00311,3) y registrando el cambio en la pestaña Revisions del mismo notice_id.
  ⚬ outcome: Las adjudicaciones se publican en una sección separada ([https://www.ungm.org/Public/ContractAward](https://www.ungm.org/Public/ContractAward)), la cual también responde a un POST /Public/ContractAward/Search.
⚬ Doble Identidad y Trazabilidad: Nunca uses el título. UNGM tiene dos identificadores clave: el UNGM Notice ID (numérico único del portal, ej. 312633) y el Reference de la agencia emisora (ej. UNDP-PAK-01738 o RFQ/2026/64721). Tu source_id primario debe ser UNGM-{notice_id} guardando Reference como atributo de trazabilidad.
⚬ Trampa de los Portales Externos (e-Sourcing): Agencias como UNDP (Quantum), UNOPS (eSourcing) o FAO (In-Tend) sincronizan el anuncio y parte de los PDFs en UNGM, pero a veces obligan a pulsar el botón "View document" o "Express Interest" que redirige al ERP externo. El scraper debe descargar todos los documentos públicos expuestos en la pestaña Documents de UNGM y, si están bloqueados tras login, registrar los metadatos con official_documents: [] y mantener los campos no visibles como "unknown".

3. Diccionario de Datos (Mapeo UNGM → Contrato Agente)

Campo del Contrato	Origen Técnico	Selector / Campo en Fuente UNGM	Tipo	Regla de Transformación y Linaje
unit_type	Derivado (Regla)	Type of opportunity (/API/NoticeTypes)	String	RFP, ITB, RFQ, Grant, EOI, Consultant, Implementing Partner → actionable_opportunity. RFI, Pre-bid notice → context. Pestaña Revisions → update. /Public/ContractAward → outcome.
source_metadata.source_id	Scraper (URL/DOM)	Atributo data-noticeid / URL /Public/Notice/{id}	String	Formato UNGM-{notice_id} (ej. UNGM-312633). Concatenar o guardar aparte el campo Reference (ej. UNDP-MNE-00888,1).
source_metadata.source_url	Scraper	[https://www.ungm.org/Public/Notice/](https://www.ungm.org/Public/Notice/){id}	String	URL pública permanente del aviso.
identity_and_state.title	Scraper (Tabla/DOM)	Columna Title / Encabezado del aviso	String	Conservar en idioma original (usualmente EN, FR, ES, PT o AR).
identity_and_state.summary	Scraper (DOM Detalle)	Pestaña General > Description	String	Extraer texto íntegro de la descripción en su idioma nativo.
identity_and_state.modality	Scraper (Tabla/API)	Columna Type of opportunity	String	Mapear contra los 11 valores oficiales de /API/NoticeTypes (ej. Request for proposal, Grant support-call for proposal).
identity_and_state.status	Dinámico / Scraper	Filtro Active opportunities + Deadline	String	Desmarcar Only currently active en ingestas históricas para capturar cerradas (cerrada). Calcular dinámicamente comparando submission_deadline vs. UTC actual.
contexts_and_programs.parent_program_name	Scraper (DOM/PDF)	Pestaña UNSPSC codes + Nombre del proyecto en Description	String	UNGM clasifica por categoría UNSPSC (ej. IT Services, Healthcare). El nombre del proyecto paraguas suele estar en el PDF de ToR; si no está en el HTML, usar "unknown".
actors_and_roles.financiador	Scraper (Tabla/PDF)	Columna Organization + Donante en PDF	String	En primera instancia es la agencia ONU (UNDP, UNICEF, FAO, UNOPS, WHO, UNESCO, etc.).
actors_and_roles.emisor	Scraper (Tabla)	Columna Organization	String	Agencia de las Naciones Unidas que publica el llamado.
actors_and_roles.autoridad_contratante	Scraper (DOM Detalle)	Pestaña Contacts (Office, Name, Email)	String	Extraer la oficina de país (ej. UNDP Ecuador Country Office) y correo de contacto si es público.
dates_and_milestones.publication_date	Scraper (Tabla/DOM)	Columna Published (DD-MMM-YYYY)	ISO8601	Normalizar fecha de publicación a YYYY-MM-DDT00:00:00Z.
dates_and_milestones.submission_deadline	Scraper (Tabla/DOM)	Columna Deadline (28-Oct-2026 08:00 (GMT -4.00))	ISO8601	Crítico: UNGM explicita el offset GMT en cada fila (ej. (GMT -4.00) o (GMT 1.00)). Parsear la fecha, aplicar el offset y convertir a UTC (Z).
dates_and_milestones.clarification_deadline	Scraper (DOM/PDF)	Pestaña General o PDF (Deadline for clarifications)	ISO8601	Si no está explícito en el texto de Description, extraer del PDF o asignar "unknown".
financial_conditions.total_budget	Scraper (PDF)	Pliego PDF / "unknown"	Float/Str	Por política de adquisiciones de la ONU, las licitaciones (RFP/ITB/RFQ) ocultan el presupuesto estimado para asegurar competencia de precios. Debe quedar como "unknown" salvo en Grants donde el ToR lo indique.
financial_conditions.currency	Scraper (PDF)	Pliego PDF / "unknown"	String	Extraer del PDF si indica moneda de cotización (USD, EUR, moneda local). Si no es visible sin el PDF, "unknown".
eligibility_and_participation.modality_type	Scraper (DOM/PDF)	TypeOfCompetition (Open / Limited) + PDF	String	Si es Call for individual consultants → "individual". En RFP/Grants, verificar en el PDF si permite Joint Venture / Consortium ("consorcio_permitido").
eligibility_and_participation.applicant_types	Derivado / Scraper	Type of opportunity + RegistrationLevel	Array	Call for individual consultants → ["persona_natural"]. Call for implementing partners / Grant → ["ong", "universidad", "centro_investigacion"]. RFP/ITB/RFQ → ["empresa", "universidad", "ong"].
eligibility_and_participation.eligible_geographies	Scraper (Tabla/PDF)	Columna Beneficiary country or territory	Array	Distinción clave: La columna Beneficiary country indica dónde se ejecuta el contrato (incluye filtro directo para Ecuador). En licitaciones internacionales (Open), empresas/universidades de cualquier país miembro de la ONU pueden postular salvo que el título diga "National Consultant" o "Local ITB".
requirements_vs_criteria.mandatory_requirements	Scraper (DOM/PDF)	RegistrationLevel (Basic, Level 1, Level 2) + PDF	Array	Incluir siempre el nivel de registro requerido en UNGM y el UN Supplier Code of Conduct más los requisitos de calificación del PDF.
requirements_vs_criteria.evaluation_criteria	Scraper (PDF)	Sección Evaluation Criteria en el RFP/ToR PDF	Array	En RFP de la ONU suele ser ponderación Técnico/Financiera (ej. 70% / 30% o 80% / 20%). Extraer del PDF con linaje de página; si es solo HTML sin PDF, "unknown".
official_documents[]	Scraper (DOM Detalle)	Pestaña Documents	Array	Descargar cada archivo adjunto a RustFS S3, calcular sha256_hash y etiquetar como opportunity_specific. El UN Supplier Code of Conduct se etiqueta como agency_general.

4. Ejemplo de Salida JSON (Contrato Aplicado a UNGM)

{
  "unit_type": "actionable_opportunity",
  "source_metadata": {
    "source_id": "UNGM-312633",
    "source_url": "https://www.ungm.org/Public/Notice/312633",
    "scraped_at": "2026-10-28T17:03:00Z"
  },
  "identity_and_state": {
    "title": "Socio-Economic Analysis of the Just Transition of Montenegro's Energy System",
    "summary": "Reference: UNDP-MNE-00888,1. UNDP invites qualified institutions and firms to submit proposals for conducting a comprehensive socio-economic analysis of the just transition of the energy system...",
    "modality": "Request for proposal (RFP)",
    "status": "abierta"
  },
  "contexts_and_programs": {
    "parent_program_id": "UNSPSC-80000000",
    "parent_program_name": "Business Professionals and Administrative Services / Engineering, Research and Technology Based Services"
  },
  "actors_and_roles": {
    "financiador": "United Nations Development Programme (UNDP)",
    "emisor": "UNDP",
    "autoridad_contratante": "UNDP Montenegro Country Office (Quantum eTendering Portal)"
  },
  "dates_and_milestones": {
    "publication_date": "2026-10-05T00:00:00Z",
    "submission_deadline": "2026-10-28T12:00:00Z",
    "clarification_deadline": "unknown",
    "award_notice_date": "unknown"
  },
  "financial_conditions": {
    "total_budget": "unknown",
    "currency": "unknown",
    "minimum_award": "unknown",
    "maximum_award": "unknown",
    "funding_rate": 100.0,
    "cost_sharing_required": false
  },
  "eligibility_and_participation": {
    "modality_type": "consorcio_permitido",
    "applicant_types": ["empresa", "universidad", "centro_investigacion", "ong"],
    "eligible_geographies": ["Montenegro", "Global"]
  },
  "requirements_vs_criteria": {
    "mandatory_requirements": [
      "Registro activo en UNGM (Registration Level: Basic) y en el portal UNDP Quantum",
      "Aceptación del UN Supplier Code of Conduct"
    ],
    "evaluation_criteria": "unknown"
  },
  "official_documents": [
    {
      "doc_name": "Negotiation Document - UNDP-MNE-00888,1.pdf",
      "download_url": "https://www.ungm.org/Public/Notice/DownloadDocument?docId=...",
      "scope": "opportunity_specific",
      "sha256_hash": "pending_extraction"
    },
    {
      "doc_name": "UN Supplier Code of Conduct",
      "download_url": "https://www.ungm.org/Shared/KnowledgeCenter/Pages/PT_Sustain_CodeOfConduct",
      "scope": "agency_general",
      "sha256_hash": "pending_extraction"
    }
  ]
}

