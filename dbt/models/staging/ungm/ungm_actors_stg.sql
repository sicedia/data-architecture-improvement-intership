{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'organization'), ''), 'United Nations') AS funded_by_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'organization'), ''), 'United Nations Agency') AS emisor_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'contact_name'), ''), 'UN Procurement Officer') AS contact_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'ungm__notices') }}
