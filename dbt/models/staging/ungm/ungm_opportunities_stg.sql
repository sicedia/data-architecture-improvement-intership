{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'notice_id'), ''), call_code) AS notice_id_raw,
    TRIM(payload ->> 'reference') AS agency_reference_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'title'), ''), call_code) AS title_raw,
    COALESCE(TRIM(payload ->> 'description'), 'UN Procurement Notice') AS summary_raw,
    COALESCE(TRIM(payload ->> 'opportunity_type'), 'Request for proposal (RFP)') AS modality_raw,
    COALESCE(TRIM(payload ->> 'organization'), 'United Nations') AS organization_raw,
    UPPER(TRIM(COALESCE(payload ->> 'status', 'OPEN'))) AS status_raw,
    COALESCE(TRIM(payload ->> 'beneficiary_country'), 'Global') AS beneficiary_country_raw,
    TRIM(payload ->> 'url') AS official_url,
    TRIM(payload ->> 'deadline_raw') AS deadline_raw,
    TRIM(payload ->> 'published_date') AS published_date_raw,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _ingested_at
FROM {{ source('bronze', 'ungm__notices') }}
