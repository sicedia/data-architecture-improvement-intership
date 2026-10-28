{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Fechas e Hitos (Section 6.5)
-- Modela hitos temporales identificables (cierre, apertura, publicación).
-- ==============================================================================

WITH staging AS (
    SELECT * FROM {{ ref('stg_idrc_funding_calls') }}
)

SELECT
    MD5(opportunity_id || '_cierre_presentacion') AS milestone_id,
    opportunity_id,
    'cierre_presentacion' AS milestone_type,
    deadline_at AS milestone_date_at,
    deadline_raw_text AS milestone_raw_text,
    CASE
        WHEN deadline_at IS NOT NULL
        THEN GREATEST(0, EXTRACT(DAY FROM (deadline_at - CURRENT_TIMESTAMP))::INTEGER)
        ELSE NULL
    END AS days_remaining,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM staging
WHERE deadline_raw_text IS NOT NULL AND deadline_raw_text != ''
