{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    'World Bank (IBRD / IDA)' AS funded_by_raw,
    'World Bank Group' AS emisor_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'contact_organization'), ''), TRIM(payload ->> 'borrower'), 'Executing Borrowing Agency') AS contact_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'worldbank__procurement') }}
