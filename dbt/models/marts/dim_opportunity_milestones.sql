{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Hitos y Plazos Temporales (Kimball Core)
-- ==============================================================================

SELECT milestone_id, opportunity_id, milestone_type, milestone_date_at, milestone_raw_text, days_remaining, _batch_id, _silver_transformed_at
FROM {{ ref('idrc_milestones_int') }}

UNION ALL

SELECT milestone_id, opportunity_id, milestone_type, milestone_date_at, milestone_raw_text, days_remaining, _batch_id, _silver_transformed_at
FROM {{ ref('cyted_milestones_int') }}

UNION ALL

SELECT milestone_id, opportunity_id, milestone_type, milestone_date_at, milestone_raw_text, days_remaining, _batch_id, _silver_transformed_at
FROM {{ ref('worldbank_milestones_int') }}

UNION ALL

SELECT milestone_id, opportunity_id, milestone_type, milestone_date_at, milestone_raw_text, days_remaining, _batch_id, _silver_transformed_at
FROM {{ ref('ungm_milestones_int') }}
