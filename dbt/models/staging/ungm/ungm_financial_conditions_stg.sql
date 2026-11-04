{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    'unknown' AS total_budget_raw,
    'unknown' AS currency_raw,
    100.0 AS funding_rate_raw,
    FALSE AS cost_sharing_required_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'ungm__notices') }}
