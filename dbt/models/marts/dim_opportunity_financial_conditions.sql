{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Condiciones de Financiamiento (Section 6.6)
-- Representa términos económicos tipados en su moneda original.
-- ==============================================================================

WITH staging AS (
    SELECT * FROM {{ ref('stg_idrc_funding_calls') }}
)

SELECT
    MD5(opportunity_id || '_financiamiento') AS condition_id,
    opportunity_id,
    CASE
        WHEN LOWER(budget_raw_text) LIKE '%maximum%' OR LOWER(budget_raw_text) LIKE '%up to%' THEN 'maximum_award'
        WHEN LOWER(budget_raw_text) LIKE '%total%' THEN 'total_budget'
        ELSE 'award_description'
    END AS condition_type,
    budget_raw_text AS raw_amount_text,
    CASE
        WHEN LOWER(budget_raw_text) LIKE '%cad%' OR LOWER(budget_raw_text) LIKE '%ca$%' THEN 'CAD'
        WHEN LOWER(budget_raw_text) LIKE '%usd%' OR LOWER(budget_raw_text) LIKE '%us$%' THEN 'USD'
        WHEN LOWER(budget_raw_text) LIKE '%various%' THEN 'MULTILATERAL_MIXED'
        ELSE 'POR_DEFINIR'
    END AS original_currency,
    duration_raw_text AS duration_text,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM staging
WHERE budget_raw_text IS NOT NULL OR duration_raw_text IS NOT NULL
