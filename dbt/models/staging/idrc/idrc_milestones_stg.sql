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
    TRIM(payload ->> 'clarifications_deadline') AS clarifications_deadline_raw,
    TRIM(payload ->> 'noticedate') AS noticedate_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'idrc__funding_calls') }}
