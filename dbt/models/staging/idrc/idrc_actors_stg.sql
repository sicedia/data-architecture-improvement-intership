{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'funded_by'), ''), 'IDRC (International Development Research Centre)') AS funded_by_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'point_of_contact'), ''), TRIM(payload ->> 'author')) AS contact_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'idrc__funding_calls') }}
