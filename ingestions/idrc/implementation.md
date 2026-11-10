# Implementation notes: idrc (phase 4)

Phase 4 runs in this repository, independent of CEDIA (everything stays on this machine:
RustFS for Landing, PostgreSQL for bronze, local Airflow, Obscura in Docker).

| Artifact | Location |
| :--- | :--- |
| Contract (source of truth after H2; the signed draft is `contract.yml` here) | `configs/contracts/idrc/funding_opportunities.yml` |
| Source declaration | `configs/ingestions/idrc.yml` |
| Extractor | `python/scrapagents/extractors/idrc/` (`python -m scrapagents.extractors.idrc`) |
| Generated | `bronze/`, `dbt/models/*/idrc`, `dags/ingest__idrc.yml` (`make generate-*`) |

## Decisions confirmed by the owner (2026-11-10)

1. **Raw bytes (accepted):** original xml/html land as the landing-only dataset
   `funding_opportunities_raw` (content-addressed by SHA-256, never sent to Tika). Same bytes and
   30-day personal-data retention as the signed blueprint's "side objects"; the RustWorker has no
   side-object endpoint, so this is the local shape. dbt never reads them.
2. **Change persistence (accepted for this prototype):** `mode: changes` and
   `max_delete_percentage: 15` stay declared in `configs/ingestions/idrc.yml`. The RustWorker still
   only inserts (`ON CONFLICT DO NOTHING`). Enforcement in the worker or in dbt is deferred past
   this prototype.
3. **Commercial-use permission from IDRC:** still **pending** (human decision). Do not treat a
   successful technical run as legal clearance.
4. **CEDIA clone remote:** `origin` was removed from the local reference clone
   `../cedia-data-platform_prod` so nothing can be pushed there by accident. CEDIA remains a
   reading guide only.

## How to run from Airflow (this Mac)

```bash
# 1. Token for Obscura (never commit it)
export OBSCURA_CDP_TOKEN="$(openssl rand -hex 32)"

# 2. Stacks: warehouse + ingestion (incl. Obscura) + orchestration
make infra-up STACKS="warehouse ingestion orchestration"
docker compose --env-file infra/.env -f infra/ingestion/docker-compose.yml --profile browser up -d obscura

# 3. After rebuilding the Airflow image (extractors + configs), import pools and trigger
docker compose --env-file infra/.env -f infra/orchestration/docker-compose.yml run --rm airflow-init
# UI: http://127.0.0.1:8080  → unpause ingest__idrc → Trigger
```

## Verified locally (2026-11-09)

Obscura (`h4ckf0r0day/obscura:0.2.6`, profile `browser`) → extractor → RustWorker → RustFS +
`bronze.idrc__funding_opportunities`: 4 requests, 11 calls, no block; raw RSS and listing bytes
equal the ones `curl` receives; no `@` in any bronze payload.
