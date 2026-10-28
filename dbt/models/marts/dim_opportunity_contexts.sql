{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Contextos de Oportunidad (Section 5.3 y 6.2)
-- Representa contenedores semánticos no accionables por sí mismos (programas, iniciativas).
-- ==============================================================================

WITH staging AS (
    SELECT * FROM {{ ref('stg_idrc_funding_calls') }}
    WHERE program_name IS NOT NULL AND program_name != ''
)

SELECT
    MD5(opportunity_id || '_' || program_name) AS context_id,
    opportunity_id,
    'programme' AS context_type,
    program_name AS context_name,
    source_system,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM staging
