{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    TRIM(payload ->> 'deadline_raw') AS deadline_raw,
    TRIM(payload ->> 'deadline_iso') AS deadline_iso_raw,
    TRIM(payload ->> 'publication_date') AS publication_date_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'cyted__funding_calls') }}
