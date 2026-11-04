{{
    config(
        materialized='table',
        schema='silver'
    )
}}

SELECT DISTINCT ON (call_code)
    MD5(call_code || '_financial') AS condition_id,
    call_code AS opportunity_id,
    'USD' AS currency,
    NULL::numeric AS total_budget,
    NULL::numeric AS minimum_award,
    NULL::numeric AS maximum_award,
    '100%' AS funding_rate,
    cost_sharing_required_raw AS cost_sharing_required,
    'Según términos de referencia' AS duration_text,
    'Confidencial / unknown' AS raw_amount_text,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM {{ ref('ungm_financial_conditions_stg') }}
ORDER BY call_code, _extracted_at DESC NULLS LAST
