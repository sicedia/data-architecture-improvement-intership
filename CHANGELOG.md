# 📝 Registro de Cambios (Changelog) - IDCI Data Platform

Todos los cambios notables, refactorizaciones y correcciones del proyecto quedan documentados en este archivo.

---

## [2026-11-04] - Arquitectura Silver en 2 Fases, Persistencia Dual S3 y Correcciones Operativas

### 🚀 Nuevas Funcionalidades y Refactorizaciones de Arquitectura

#### 1. División de la Capa Silver en 2 Fases Desacopladas por DAG
- **Fase 1: Staging (`_stg` - Vistas SQL)**:
  - Creadas 20 vistas de desempaquetado y tipado 1:1 especializadas por entidad analítica:
    - **IDRC**: `idrc_opportunities_stg`, `idrc_actors_stg`, `idrc_financial_conditions_stg`, `idrc_milestones_stg`, `idrc_documents_stg`.
    - **CYTED**: `cyted_opportunities_stg`, `cyted_actors_stg`, `cyted_financial_conditions_stg`, `cyted_milestones_stg`, `cyted_documents_stg`.
    - **Banco Mundial**: `worldbank_opportunities_stg`, `worldbank_actors_stg`, `worldbank_financial_conditions_stg`, `worldbank_milestones_stg`, `worldbank_documents_stg`.
    - **UNGM**: `ungm_opportunities_stg`, `ungm_actors_stg`, `ungm_financial_conditions_stg`, `ungm_milestones_stg`, `ungm_documents_stg`.
- **Fase 2: Intermediate (`_int` - Tablas Físicas)**:
  - Creadas 20 tablas intermedias deduplicadas con clave inmutable (`call_code`), fechas normalizadas a UTC, inyección de `'unknown'` para valores ausentes y preservación de convocatorias cerradas:
    - **IDRC**: `idrc_opportunities_int`, `idrc_actors_int`, `idrc_financial_conditions_int`, `idrc_milestones_int`, `idrc_documents_int`.
    - **CYTED**: `cyted_opportunities_int`, `cyted_actors_int`, `cyted_financial_conditions_int`, `cyted_milestones_int`, `cyted_documents_int`.
    - **Banco Mundial**: `worldbank_opportunities_int`, `worldbank_actors_int`, `worldbank_financial_conditions_int`, `worldbank_milestones_int`, `worldbank_documents_int`.
    - **UNGM**: `ungm_opportunities_int`, `ungm_actors_int`, `ungm_financial_conditions_int`, `ungm_milestones_int`, `ungm_documents_int`.
    - Modelo unificado: `int_opportunities__unified`.
- **Marts Dimensionales (Kimball Core)**:
  - Actualizados para consumir de las tablas intermedias institucionales: `fct_opportunities`, `dim_opportunity_actors`, `dim_opportunity_contexts`, `dim_opportunity_financial_conditions`, `dim_opportunity_milestones`, `dim_opportunity_documents` y la vista de analítica `v_opportunities_consolidated`.

#### 2. Persistencia y Exportación Dual hacia RustFS S3
- Creado el módulo [`src/extractor/export_silver_to_s3.py`](file:///Users/edissonmorocho/practicaspp/IDCI/src/extractor/export_silver_to_s3.py):
  - Conexión a PostgreSQL esquema `silver` y exportación de modelos `_int` y dimensionales.
  - Almacenamiento en RustFS S3 con particionamiento temporal compatible con Data Lake/DuckDB:
    - `s3://opportunity-intelligence/silver/{institution}/{table_name}/year=YYYY/month=MM/data_{timestamp}.json`
    - `s3://opportunity-intelligence/silver/{institution}/{table_name}/latest.json`
  - Tolerancia a tablas vacías (exporta `[]` sin fallar en estado inicial).
- Integrada la tarea `run_export_silver_s3` en los DAGs de Airflow ([`_pipeline_factory.py`](file:///Users/edissonmorocho/practicaspp/IDCI/dags/ingestions/_pipeline_factory.py) y [`worldbank_procurement_pipeline_dag.py`](file:///Users/edissonmorocho/practicaspp/IDCI/dags/ingestions/worldbank_procurement_pipeline_dag.py)).

---

### 🐛 Correcciones (Bug Fixes)

#### 1. Corrección de `Broken DAG: CYTED_DOC_MD is not defined`
- **Problema**: El archivo [`cyted_funding_pipeline_dag.py`](file:///Users/edissonmorocho/practicaspp/IDCI/dags/ingestions/cyted_funding_pipeline_dag.py) referenciaba la variable `CYTED_DOC_MD` en su llamada al constructor, pero la variable no existía en el archivo, rompiendo la carga del DAG en Airflow.
- **Solución**: Se definió el bloque de documentación enriquecida `CYTED_DOC_MD` con las reglas de negocio de CYTED (arquitectura PHP, líneas temáticas, horario CEST a UTC, moneda EUR y consorcio obligatorio).
- **Verificación**: `airflow dags list-import-errors` retornó 0 errores.

#### 2. Configuración y Restablecimiento de Credenciales de Airflow
- **Problema**: Al reinicializar el stack desde cero en modo *standalone*, Airflow generó una contraseña aleatoria temporal para `admin` y no existía el usuario `airflow`.
- **Solución**: Se crearon/actualizaron los usuarios administrativos:
  - `airflow` / `airflow` (Rol: Admin)
  - `admin` / `admin` (Rol: Admin)

#### 3. Remoción de `doc_md` (DAG Docs) de la UI de Airflow
- **Motivo**: Mantener la interfaz de usuario de Airflow limpia, ligera y enfocada en la monitorización de tareas, evitando bloques de texto masivos en la vista de cuadrícula/grafo.
- **Acción**: Se retiró el atributo `doc_md` de todos los DAGs (`idrc`, `cyted`, `ungm`, `worldbank`). La documentación contextual y operativa completa se centraliza en [`ContextoParaDags.md`](file:///Users/edissonmorocho/practicaspp/IDCI/ContextoParaDags.md), [`informacion.md`](file:///Users/edissonmorocho/practicaspp/IDCI/informacion.md) y [`docs/`](file:///Users/edissonmorocho/practicaspp/IDCI/docs/).
- **Documentación**: Actualizada la tabla de accesos y comandos de mantenimiento en [`docs/operations/RUNBOOK_LOCAL.md`](file:///Users/edissonmorocho/practicaspp/IDCI/docs/operations/RUNBOOK_LOCAL.md).

#### 3. Ajuste de compatibilidad en dbt Core
- **Problema**: La vista `v_opportunities_consolidated` fallaba al compilar debido a una referencia al campo `condition_type` en `dim_opportunity_financial_conditions`.
- **Solución**: Se ajustó `dim_opportunity_financial_conditions.sql` para exponer `condition_type` (`subvencion_investigacion`, `subvencion_red_tematica`, `licitacion_adquisicion`, `adquisicion_onu`).
- **Verificación**: `dbt run` completó 50/50 modelos y `dbt test` aprobó 49/49 pruebas.

---

### 📚 Documentación Actualizada
- [`docs/architecture/SILVER_TWO_PHASE_ARCHITECTURE.md`](file:///Users/edissonmorocho/practicaspp/IDCI/docs/architecture/SILVER_TWO_PHASE_ARCHITECTURE.md): Documento técnico de la arquitectura en 2 fases y almacenamiento dual S3.
- [`docs/architecture/README.md`](file:///Users/edissonmorocho/practicaspp/IDCI/docs/architecture/README.md): Diagrama end-to-end actualizado con la exportación a RustFS S3 y detalle de modelos.
- [`docs/operations/RUNBOOK_LOCAL.md`](file:///Users/edissonmorocho/practicaspp/IDCI/docs/operations/RUNBOOK_LOCAL.md): Puertos, credenciales y comandos para gestión de usuarios.
- [`README.md`](file:///Users/edissonmorocho/practicaspp/IDCI/README.md): Árbol de archivos y tecnologías actualizadas.
