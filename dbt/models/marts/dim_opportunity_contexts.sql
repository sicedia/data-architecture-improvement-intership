{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Contextos y Programas (Kimball Core)
-- ==============================================================================

WITH unified AS (
    SELECT * FROM {{ ref('int_opportunities__unified') }}
)

SELECT
    MD5(opportunity_id || '_' || COALESCE(program_name, 'General')) AS context_id,
    opportunity_id,
    COALESCE(program_name, 'Programa General') AS context_name,
    'program_umbrella' AS context_type,
    thematic_areas,
    geographic_scope,
    ecuador_eligible,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM unified
