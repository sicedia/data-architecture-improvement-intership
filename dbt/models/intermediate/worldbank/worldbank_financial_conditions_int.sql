{{
    config(
        materialized='table',
        schema='silver'
    )
}}

SELECT DISTINCT ON (call_code)
    MD5(call_code || '_financial') AS condition_id,
    call_code AS opportunity_id,
    currency_raw AS currency,
    amount_raw AS total_budget,
    NULL::numeric AS minimum_award,
    amount_raw AS maximum_award,
    '100%' AS funding_rate,
    cost_sharing_required_raw AS cost_sharing_required,
    'Duración del contrato según pliego de licitación' AS duration_text,
    COALESCE(amount_raw::text || ' ' || currency_raw, 'Presupuesto confidencial / unknown') AS raw_amount_text,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM {{ ref('worldbank_financial_conditions_stg') }}
ORDER BY call_code, _extracted_at DESC NULLS LAST
