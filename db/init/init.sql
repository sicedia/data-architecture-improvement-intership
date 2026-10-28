-- ==============================================================================
-- IDCI Analytics - Modern Data Stack Initialization Script
-- Schemas: bronze (Raw & Landing Metadata) y silver (Cleaned & Analytical Marts)
-- ==============================================================================

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;

-- Permisos para el usuario administrador
GRANT ALL ON SCHEMA bronze TO idci_admin;
GRANT ALL ON SCHEMA silver TO idci_admin;

-- ==============================================================================
-- 1. Tabla Bronze: IDRC Funding Calls (Convocatorias de financiamiento de IDRC)
--    Sigue estrictamente la estructura institucional y metadatos de auditoría.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS bronze.idrc__funding_calls (
    call_code text NOT NULL,
    institution_name text NULL,
    payload jsonb NOT NULL,
    _ingested_at timestamptz DEFAULT now() NOT NULL,
    _batch_id uuid NOT NULL,
    _landing_uri text NOT NULL,
    _source_record_id text NULL,
    _record_hash text NULL,
    _extracted_at timestamptz NULL,
    CONSTRAINT idrc__funding_calls__batch_id_not_null CHECK (_batch_id IS NOT NULL),
    CONSTRAINT idrc__funding_calls__ingested_at_not_null CHECK (_ingested_at IS NOT NULL),
    CONSTRAINT idrc__funding_calls__landing_uri_not_null CHECK (_landing_uri IS NOT NULL),
    CONSTRAINT idrc__funding_calls_call_code_not_null CHECK (call_code IS NOT NULL),
    CONSTRAINT idrc__funding_calls_payload_not_null CHECK (payload IS NOT NULL),
    CONSTRAINT idrc__funding_calls_pkey PRIMARY KEY (call_code, _batch_id)
);

CREATE INDEX IF NOT EXISTS idx_bronze_idrc_funding_calls_batch 
    ON bronze.idrc__funding_calls USING btree (_batch_id);

CREATE INDEX IF NOT EXISTS idx_bronze_idrc_funding_calls_code 
    ON bronze.idrc__funding_calls USING btree (call_code);

CREATE INDEX IF NOT EXISTS idx_bronze_idrc_funding_calls_inst 
    ON bronze.idrc__funding_calls USING btree (institution_name);

-- ==============================================================================
-- 2. Tabla Bronze: CYTED Funding Calls (Programa Iberoamericano CYTED)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS bronze.cyted__funding_calls (
    call_code text NOT NULL,
    institution_name text NULL,
    payload jsonb NOT NULL,
    _ingested_at timestamptz DEFAULT now() NOT NULL,
    _batch_id uuid NOT NULL,
    _landing_uri text NOT NULL,
    _source_record_id text NULL,
    _record_hash text NULL,
    _extracted_at timestamptz NULL,
    CONSTRAINT cyted__funding_calls_pkey PRIMARY KEY (call_code, _batch_id)
);

CREATE INDEX IF NOT EXISTS idx_bronze_cyted_funding_calls_batch 
    ON bronze.cyted__funding_calls USING btree (_batch_id);

CREATE INDEX IF NOT EXISTS idx_bronze_cyted_funding_calls_code 
    ON bronze.cyted__funding_calls USING btree (call_code);

-- ==============================================================================
-- 3. Tabla Bronze: World Bank Procurement (Licitaciones y Adquisiciones Banco Mundial)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS bronze.worldbank__procurement (
    call_code text NOT NULL,
    institution_name text NULL,
    payload jsonb NOT NULL,
    _ingested_at timestamptz DEFAULT now() NOT NULL,
    _batch_id uuid NOT NULL,
    _landing_uri text NOT NULL,
    _source_record_id text NULL,
    _record_hash text NULL,
    _extracted_at timestamptz NULL,
    CONSTRAINT worldbank__procurement_pkey PRIMARY KEY (call_code, _batch_id)
);

CREATE INDEX IF NOT EXISTS idx_bronze_worldbank_procurement_batch 
    ON bronze.worldbank__procurement USING btree (_batch_id);

CREATE INDEX IF NOT EXISTS idx_bronze_worldbank_procurement_code 
    ON bronze.worldbank__procurement USING btree (call_code);

CREATE INDEX IF NOT EXISTS idx_bronze_worldbank_procurement_inst 
    ON bronze.worldbank__procurement USING btree (institution_name);

-- ==============================================================================
-- 4. Tablas Bronze Dinámicas por Institución
--    Las tablas bronze adicionales (ej: bronze.ukri, bronze.opportunity, etc.)
--    se crean dinámicamente de forma automática por el Data Loader al ejecutar
--    un scraping con el nombre institucional configurado desde Airflow.
-- ==============================================================================
