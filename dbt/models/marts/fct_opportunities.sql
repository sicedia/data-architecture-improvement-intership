{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Tabla de Hechos Central: Oportunidades Accionables (Section 5 y 6.1)
-- Representa la unidad institucional común sobre la cual se toma una decisión.
-- ==============================================================================

WITH staging AS (
    SELECT * FROM {{ ref('stg_idrc_funding_calls') }}
)

SELECT
    opportunity_id,
    source_system,
    source_record_id,
    title,
    summary,
    opportunity_type,
    actionability_status,
    status,
    CASE
        WHEN status = 'OPEN' 
             AND (deadline_at IS NULL OR deadline_at > CURRENT_TIMESTAMP)
        THEN TRUE
        ELSE FALSE
    END AS is_active,
    official_url,
    topics_text AS thematic_areas,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _ingested_at,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM staging
