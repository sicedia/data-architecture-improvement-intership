-- Local warehouse schemas of this project. The typed bronze tables are generated from
-- configs/contracts (bronze/tables.sql, `make generate-bronze`) and applied by scripts/apply_bronze.sh.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS bronze_quarantine;

-- Typed bronze tables (bronze.<source>__<dataset>) are generated from the data contracts:
-- bronze/tables.sql, applied by `make bronze-apply` (also run by `make infra-up`).

-- Payloads the triage did not recognise or that failed validation; raw bytes stay in Landing.
CREATE TABLE IF NOT EXISTS bronze_quarantine.rejected_payloads (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       TEXT        NOT NULL,
    dataset      TEXT        NOT NULL,
    sha256       CHAR(64)    NOT NULL,
    reason       TEXT        NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, dataset, sha256)
);
