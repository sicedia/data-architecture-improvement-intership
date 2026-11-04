{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'id'), ''), call_code) AS notice_id_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'bid_description'), ''), call_code) AS title_raw,
    COALESCE(TRIM(payload ->> 'notice_text'), TRIM(payload ->> 'project_name')) AS summary_raw,
    COALESCE(TRIM(payload ->> 'procurement_method_name'), 'RFQ') AS modality_raw,
    COALESCE(TRIM(payload ->> 'notice_type'), 'SPN') AS notice_type_raw,
    UPPER(TRIM(COALESCE(payload ->> 'notice_status'), 'OPEN')) AS status_raw,
    COALESCE(TRIM(payload ->> 'project_id'), 'P_GLOBAL') AS parent_program_id_raw,
    COALESCE(TRIM(payload ->> 'project_name'), 'World Bank Development Project') AS parent_program_name_raw,
    COALESCE(TRIM(payload ->> 'project_ctry_name'), 'Global') AS country_raw,
    TRIM(payload ->> 'url') AS official_url,
    TRIM(payload ->> 'submission_deadline_date') AS deadline_raw,
    TRIM(payload ->> 'noticedate') AS noticedate_raw,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _ingested_at
FROM {{ source('bronze', 'worldbank__procurement') }}
