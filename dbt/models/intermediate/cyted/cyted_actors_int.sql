{{
    config(
        materialized='table',
        schema='silver'
    )
}}

WITH base AS (
    SELECT DISTINCT
        call_code,
        funded_by_raw,
        emisor_raw,
        contact_raw,
        _batch_id
    FROM {{ ref('cyted_actors_stg') }}
),

unioned_roles AS (
    SELECT
        call_code AS opportunity_id,
        'financiador' AS contextual_role,
        funded_by_raw AS actor_name,
        _batch_id
    FROM base

    UNION ALL

    SELECT
        call_code AS opportunity_id,
        'emisor' AS contextual_role,
        emisor_raw AS actor_name,
        _batch_id
    FROM base

    UNION ALL

    SELECT
        call_code AS opportunity_id,
        'autoridad_contratante' AS contextual_role,
        contact_raw AS actor_name,
        _batch_id
    FROM base
)

SELECT
    MD5(opportunity_id || '_' || contextual_role || '_' || actor_name) AS actor_rel_id,
    opportunity_id,
    contextual_role,
    actor_name,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM unioned_roles
