# CEDIA as a reference (not a dependency)

This project is independent of CEDIA and runs only on this machine. The notes below record what
`sicedia/cedia-data-platform_prod` ("CEDIA Data Architecture") does, as read on 2026-11-09 from a clone
outside this repository (`../cedia-data-platform_prod-main`), and where this project chose differently.
Nothing here imports, vendors or deploys to it; the contract rules are this project's own
(`scrapagents.contracts`).

## What CEDIA provides (guide)

| Topic | CEDIA location |
| :--- | :--- |
| Source declaration (one file per source, governance included) | `configs/ingestions/<id>.yml` |
| Dataset contracts (grain, primary key, typed columns, personal data classification) | `configs/contracts/<source>/<dataset>.yml` |
| Scaffolding | `make new-ingestion ID= TEAM=`, `scripts/scaffold/new_ingestion.py` |
| Run-time contract object | `src/common/ingestion/runtime.py` (`SourceRuntime`, Python) |
| Validators | `make validate` (`scripts/validation/`) |
| Pre-implementation gate for agents | `docs/ai/data_platform_pre_implementation_gate.md` |

## Differences to resolve

| Topic | `Contex.md` | CEDIA (`configs/platform/compatibility_matrix.yml`) | F1 decision |
| :--- | :--- | :--- | :--- |
| PostgreSQL | 16 | 18.6 | Local infra follows `Contex.md` (16), version set in `infra/.env.example` |
| Airflow | 3.4.0 | 3.3.2 | 3.4.0 verified as the latest stable release on 2026-11-09 (PyPI and `apache/airflow` on Docker Hub); not used until F3 |
| OpenMetadata | 1.4.2 | 2.0.7 | Not used in F1; decide in F6 |
| Object storage | RustFS (S3) | MinIO | Local infra uses RustFS per `Contex.md`; both speak S3 |
| SourceRuntime | Rust `RustWorker` | Python `SourceRuntime` | Rust crate is a new component; CEDIA integration point is open |
| DAG definition | declarative YAML (AIP-85), generated | Python factories (`common.airflow.ingestion_docker_dag`) | Both read the same `configs/ingestions/<id>.yml`; generated DAGs use `BashOperator` where CEDIA uses `DockerOperator`. Which to adopt in CEDIA is open |
| dbt | dbt Core 1.12.3 (`AGENTS.md`, `Contex.md`) | dbt-core 1.12.3, dbt-postgres 1.10.1 | Aligned on 2026-11-09 by decision of the project owner (latest release is 1.12.6; generated models also build on it). Pins: `dbt/requirements.txt`; image tag: `DBT_CORE_VERSION` |
| Bronze shape | typed table per dataset (`bronze.<source>__<dataset>`) | same, `configs/ingestions/<id>.yml` `datasets.<ds>.bronze_table` | Aligned: key columns + `payload` + `_ingested_at`, `_batch_id`, `_landing_uri`, `_record_hash`, PK `(keys, _batch_id)`. Differences: CEDIA's `ops` batch tables, change-only persistence (`_change_type`) and per-source Landing page formats are not replicated; our `_batch_id` is derived from the payload SHA-256 and our quarantine is `bronze_quarantine.rejected_payloads`. The table name follows `<source_system>__<dataset>`, true for the 29 pinned datasets |
| Rust toolchain | `1.80` | n/a | Current dependencies (aws-sdk-s3, axum) need a newer compiler; the crate builds on stable and pins no `rust-version` |
| Apache Tika, obscura.sh | in stack | not present in the main code (only archived specs) | Tika in local infra; Obscura reached over CDP (`OBSCURA_CDP_URL`) |
| Compose Topology | Single root `docker-compose.yml` | `deploy/local/docker-compose.yml` | Aligned on 2026-11-10: all services (db, rustfs, tika, runtime, obscura, airflow) consolidated into a single compose project with explicit `container_name` entries. See `docs/docker_architecture.md` |

Do not edit `vendor/cedia` from this repository. Changes to CEDIA go through its own branches and PRs.
To move the pin: `git -C vendor/cedia fetch && git -C vendor/cedia checkout <commit>`, then commit the
submodule pointer here and re-run `make test`.
