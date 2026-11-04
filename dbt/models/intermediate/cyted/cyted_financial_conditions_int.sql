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
    total_budget_raw AS total_budget,
    minimum_award_raw AS minimum_award,
    maximum_award_raw AS maximum_award,
    funding_rate_raw AS funding_rate,
    cost_sharing_required_raw AS cost_sharing_required,
    duration_raw AS duration_text,
    '20.000 € por año (máximo 80.000 €)' AS raw_amount_text,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM {{ ref('cyted_financial_conditions_stg') }}
ORDER BY call_code, _extracted_at DESC NULLS LAST
