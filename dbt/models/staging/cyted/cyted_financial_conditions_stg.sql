{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    'EUR' AS currency_raw,
    NULLIF(TRIM(payload ->> 'minimum_award'), '')::numeric AS minimum_award_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'maximum_award'), '')::numeric, 20000.00) AS maximum_award_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'total_budget'), '')::numeric, 80000.00) AS total_budget_raw,
    '100%' AS funding_rate_raw,
    TRUE AS cost_sharing_required_raw,
    COALESCE(TRIM(payload ->> 'duration_raw'), 'Hasta 4 años (48 meses)') AS duration_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'cyted__funding_calls') }}
