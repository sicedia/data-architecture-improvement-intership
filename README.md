# 🚀 IDCI Data Architecture & Ingestion Platform

Repositorio unificado de arquitectura de datos para la extracción, almacenamiento crudo en S3, ingestión Bronze, modelado analítico Silver con dbt Core y gobernanza para las oportunidades de financiamiento del **IDRC / CRDI (International Development Research Centre - Canadá)** y portales asociados de **Opportunity Intelligence**.
.

---

## 🏛️ Estructura del Proyecto (Estándar)

```text
IDCI/
├── configs/                     # Configuraciones declarativas de ingesta y entornos
│   ├── environments/            # Configuración por ambiente (local.yml)
│   ├── ingestions/              # Especificación de ingestas (idrc.yml)
│   └── metadata/                # Pipelines de gobernanza (postgres_dbt_ingestion.yml)
├── dags/                        # Airflow DAGs listos para orquestación
│   └── ingestions/              # DAGs de ingesta (idrc_funding_pipeline_dag.py)
├── db/                          # Inicialización y migraciones del Data Warehouse
│   ├── init/                    # Scripts de inicio (init.sql)
│   └── migrations/              # Registro de migraciones ordenadas (0001_init.sql)
├── dbt/                         # Proyecto analítico dbt Core (PostgreSQL)
│   ├── dbt_project.yml          # Manifiesto y configuración dbt
│   ├── profiles.yml             # Perfiles de conexión (docker / local)
│   ├── macros/                  # Macros SQL Jinja (generate_schema_name, get_bronze_tables)
│   └── models/
│       ├── staging/             # Vistas de tipado y normalización (silver.stg_*)
│       └── marts/               # Modelo dimensional Kimball (fct_* y dim_*)
├── deploy/                      # Infraestructura y runtime Docker
│   ├── images/                  # Dockerfiles desacoplados y requerimientos
│   │   ├── extractor.Dockerfile
│   │   ├── tika.Dockerfile
│   │   ├── dbt.Dockerfile
│   │   └── openmetadata.Dockerfile
│   └── local/                   # Despliegue local modular
│       ├── docker-compose.yml   # Stack unificado local
│       ├── docker-compose.*.yml # Compose modulares (db, s3, airflow, dbt)
│       ├── .env.example         # Plantilla de variables de entorno
│       └── README.md            # Guía de despliegue local
├── docs/                        # Documentación técnica y operativa
│   ├── architecture/            # Diagramas y diseño Lakehouse Fan-Out
│   ├── ingestions/              # Documentación de arañas (spiders) y CLI
│   └── operations/              # Runbook operativo local (RUNBOOK_LOCAL.md)
├── scripts/                     # Scripts y utilitarios de automatización
│   └── local/                   # Ejecutores locales (run_dbt.sh, setup_network.sh)
├── src/                         # Código fuente Python de la plataforma
│   ├── airflow_plugins/         # Plugins para Apache Airflow
│   ├── extractor/               # Motor de Scraping Playwright y Spiders
│   │   ├── scraper.py           # Entrypoint de extracción y carga
│   │   └── spiders/             # Registro modular de arañas (idrc, generic)
│   ├── openmetadata/            # Validador y publicador de linaje
│   └── tika_processor/          # Procesador efímero Apache Tika (Fan-Out)
├── tests/                       # Suite de pruebas unitarias
│   └── unit/                    # Pruebas de componentes Python
├── Makefile                     # Interfaz unificada de comandos de plataforma
├── README.md                    # Documentación principal del repositorio
├── .dockerignore                # Exclusiones de build Docker
└── .gitignore                   # Exclusiones de Git
```

> [!NOTE]
> **Compatibilidad total**: Para preservar compatibilidad absoluta con scripts preexistentes y comandos directos de Docker, los accesos raíz (`docker compose`, `./run_dbt.sh`, y enlaces simbólicos hacia `src/` y `db/`) se encuentran totalmente operativos sin alteraciones a la lógica de negocio.

---

## 🛠️ Stack Tecnológico

* **Lenguaje de Programación & Ingesta:** Python 3 (`playwright` [Chromium Headless], `beautifulsoup4`, `requests`, `boto3`, `psycopg2`).
* **Motor de Navegación & Anti-Bloqueos:** Playwright Chromium Headless con evasión de JavaScript dinámico.
* **Descarga de Binarios:** Extracción automática de documentos adjuntos (PDFs, Word `.docx`/`.doc`, Excel `.xlsx`, etc.) persistidos en S3.
* **Procesamiento de Texto & Metadatos:** Apache Tika en contenedores efímeros bajo el patrón Fan-Out en paralelo.
* **Almacenamiento de Objetos Crudos y Procesados:** RustFS (S3-Compatible Object Storage).
* **Almacenamiento Relacional (Data Warehouse):** PostgreSQL 16 con esquemas desacoplados `bronze` y `silver`.
* **Motor de Transformación:** dbt Core (SQL + Jinja) con adaptadores para PostgreSQL.
* **Orquestador:** Apache Airflow 2.8.1 (Standalone: Webserver + Scheduler).
* **Gobernanza y Catálogo:** OpenMetadata.
* **Contenedorización & Red:** Docker & Docker Compose con red bridge dedicada (`idci_network`).

---

## 🏛️ Arquitectura del Sistema End-to-End

```text
       [ Portal Web Oficial / Fuentes ] (IDRC, CYTED)
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

## 🔑 Credenciales, Puertos y URLs de Acceso

| Servicio | URL / Endpoint Host | Puerto Host | Puerto Interno Docker | Usuario | Contraseña | Base de Datos / Bucket |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Apache Airflow UI** | [http://localhost:8082](http://localhost:8082) | `8082` | `8080` | `idci_admin` / `admin` | `secure_password_2026` / `admin` | `idci_analytics` |
| **PostgreSQL** | `localhost:5435` | `5435` | `5432` | `idci_admin` | `secure_password_2026` | `idci_analytics` |
| **RustFS Web Console** | [http://localhost:9003/rustfs/console/](http://localhost:9003/rustfs/console/) | `9003` | `9001` | `rustfsadmin` | `rustfsadmin2026` | Consola Web UI |
| **RustFS S3 API** | `http://localhost:9002` | `9002` | `9000` | `rustfsadmin` | `rustfsadmin2026` | `opportunity-intelligence` |

### 📌 Conexión a PostgreSQL desde tu Máquina (DBeaver, DataGrip, pgAdmin)
* **Host:** `localhost` o `127.0.0.1`
* **Puerto:** `5435`
* **Base de Datos:** `idci_analytics`
* **Usuario:** `idci_admin`
* **Contraseña:** `secure_password_2026`

---

## ⚡ Automatización con Makefile

Siguiendo el flujo incluye un `Makefile` en la raíz:

| Comando | Acción |
| :--- | :--- |
| `make help` | Muestra la lista de comandos disponibles |
| `make local-up` | Asegura la red y levanta el stack local (Postgres, RustFS S3, Airflow) |
| `make local-down` | Detiene los contenedores locales conservando volúmenes |
| `make local-ps` | Consulta el estado de salud de los contenedores |
| `make local-logs` | Visualiza los logs combinados en vivo |
| `make local-reset` | Detiene el stack y **elimina todos los volúmenes de datos** |
| `make dbt-run` | Ejecuta las transformaciones dbt Core en un contenedor efímero (`--rm`) |
| `make dbt-test` | Ejecuta la suite de pruebas de calidad dbt Core |
| `make dbt-build` | Ejecuta `dbt build` (modelos + tests) |
| `make docker-build` | Construye las imágenes efímeras personalizadas |
| `make postgres-shell` | Abre una consola interactiva `psql` dentro de PostgreSQL |
| `make test` | Ejecuta la suite de pruebas unitarias |

---

## 🚀 Guías de Despliegue Alternativas

### Opción 1: Vía `Makefile` (Recomendada)
```bash
make local-up
```

### Opción 2: Vía `deploy/local/` (Estándar)
```bash
# Copiar variables si se desea customizar
cp deploy/local/.env.example deploy/local/.env

# Levantar servicios
docker compose -f deploy/local/docker-compose.yml up -d
```

### Opción 3: Vía Raíz (Retrocompatibilidad Directa)
```bash
docker network create idci_network || true
docker compose up -d
```

---

## 🕷️ Sistema Modular de Spiders (Extracción Dinámica)

Las arañas están ubicadas bajo `src/extractor/spiders/` y registradas en el factory `SPIDER_REGISTRY`:

| Spider | Institución por defecto | URL Objetivo | Tabla Bronze | Características |
| :--- | :--- | :--- | :--- | :--- |
| `idrc` | IDRC (Canadá) | `https://idrc-crdi.ca/en/funding` | `bronze.idrc__funding_calls` | Parsing especializado de convocatorias IDRC, estados, fechas y pliegos. |
| `generic` | Parametrizable | Dinámica | `bronze.<institución>` | Crawling adaptativo con extracción de enlaces, textos y detección automática de binarios. |

### Listar Spiders Registrados
```bash
python3 src/extractor/scraper.py --list-spiders
```

---

## 🕹️ Parámetros de Ejecución desde Airflow

El DAG `idrc_funding_pipeline_dag` (en `dags/ingestions/idrc_funding_pipeline_dag.py`) está parametrizado para ejecutarse tanto desde la UI como por CLI:

* `spider`: Araña a utilizar (`generic` o `idrc`).
* `target_url`: URL de inicio del scraping.
* `institution_name`: Nombre de la institución (ej: `UKRI`, `CYTED`, `IDRC`). Determina la tabla en Bronze (ej: `bronze.ukri`).
* `scrape_limit`: Cantidad máxima de convocatorias o páginas a extraer.
* `use_browser`: Activa Playwright Chromium Headless para evasión de JavaScript.
* `download_binaries`: Descarga documentos adjuntos hacia S3.
* `enable_tika_fanout`: Activa el procesamiento concurrente de documentos con Apache Tika.
* `tika_chunk_size`: Tamaño de lote por contenedor efímero `idci_tika` (por defecto `500`).

### Ejecución por Airflow CLI:
```bash
docker exec -it idci_airflow airflow dags trigger idrc_funding_pipeline_dag \
  --conf '{
    "spider": "generic",
    "target_url": "https://www.cyted.org/convocatorias",
    "institution_name": "CYTED",
    "scrape_limit": 30,
    "use_browser": true,
    "download_binaries": true,
    "enable_tika_fanout": true,
    "tika_chunk_size": 250
  }'
```

---

## ⚡ Procesamiento Efímero con Apache Tika (Patrón Fan-Out)

El procesador ubicado en `src/tika_processor/processor.py` realiza la conversión de binarios crudos hacia texto plano `.txt` y metadatos estructurados `.json` bajo el patrón Fan-Out:

1. **Fase de Planificación (`--plan`):** Consulta S3 y genera un plan JSON de partición en lotes.
2. **Fase Fan-Out en Paralelo:** Airflow despacha contenedores efímeros `idci_tika` en paralelo:
   * `[⚡ idci_tika - Lote-1]` (Archivos 1 a 500)
   * `[⚡ idci_tika - Lote-2]` (Archivos 501 a 1000)
   * `[⚡ idci_tika - Lote-3]` (Archivos 1001 a 1500)
3. Cada contenedor procesa su lote asignado, persiste en `s3://opportunity-intelligence/processed/` y se destruye automáticamente (`--rm`).

---

## 📊 Modelo de Datos Dimensional Silver (dbt Core)

El proyecto dbt en `dbt/` transforma los datos crudos en un modelo dimensional listo para analítica:

* **Staging (`silver.stg_idrc_funding_calls`)**: Limpieza de tipados, extracción de campos JSONB y validaciones preliminares.
* **Marts Dimensionales (`silver.*`)**:
  * `fct_opportunities`: Tabla de hechos central de convocatorias con métricas agregadas.
  * `dim_opportunity_actors`: Actores, instituciones proponentes y audiencias elegibles.
  * `dim_opportunity_financial_conditions`: Montos máximos, moneda de financiamiento y aportes contraparte.
  * `dim_opportunity_milestones`: Fechas clave (apertura, cierre, consultas, publicación de resultados).
  * `dim_opportunity_documents`: Enlaces S3 a pliegos, resoluciones y anexos en formato crudo y procesado.
  * `dim_opportunity_contexts`: Ejes temáticos, sectores y regiones geográficas de impacto.
  * `v_opportunities_consolidated`: Vista analítica consolidada para herramientas BI y consumidores finales.

### Validaciones de Calidad dbt
```bash
make dbt-test
# o mediante script:
./scripts/local/run_dbt.sh
```

---

## 🔍 Gobernanza y OpenMetadata

El módulo `src/openmetadata/` gestiona el catálogo y linaje end-to-end:
* Valida la conectividad con el servidor OpenMetadata (`OPENMETADATA_HOST`).
* Integra el catálogo y linaje entre las fuentes oficiales, los buckets de RustFS S3, las tablas `bronze` y los modelos dimensionales `silver` construidos por dbt Core.
* La configuración declarativa se encuentra en `configs/metadata/postgres_dbt_ingestion.yml`.
