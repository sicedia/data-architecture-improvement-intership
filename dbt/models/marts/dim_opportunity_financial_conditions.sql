{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Condiciones Financieras (Kimball Core)
-- Unifica los modelos intermedios de finanzas por institución
-- ==============================================================================

SELECT
    condition_id,
    opportunity_id,
    'subvencion_investigacion' AS condition_type,
    raw_amount_text,
    currency AS original_currency,
    total_budget,
    minimum_award,
    maximum_award,
    funding_rate,
    cost_sharing_required,
    duration_text,
    _batch_id,
    _silver_transformed_at
FROM {{ ref('idrc_financial_conditions_int') }}

UNION ALL

SELECT
    condition_id,
    opportunity_id,
    'subvencion_red_tematica' AS condition_type,
    raw_amount_text,
    currency AS original_currency,
    total_budget,
    minimum_award,
    maximum_award,
    funding_rate,
    cost_sharing_required,
    duration_text,
    _batch_id,
    _silver_transformed_at
FROM {{ ref('cyted_financial_conditions_int') }}

UNION ALL

SELECT
    condition_id,
    opportunity_id,
    'licitacion_adquisicion' AS condition_type,
    raw_amount_text,
    currency AS original_currency,
    total_budget,
    minimum_award,
    maximum_award,
    funding_rate,
    cost_sharing_required,
    duration_text,
    _batch_id,
    _silver_transformed_at
FROM {{ ref('worldbank_financial_conditions_int') }}

UNION ALL

SELECT
    condition_id,
    opportunity_id,
    'adquisicion_onu' AS condition_type,
    raw_amount_text,
    currency AS original_currency,
    total_budget,
    minimum_award,
    maximum_award,
    funding_rate,
    cost_sharing_required,
    duration_text,
    _batch_id,
    _silver_transformed_at
FROM {{ ref('ungm_financial_conditions_int') }}
