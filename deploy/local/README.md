# Despliegue Local - IDCI Platform

Instrucciones y configuración para ejecutar la plataforma de datos IDCI en el entorno local.

## Arquitectura de Contenedores

| Servicio | Contenedor | Puerto Host | Descripción |
| :--- | :--- | :--- | :--- |
| **PostgreSQL 16** | `idci_postgres` | `5435` | Almacenamiento analítico de capas Bronze y Silver |
| **RustFS S3** | `idci_rustfs` | `9002` (API) / `9003` (UI) | Data Lake compatible con S3 para landing y artefactos crudos |
| **Apache Airflow** | `idci_airflow` | `8082` | Orquestador de DAGs y contenedores efímeros |

## Contenedores Efímeros bajo demanda (`--profile tools`)

* `idci_scraper_runner`: Extractor web con Playwright headless hacia RustFS S3.
* `idci_tika_runner`: Extracción paralela de texto y metadatos con Apache Tika.
* `idci_loader_runner`: Carga de manifests hacia `bronze.<institución>`.
* `idci_dbt_runner`: Transformación dimensional dbt Core y tests hacia `silver`.
* `idci_metadata_runner`: Certificación y linaje en OpenMetadata.

## Comandos Rápidos

```bash
# Crear red si no existe
docker network create idci_network || true

# Levantar el stack completo
docker compose -f deploy/local/docker-compose.yml up -d

# Ver estado
docker compose -f deploy/local/docker-compose.yml ps

# Detener el stack
docker compose -f deploy/local/docker-compose.yml down
```
