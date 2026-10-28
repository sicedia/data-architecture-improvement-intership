# 🚀 IDCI Data Architecture & Ingestion Platform

Plataforma unificada de arquitectura de datos para la extracción, procesamiento de alto rendimiento con **Rust Worker**, extracción de texto con **Apache Tika**, almacenamiento crudo en **RustFS S3**, ingestión **PostgreSQL Bronze**, modelado analítico dimensional **Silver con dbt Core** y gobernanza con **OpenMetadata** para convocatorias de financiamiento e investigación (**IDRC / CRDI - Canadá**, **CYTED - Iberoamérica** y portales asociados de **Opportunity Intelligence**).

---

## 🏛️ Estructura del Proyecto

```text
IDCI/
├── configs/                     # Configuraciones declarativas de ingesta y entornos
│   ├── environments/            # Configuración por ambiente (local.yml)
│   ├── ingestions/              # Especificación de ingestas (idrc.yml)
│   └── metadata/                # Pipelines de gobernanza (postgres_dbt_ingestion.yml)
├── dags/                        # Airflow DAGs dedicados por institución
│   └── ingestions/              # Pipeline Factory y DAGs desacoplados
│       ├── _pipeline_factory.py          # Constructor modular de DAGs efímeros
│       ├── idrc_funding_pipeline_dag.py  # DAG dedicado para IDRC Canadá
│       └── cyted_funding_pipeline_dag.py # DAG dedicado para CYTED Iberoamérica
├── db/                          # Inicialización y migraciones del Data Warehouse
│   ├── init/                    # Scripts DDL de inicio (init.sql - esquemas bronze y silver)
│   └── migrations/              # Registro de migraciones ordenadas (0001_init.sql)
├── dbt/                         # Proyecto analítico dbt Core (PostgreSQL)
│   ├── dbt_project.yml          # Manifiesto y configuración de dbt
│   ├── profiles.yml             # Perfiles de conexión (docker / local)
│   ├── macros/                  # Macros SQL Jinja (get_bronze_tables, generate_schema_name)
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
│   ├── architecture/            # Diagramas y diseño Lakehouse
│   ├── ingestions/              # Documentación de arañas (spiders) y CLI
│   └── operations/              # Runbook operativo local (RUNBOOK_LOCAL.md)
├── scripts/                     # Scripts y utilitarios de automatización
│   └── local/                   # Ejecutores locales (run_dbt.sh, setup_network.sh)
├── src/                         # Código fuente del sistema
│   ├── airflow_plugins/         # Plugins para Apache Airflow
│   ├── extractor/               # Motor de Scraping (Scrapy + Playwright)
│   │   ├── scraper.py           # Entrypoint CLI con soporte de Stream IPC y Carga
│   │   └── spiders/             # Registro modular de arañas (idci, idrc, cyted)
│   ├── openmetadata/            # Validador y publicador de linaje end-to-end
│   ├── rust_worker/             # 🦀 Motor de Alto Rendimiento en Rust
│   │   ├── Cargo.toml           # Dependencias (tokio, reqwest, serde, sha2)
│   │   ├── Dockerfile           # Imagen multi-stage en Alpine (binario ultraligero 33MB)
│   │   └── src/
│   │       ├── main.rs          # Orquestador del ciclo de vida y ensamblado
│   │       ├── models.rs        # Estructuras de datos y sobres de lote
│   │       ├── s3_client.rs     # Cliente HTTP asíncrono para RustFS S3
│   │       └── tika_client.rs   # Despachador HTTP Fan-Out hacia Apache Tika
│   └── tika_processor/          # Procesador complementario Apache Tika
├── tests/                       # Suite de pruebas unitarias
│   └── unit/                    # Pruebas automatizadas (test_spiders.py)
├── Makefile                     # Interfaz unificada de comandos de plataforma
├── README.md                    # Documentación principal del repositorio
├── .dockerignore                # Exclusiones de build Docker
└── .gitignore                   # Exclusiones de Git
```

---

## 🛠️ Stack Tecnológico

* **Extracción Web & Binarios:** Python 3 (`playwright` [Chromium Headless con evasión de JavaScript], `beautifulsoup4`, `requests`, `boto3`).
* **🦀 Rust Worker (Stream IPC & Fan-Out):** Rust 1.80+ con `tokio` (asíncrono), `reqwest` (HTTP client), `serde` (serialización JSON tolerante), y `sha2` (hashing criptográfico). Binario nativo ultraligero (~33 MB) para validación de stream, filtrado de integridad y despacho de documentos.
* **Extracción de Contenido Complejo:** Apache Tika Server 4.1.0 para parsing estructural y OCR de documentos binarios (`.pdf`, `.docx`, `.doc`, `.xlsx`).
* **Almacenamiento de Objetos (Data Lake):** RustFS S3 (compatible S3 de ultra-baja latencia). Particionamiento Hive por fecha y tipo de documento:
  - `landing/{institución}/raw_payloads/year=YYYY/month=MM/day=DD/...`
  - `binaries/{institución}/{call_code}/{hash}_{file_name}`
  - `processed/{institución}/{call_code}/{hash}_{file_name}.txt`
* **Data Warehouse Relacional:** PostgreSQL 16 con esquemas desacoplados `bronze` (ingesta cruda en JSONB) y `silver` (tablas de hechos y dimensiones).
* **Modelado Analítico Dimensional:** dbt Core 1.8.2 (SQL + Jinja) con macro de autodescubrimiento `get_bronze_tables()`.
* **Orquestación de Pipelines:** Apache Airflow 2.8.1 con DAGs dedicados por institución.
* **Catálogo & Linaje de Datos:** OpenMetadata 1.4.2 con sincronización automatizada de linaje en 5 capas.
* **Contenedorización & Red:** Docker & Docker Compose en red bridge dedicada (`idci_network`).

---

## 🏛️ Arquitectura del Sistema End-to-End

```text
       [ Portal Web Oficial / Fuentes ] (IDRC Canadá, CYTED Iberoamérica)
                      │
                      ▼ (Navegación Playwright Headless + Descarga de Anexos)
       ┌──────────────────────────────────────────────┐
       │   Contenedor Scraper Efímero (idci_scraper)  │ ──► [Se destruye --rm]
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Stream JSON IPC con metadatos y binarios en Base64)
       ┌──────────────────────────────────────────────┐
       │   🦀 Rust Worker Efímero (idci_rust_worker)  │
       │   - Validación de esquema e integridad       │
       │   - Filtrado de registros inválidos          │
       │   - Detección de documentos complejos        │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Fan-Out HTTP asíncrono para PDFs / DOCX)
       ┌──────────────────────────────────────────────┐
       │         Apache Tika Server (Core)            │
       │   - Extracción de texto estructurado y OCR   │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Retorna texto plano estructurado)
       ┌──────────────────────────────────────────────┐
       │   🦀 Rust Worker Efímero (Ensamblador)       │
       │   - Ensambla metadatos + texto + binarios    │
       │   - Calcula hashes SHA-256 de trazabilidad   │
       │   - Genera Batch Manifest consolidado        │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Persistencia Atómica y Paralela)
       ┌──────────────────────────────────────────────┐
       │     RustFS S3 (Storage Compatible S3)        │ (Persistente)
       │    Bucket: s3://opportunity-intelligence/    │
       │  (landing/ , binaries/ , processed/)         │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Batch URI directa)
       ┌──────────────────────────────────────────────┐
       │   Contenedor Loader Efímero (idci_loader)    │ ──► [Se destruye --rm]
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Carga atómica en JSONB con auditoría)
       ┌──────────────────────────────────────────────┐
       │  PostgreSQL: bronze.<institución>__funding   │ (Persistente)
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (get_bronze_tables() auto-detecta la tabla)
       ┌──────────────────────────────────────────────┐
       │  Contenedor dbt Core Efímero (idci_dbt)      │ ──► [Se destruye --rm]
       │  - dbt run: Staging unificado + Marts        │
       │  - dbt test: 41 pruebas de calidad de datos  │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼
       ┌──────────────────────────────────────────────┐
       │  PostgreSQL (Esquema silver / Marts Kimball) │ (Persistente)
       │  - fct_opportunities                         │
       │  - dim_opportunity_documents (con S3 URIs)  │
       │  - dim_opportunity_milestones / actors / fin │
       │  - v_opportunities_consolidated              │
       └──────────────────────┬───────────────────────┘
                              │
                              ▼ (Validación y Certificación de Linaje)
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

## 🦀 Detalle del Rust Worker de Alto Rendimiento

El **Rust Worker** (`idci_rust_worker`) fue diseñado para desacoplar el procesamiento pesado de I/O y CPU fuera de Scrapy y Python:

1. **Recepción por Stream IPC:** Lee desde `stdin` un sobre estructurado (`BatchInputEnvelope`) con todos los registros y binarios en Base64 generados por el scraper.
2. **Filtrado y Validación en Tiempo Cero:** Valida códigos de oportunidad (`call_code`), URLs requeridas y congruencia de identificadores sin penalización de Garbage Collection.
3. **Fan-Out hacia Apache Tika:**
   - Detecta si cada anexo es un documento complejo (`.pdf`, `.docx`, `.doc`, `.odt`, `.rtf`, etc.).
   - Despacha los bytes concurrentemente hacia `http://tika:9998/tika`.
   - Extrae miles de palabras por documento en milisegundos.
4. **Ensamblado y Persistencia Directa en RustFS S3:**
   - Escribe el binario crudo en `binaries/{institución}/{call_code}/{hash}_{nombre}`.
   - Escribe el texto extraído por Tika en `processed/{institución}/{call_code}/{hash}_{nombre}.txt`.
   - Escribe la evidencia HTML completa en `documents/{institución}/{call_code}/source_evidence_{hash}.html`.
   - Ensambla el payload enriquecido en `landing/{institución}/raw_payloads/...`.
   - Genera y persiste el **Batch Manifest** final (`s3://.../batch_{uuid}.json`), el cual es entregado al Loader.
5. **Rendimiento:** Procesa lotes completos con 14+ documentos complejos en **menos de 3 segundos**.

---

## 🔑 Credenciales, Puertos y URLs de Acceso

| Servicio | URL / Endpoint Host | Puerto Host | Puerto Interno Docker | Usuario | Contraseña | Base de Datos / Bucket |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Apache Airflow UI** | [http://localhost:8082](http://localhost:8082) | `8082` | `8080` | `idci_admin` / `admin` | `secure_password_2026` / `admin` | `idci_analytics` |
| **PostgreSQL** | `localhost:5435` | `5435` | `5432` | `idci_admin` | `secure_password_2026` | `idci_analytics` |
| **Apache Tika API** | [http://localhost:9998/tika](http://localhost:9998/tika) | `9998` | `9998` | *N/A* | *N/A* | Endpoint REST |
| **RustFS Web Console** | [http://localhost:9003/rustfs/console/](http://localhost:9003/rustfs/console/) | `9003` | `9001` | `rustfsadmin` | `rustfsadmin2026` | Consola Web UI |
| **RustFS S3 API** | `http://localhost:9002` | `9002` | `9000` | `rustfsadmin` | `rustfsadmin2026` | `opportunity-intelligence` |
| **OpenMetadata UI** | [http://localhost:8585](http://localhost:8585) | `8585` | `8585` | `admin` | `admin` | Catálogo & Linaje |

---

## 🕷️ Sistema Modular de Spiders Especializados

Las arañas están diseñadas en estricto cumplimiento con las 7 dimensiones analíticas de `informacion.md`:

| Spider | Institución | URL Objetivo | Tabla Bronze | Moneda | Características |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`idci` / `idrc`** | IDRC (Canadá) | `https://idrc-crdi.ca/en/funding` | `bronze.idrc__funding_calls` | `CAD` | Extracción de convocatorias globales de investigación y desarrollo, pliegos, formularios y fechas de cierre. |
| **`cyted`** | CYTED (Iberoamérica) | `https://www.cyted.org/` | `bronze.cyted__funding_calls` | `EUR` | Extracción de Convocatoria Redes Temáticas (`idm=229`), Foros (`idm=219`), Proyectos IBEROEKA (`idm=220`) y Noticias. Descarga automática de 14 documentos oficiales (bases, memorias en DOCX, rúbricas y FAQs en español y portugués). |

### Listar Spiders Registrados
```bash
python3 src/extractor/scraper.py --list-spiders
```

---

## 🕹️ Orquestación Modular con DAGs Dedicados en Airflow

Siguiendo las mejores prácticas de ingeniería de datos, el proyecto utiliza **DAGs desacoplados por institución** construidos mediante [`_pipeline_factory.py`](file:///Users/edissonmorocho/practicaspp/IDCI/dags/ingestions/_pipeline_factory.py):

* **Aislamiento de Fallos (*Blast Radius*):** Si la web de una institución cambia o entra en mantenimiento, solo falla su respectivo DAG sin interrumpir a los demás.
* **Cronogramas Independientes:**
  - `idrc_funding_pipeline_dag`: Ejecución semanal los lunes a las 06:00 UTC (`0 6 * * 1`).
  - `cyted_funding_pipeline_dag`: Ejecución mensual el día 1 a las 08:00 UTC (`0 8 1 * *`).
* **Métricas y SLAs Aislados:** Gráficos de Gantt, duración y tasas de éxito independientes por institución en la interfaz de Airflow.

### Disparo Manual por Airflow CLI:
```bash
# Disparar pipeline de CYTED con límite de 5 convocatorias
docker exec -it idci_airflow airflow dags trigger cyted_funding_pipeline_dag \
  --conf '{"scrape_limit": 5, "use_browser": true, "download_binaries": true}'

# Disparar pipeline de IDRC
docker exec -it idci_airflow airflow dags trigger idrc_funding_pipeline_dag \
  --conf '{"scrape_limit": 10, "use_browser": true, "download_binaries": true}'
```

---

## ⚡ Ejecución Directa de la Cadena ELT (CLI / Docker)

Para ejecutar el flujo completo paso a paso sin Airflow:

```bash
# 1. Extracción con Scrapy hacia Stream IPC JSON
docker run --rm --network idci_network idci_scraper:latest \
    --step stream --spider cyted --limit 1 > /tmp/cyted_stream.json

# 2. Rust Worker: Filtrado + Apache Tika Fan-Out + Persistencia en S3
cat /tmp/cyted_stream.json | docker run -i --rm --network idci_network \
    -e S3_ENDPOINT_URL="http://rustfs:9000" \
    -e TIKA_URL="http://tika:9998" \
    idci_rust_worker:latest --input - > /tmp/cyted_manifest.json

# 3. Loader: Ingestión a PostgreSQL Bronze
MANIFEST_URI=$(python3 -c "import json; print(json.load(open('/tmp/cyted_manifest.json'))['batch_uri'])")
docker run --rm --network idci_network -e S3_ENDPOINT_URL="http://rustfs:9000" \
    idci_loader:latest --step load --batch-uri "$MANIFEST_URI"

# 4. dbt Core: Transformaciones dimensionales y pruebas de calidad
docker run --rm --network idci_network idci_dbt:latest run --profiles-dir . --target docker
docker run --rm --network idci_network idci_dbt:latest test --profiles-dir . --target docker

# 5. OpenMetadata: Certificación de linaje de datos
docker run --rm --network idci_network -e POSTGRES_HOST="postgres" idci_metadata:latest
```

---

## 📊 Modelo de Datos Dimensional Silver (dbt Core)

El proyecto dbt en `dbt/` unifica automáticamente todas las tablas `bronze.*__funding_calls` mediante la macro Jinja [`get_bronze_tables()`](file:///Users/edissonmorocho/practicaspp/IDCI/dbt/macros/get_bronze_tables.sql):

* **Staging (`silver.stg_idrc_funding_calls`)**: Vista normalizada con tipados, multimoneda original, fechas normalizadas y array de documentos adjuntos.
* **Marts Dimensionales (`silver.*`)**:
  * `fct_opportunities`: Tabla de hechos central con estado unificado (`OPEN`, `CLOSED`, `ANTICIPATORY`), indicadores de elegibilidad para Ecuador y resumen de financiamiento.
  * `dim_opportunity_documents`: Catálogo de documentos oficiales y anexos (PDFs, DOCX) con idioma (`es`, `pt`, `en`), tipo (`guidelines`, `template`, `rubric`, `faq`) y enlace directo a su almacenamiento en RustFS S3.
  * `dim_opportunity_actors`: Instituciones financiadoras y actores elegibles.
  * `dim_opportunity_financial_conditions`: Montos mínimos y máximos en moneda nativa original (`EUR`, `CAD`, etc.) y cofinanciamiento.
  * `dim_opportunity_milestones`: Hitos temporales (fechas de apertura, consultas, fallos y cierre).
  * `dim_opportunity_contexts`: Ejes temáticos, sectores de investigación y alcance geográfico.
  * `v_opportunities_consolidated`: Vista analítica consolidada para Power BI, Metabase o herramientas de visualización.

### Validación de Calidad de Datos
```bash
docker run --rm --network idci_network idci_dbt:latest test --profiles-dir . --target docker
# 41 de 41 pruebas de calidad aprobadas al 100%
```

---

## 🔍 Gobernanza y Linaje en OpenMetadata

El módulo `src/openmetadata/` valida y certifica las 5 etapas del linaje físico y lógico:
1. `Web Oficial` $\to$ `RustFS S3 Landing` (`idci_scraper` + `idci_rust_worker`)
2. `RustFS S3 Landing` $\to$ `PostgreSQL Bronze` (`idci_loader`)
3. `PostgreSQL Bronze` $\to$ `PostgreSQL Silver Staging` (`idci_dbt`)
4. `PostgreSQL Silver Staging` $\to$ `PostgreSQL Silver Marts` (`idci_dbt`)
5. `Silver Marts` $\to$ `Serving View` (`v_opportunities_consolidated`)
