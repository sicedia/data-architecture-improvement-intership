{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'currency'), ''), 'USD') AS currency_raw,
    NULLIF(TRIM(payload ->> 'supplier_contract_amount_usd'), '')::numeric AS amount_raw,
    'unknown' AS total_budget_raw,
    FALSE AS cost_sharing_required_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'worldbank__procurement') }}
