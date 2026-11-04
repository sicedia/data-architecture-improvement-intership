{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    TRIM(payload ->> 'budget_raw') AS budget_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'currency'), ''), 'CAD') AS currency_raw,
    NULLIF(TRIM(payload ->> 'minimum_award'), '')::numeric AS minimum_award_raw,
    NULLIF(TRIM(payload ->> 'maximum_award'), '')::numeric AS maximum_award_raw,
    NULLIF(TRIM(payload ->> 'total_budget'), '')::numeric AS total_budget_raw,
    TRIM(payload ->> 'funding_rate') AS funding_rate_raw,
    (payload ->> 'cost_sharing_required')::boolean AS cost_sharing_required_raw,
    TRIM(payload ->> 'duration_raw') AS duration_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'idrc__funding_calls') }}
