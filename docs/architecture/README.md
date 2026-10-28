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
                              ▼ (Linaje & Gobierno)
       ┌──────────────────────────────────────────────┐
       │  Contenedor Metadata Efímero (idci_metadata) │ ──► [Se destruye --rm]
       └──────────────────────┬───────────────────────┘
                              │
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
  - `bronze.idrc__funding_calls`: Convocatorias de IDRC extraídas con su payload crudo en JSONB, timestamps de ingesta, hash de integridad MD5/SHA y `_landing_uri`.
  - Tablas dinámicas (ej: `bronze.ukri`, `bronze.cyted`): Creadas automáticamente según la institución configurada.
* **Capa Silver (`silver.*`)**:
  - `stg_idrc_funding_calls`: Vista de normalización intermedia y limpieza de tipos de datos.
  - Tablas dimensionales (Kimball):
    - `fct_opportunities`: Tabla de hechos principal de convocatorias.
    - `dim_opportunity_actors`: Entidades, agencias y beneficiarios elegibles.
    - `dim_opportunity_financial_conditions`: Montos máximos, moneda y requisitos de cofinanciamiento.
    - `dim_opportunity_milestones`: Fechas críticas (apertura, cierre, consultas, evaluación).
    - `dim_opportunity_documents`: Enlaces y metadatos de documentos adjuntos persistidos en S3.
    - `dim_opportunity_contexts`: Ejes temáticos, países elegibles y descriptores.
  - `v_opportunities_consolidated`: Vista analítica consumible para plataformas y usuarios de negocio.
