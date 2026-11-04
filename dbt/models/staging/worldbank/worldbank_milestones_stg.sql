{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    TRIM(payload ->> 'submission_deadline_date') AS deadline_raw,
    TRIM(payload ->> 'noticedate') AS noticedate_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'worldbank__procurement') }}
