# Docker Infrastructure & Container Architecture

> **REFERENCE:** Modelled after CEDIA Data Platform (`deploy/local/docker-compose.yml`).
> **PRINCIPLE:** All core infrastructure services (Warehouse, Object Storage, Ingestion Runtime, Browser, and Orchestration) run under a **single unified `docker-compose.yml`** at the repository root, with explicit, deterministic container names (`container_name`).

---

## 1. Overview & Architectural Shift

Previously, infrastructure services were split across multiple sub-compose projects in `infra/` (`infra/warehouse`, `infra/ingestion`, `infra/orchestration`, `infra/transformation`). 

To align with the CEDIA data platform architecture, reduce network orchestration overhead, and provide single-command provisioning, all services are now consolidated into:
* **Root Compose File:** [`docker-compose.yml`](file:///Users/edissonmorocho/practicaspp/ScrapAgents/docker-compose.yml)
* **Environment Configuration:** [`.env`](file:///Users/edissonmorocho/practicaspp/ScrapAgents/.env) (copied from [`.env.example`](file:///Users/edissonmorocho/practicaspp/ScrapAgents/.env.example) at repository root; automatically loaded by `docker compose` without needing `--env-file`)
* **Network:** Unified bridge network `scrapagents_net`.

---

## 2. Container Inventory & Naming Convention

Every service specifies an explicit `container_name` to eliminate Docker Compose's non-deterministic numbering (`<project>-<service>-1`) and allow reliable CLI execution, automated health checks, and test runner scripting:

| Service | Container Name (`container_name`) | Base Image / Build Context | Exposed Host Port | Role & Responsibility |
| :--- | :--- | :--- | :---: | :--- |
| **`postgres`** | `scrapagents-postgres` | `postgres:16` | `5433` | Data Warehouse: hosts typed `bronze` tables, quarantine schema, and analytical dbt targets. Initialized via `infra/warehouse/init.sql`. |
| **`rustfs`** | `scrapagents-rustfs` | `rustfs/rustfs:1.0.4` | `9000` (S3), `9001` (UI) | Immutable S3 Landing Data Lake with Hive-style partitioning (`source=/dataset=/year=/...`). |
| **`tika`** | `scrapagents-tika` | `apache/tika:4.1.0` | `9998` | Binary parser: extracts plain text from complex documents (PDF, DOCX) before storage. Reached only by `source-runtime`. |
| **`source-runtime`** | `scrapagents-source-runtime` | Build: `rust/source_runtime` | `8088` | High-concurrency native RustWorker: performs streaming SHA-256 integrity hashing, Tika triage, S3 Landing ingest, and typed PostgreSQL inserts. |
| **`obscura`** | `scrapagents-obscura` | `h4ckf0r0day/obscura:0.2.6` | `9222` | Stealth headless browser written in Rust. Exposes CDP over WebSocket for anti-bot scraping and DOM exploration. |
| **`airflow-db`** | `scrapagents-airflow-db` | `postgres:16` | Internal only | Metadata database for Apache Airflow. |
| **`airflow-init`** | `scrapagents-airflow-init` | Build: `infra/orchestration/Dockerfile` | Ephemeral | Database migration runner and declarative pool importer (`_pools.json`). Terminates after execution. |
| **`airflow-api-server`**| `scrapagents-airflow-api-server` | Build: `infra/orchestration/Dockerfile` | `8080` | Airflow 3.4.0 API server and Web UI. Runs `SimpleAuthManager` in local development. |
| **`airflow-scheduler`** | `scrapagents-airflow-scheduler` | Build: `infra/orchestration/Dockerfile` | Internal only | Airflow LocalExecutor scheduler and task execution runner. |
| **`airflow-dag-processor`**| `scrapagents-airflow-dag-processor`| Build: `infra/orchestration/Dockerfile` | Internal only | Parses declarative YAML DAGs via native AIP-85 YAML importer (`airflow.sdk.importers.yaml_importer`). |
| **`dbt`** | `scrapagents-dbt` | Build: `infra/transformation/Dockerfile` | One-off CLI | dbt Core CLI tool container (`profile: [tools]`) used for catalog validation and model testing. |

---

## 3. Storage Volumes & Network

### Shared Network
* **`scrapagents_net`**: Pre-declared bridge network. All services communicate over internal DNS hostnames (`postgres`, `rustfs`, `tika`, `source-runtime`, `obscura`, `airflow-db`, `airflow-api-server`).

### Persistent Volumes
* `postgres_data`: PostgreSQL warehouse data directory (`/var/lib/postgresql/data`).
* `rustfs_data`: Raw S3 Landing data lake objects (`/data`).
* `airflow_db`: Airflow metadata PostgreSQL data directory.
* `airflow_logs`: Shared task execution logs across scheduler, api-server, and dag-processor (`/opt/airflow/logs`).

---

## 4. Operational Commands (Lifecycle)

The unified container setup is fully wired into the [`Makefile`](file:///Users/edissonmorocho/practicaspp/ScrapAgents/Makefile):

```bash
# Bring up the entire local infrastructure with a single command:
make infra-up

# Alternatively, using docker compose directly (automatically picks up .env and docker-compose.yml):
docker compose up -d --build

# Inspect the configuration and validate variable interpolation:
make infra-config

# Execute dbt commands inside the tools container:
make dbt CMD="build --select tag:source_fixture"

# Tear down the entire platform and clean orphan containers:
make infra-down
```

---

## 5. Alignment with CEDIA Platform

| Feature | CEDIA (`deploy/local/docker-compose.yml`) | ScrapAgents (`docker-compose.yml`) |
| :--- | :--- | :--- |
| **Compose Topology** | Single primary Compose file for core services | Single primary Compose file at repository root |
| **Container Naming** | Explicit `container_name: data_platform_<svc>` | Explicit `container_name: scrapagents-<svc>` |
| **Warehouse** | PostgreSQL (`data_platform_postgres`) | PostgreSQL 16 (`scrapagents-postgres`) |
| **Airflow Architecture**| Airflow 3 (API server, scheduler, dag-processor, init)| Airflow 3.4.0 with native YAML DAG importer (AIP-85) |
| **Object Storage** | MinIO (`data_platform_minio`) | RustFS S3 (`scrapagents-rustfs`) |
| **Ingestion Engine** | Python `SourceRuntime` container | Native Rust binary `source-runtime` (RustWorker) |
| **Browser Layer** | Local Chromium / Docker daemon | Obscura Rust headless browser over CDP (`scrapagents-obscura`) |
