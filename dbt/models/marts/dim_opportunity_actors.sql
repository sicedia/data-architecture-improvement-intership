{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Actores y Roles Contextuales (Kimball Core)
-- Unifica los modelos intermedios de actores por institución
-- ==============================================================================

SELECT actor_rel_id, opportunity_id, contextual_role, actor_name, _batch_id, _silver_transformed_at
FROM {{ ref('idrc_actors_int') }}

UNION ALL

SELECT actor_rel_id, opportunity_id, contextual_role, actor_name, _batch_id, _silver_transformed_at
FROM {{ ref('cyted_actors_int') }}

UNION ALL

SELECT actor_rel_id, opportunity_id, contextual_role, actor_name, _batch_id, _silver_transformed_at
FROM {{ ref('worldbank_actors_int') }}

UNION ALL

SELECT actor_rel_id, opportunity_id, contextual_role, actor_name, _batch_id, _silver_transformed_at
FROM {{ ref('ungm_actors_int') }}
