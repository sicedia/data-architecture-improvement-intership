{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    TRIM(payload ->> 'url') AS official_url,
    payload -> 'downloaded_binaries' AS binaries_json,
    _landing_uri,
    _record_hash,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'ungm__notices') }}
