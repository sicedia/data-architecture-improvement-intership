# 🏛️ Arquitectura del Sistema: IDCI Data Platform

## 1. Visión General

La plataforma **IDCI (Opportunity Intelligence & Ingestion Pipeline)** implementa un **Modern Data Stack (MDS)** con el patrón **Lakehouse** desacoplado en dos zonas principales de almacenamiento y capas analíticas normalizadas:

1. **Object Storage (RustFS S3)**: Zona de aterrizaje inmutable de archivos crudos (HTMLs, metadatos JSON y binarios PDFs/DOCX).
2. **Relational Data Warehouse (PostgreSQL 16)**: Esquemas desacoplados `bronze` (ingesta cruda con metadatos de auditoría) y `silver` (modelo dimensional Kimball y vistas analíticas).
3. **Orquestación (Apache Airflow 2.8.1)**: Orquestador central encargado de despachar tareas secuenciales y paralelas.
4. **Computación Efímera (Docker On-Demand / Fan-Out)**: Cada tarea del pipeline se ejecuta en un contenedor independiente que se instancia para su labor y se destruye automáticamente (`--rm`).

---

## 2. Diagrama de Arquitectura End-to-End

```text
       [ Portal Web Oficial / Fuentes ] (IDRC, UKRI, CYTED, etc.)
                      │
                      ▼ (Navegación Playwright Headless + Anti-Bot)
       ┌──────────────────────────────────────────────┐
       │   Contenedor Scraper Efímero (idci_scraper)  │ ──► [Se destruye --rm]
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Landing Zone: JSONs crudos, HTMLs y Binarios PDFs/Docs)
       ┌──────────────────────────────────────────────┐
       │     RustFS S3 (Storage Compatible S3)        │ (Persistente)
       │    Bucket: s3://opportunity-intelligence/    │
       │  (landing/ , binaries/ , documents/)         │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Fan-Out: Procesamiento Efímero en Paralelo)
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
   ┌───────────┐        ┌───────────┐        ┌───────────┐
   │ idci_tika │        │ idci_tika │        │ idci_tika │
   │ (Lote 1)  │        │ (Lote 2)  │        │ (Lote 3)  │
   │ Arch.1-500│        │Arch.501-1k│        │Arch.1k-1.5│
   └─────┬─────┘        └─────┬─────┘        └─────┬─────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼ (Processed Zone: .txt limpio y .json metadatos)
       ┌──────────────────────────────────────────────┐
       │     RustFS S3 (Storage Compatible S3)        │ (Persistente)
       │  (processed/{institución}/{code}/... )       │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Carga Bronze)
       ┌──────────────────────────────────────────────┐
       │   Contenedor Loader Efímero (idci_loader)    │ ──► [Se destruye --rm]
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Ingesta cruda con metadatos)
       ┌──────────────────────────────────────────────┐
       │  PostgreSQL (Esquema bronze.{institución})   │ (Persistente)
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Transformaciones & Tests)
       ┌──────────────────────────────────────────────┐
       │  Contenedor dbt Core Efímero (idci_dbt)      │ ──► [Se destruye --rm]
       └──────────────────────┬───────────────────────┘
                              │
                              ▼
       ┌──────────────────────────────────────────────┐
       │  PostgreSQL (Esquema silver / Marts)         │ (Persistente)
       └──────────────────────┬───────────────────────┘
                              │
                              ├─────────────────────────────────────────┐
                              ▼ (Silver S3 Exporter)                    ▼ (Linaje & Gobierno)
       ┌──────────────────────────────────────────────┐  ┌──────────────────────────────────────────────┐
       │  RustFS S3 (Lakehouse Partitioning)          │  │  Contenedor Metadata Efímero (idci_metadata) │
       │  s3://.../silver/{institución}/*.json        │  └──────────────────────┬───────────────────────┘
       └──────────────────────────────────────────────┘                         │
                                                                                ▼
                                                         ┌──────────────────────────────────────────────┐
                                                         │  OpenMetadata (Catálogo & Linaje End-to-End) │
                                                         └──────────────────────────────────────────────┘
```

---

## 3. Patrón Fan-Out (Apache Tika)

Para procesar grandes volúmenes de documentos no estructurados (PDFs de convocatorias, manuales, pliegos en Word), el pipeline calcula un plan de lotes (`--plan`) dividiendo los archivos crudos en chunks parametrizables (por defecto 500 archivos por lote).

Airflow ejecuta de forma concurrente los contenedores `idci_tika`:
* Extraen texto limpio plano `.txt`.
* Extraen metadatos técnicos en `.json` (autor, tamaño, fecha de creación, software).
* Almacenan el resultado en la ruta inmutable `processed/{institution}/{call_code}/`.

---

## 4. Capas del Data Warehouse

* **Capa Bronze (`bronze.*`)**:
  - `bronze.idrc__funding_calls`: Convocatorias de IDRC extraídas en JSONB crudo con timestamps de ingesta, hash de integridad y `_landing_uri`.
  - `bronze.cyted__funding_calls`: Convocatorias de Redes Temáticas, foros y proyectos CYTED en JSONB crudo.
  - `bronze.worldbank__procurement`: Licitaciones y avisos de adquisiciones del Banco Mundial en JSONB crudo.
  - `bronze.ungm__notices`: Avisos de contrataciones de la ONU / UNGM en JSONB crudo.

* **Capa Silver (`silver.*` — Arquitectura Especializada en 2 Fases + S3 Lakehouse)**:
  - Documentación completa detallada: [`SILVER_TWO_PHASE_ARCHITECTURE.md`](file:///Users/edissonmorocho/practicaspp/IDCI/docs/architecture/SILVER_TWO_PHASE_ARCHITECTURE.md)
  - **Fase 1: Staging (`{institución}_{dimensión}_stg`) — Vistas SQL**: Desempaquetado 1:1 especializado por entidad dimensional (20 vistas):
    - **IDRC**: `idrc_opportunities_stg`, `idrc_actors_stg`, `idrc_financial_conditions_stg`, `idrc_milestones_stg`, `idrc_documents_stg`.
    - **CYTED**: `cyted_opportunities_stg`, `cyted_actors_stg`, `cyted_financial_conditions_stg`, `cyted_milestones_stg`, `cyted_documents_stg`.
    - **Banco Mundial**: `worldbank_opportunities_stg`, `worldbank_actors_stg`, `worldbank_financial_conditions_stg`, `worldbank_milestones_stg`, `worldbank_documents_stg`.
    - **UNGM**: `ungm_opportunities_stg`, `ungm_actors_stg`, `ungm_financial_conditions_stg`, `ungm_milestones_stg`, `ungm_documents_stg`.
  - **Fase 2: Intermediate (`{institución}_{dimensión}_int`) — Tablas Físicas**: Deduplicación, resolución de IDs inmutables, normalización UTC, regla de incertidumbre (`unknown`) y tipado fuerte (20 tablas):
    - **IDRC**: `idrc_opportunities_int`, `idrc_actors_int`, `idrc_financial_conditions_int`, `idrc_milestones_int`, `idrc_documents_int`.
    - **CYTED**: `cyted_opportunities_int`, `cyted_actors_int`, `cyted_financial_conditions_int`, `cyted_milestones_int`, `cyted_documents_int`.
    - **Banco Mundial**: `worldbank_opportunities_int`, `worldbank_actors_int`, `worldbank_financial_conditions_int`, `worldbank_milestones_int`, `worldbank_documents_int`.
    - **UNGM**: `ungm_opportunities_int`, `ungm_actors_int`, `ungm_financial_conditions_int`, `ungm_milestones_int`, `ungm_documents_int`.
    - `int_opportunities__unified`: Consolidación universal de oportunidades.
  - **Marts Dimensionales (Kimball Core)**:
    - `fct_opportunities`: Tabla de hechos principal de convocatorias normalizadas.
    - `dim_opportunity_actors`: Entidades financiadoras, agencias emisoras y contactos.
    - `dim_opportunity_financial_conditions`: Montos presupuestarios en moneda nativa original y cofinanciamiento.
    - `dim_opportunity_milestones`: Hitos críticos y plazos de cierre normalizados en UTC.
    - `dim_opportunity_documents`: Catálogo de pliegos y términos de referencia referenciados en RustFS S3.
    - `dim_opportunity_contexts`: Ejes temáticos, sectores y programas contenedores.
    - `v_opportunities_consolidated`: Vista analítica de consumo unificado.
  - **Persistencia Dual en RustFS S3**:
    - Las 20 tablas intermedias y los 7 marts se exportan automáticamente a `s3://opportunity-intelligence/silver/{institución}/{tabla}/` con particionamiento `year=YYYY/month=MM/` y puntero `latest.json`.
