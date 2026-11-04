{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Tabla de Hechos Central: Oportunidades Accionables Unificadas (Core V1)
-- Consume directamente de la capa intermedia unificada (int_opportunities__unified)
-- ==============================================================================

WITH unified AS (
    SELECT * FROM {{ ref('int_opportunities__unified') }}
)

SELECT
    opportunity_id,
    source_system,
    source_id AS source_record_id,
    title,
    summary,
    opportunity_type,
    unit_type AS actionability_status,
    status,
    is_active,
    official_url,
    thematic_areas,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _silver_transformed_at
FROM unified
