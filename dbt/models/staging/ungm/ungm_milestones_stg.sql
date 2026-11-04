{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    TRIM(payload ->> 'deadline_raw') AS deadline_raw,
    TRIM(payload ->> 'published_date') AS published_date_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'ungm__notices') }}
