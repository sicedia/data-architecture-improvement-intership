{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'shortlink'), ''), call_code) AS shortlink_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'title'), ''), call_code) AS title_raw,
    COALESCE(TRIM(payload ->> 'description'), TRIM(payload ->> 'text_snippet')) AS summary_raw,
    COALESCE(TRIM(payload ->> 'call_for'), 'Convocatoria General') AS call_for_raw,
    UPPER(TRIM(COALESCE(payload ->> 'status', 'OPEN'))) AS status_raw,
    TRIM(payload ->> 'url') AS official_url,
    TRIM(payload ->> 'geographic_scope') AS geographic_scope_raw,
    TRIM(payload ->> 'countries') AS countries_raw,
    COALESCE(TRIM(payload ->> 'program'), 'IDRC Global Program') AS program_name_raw,
    COALESCE(TRIM(payload ->> 'topics'), 'General') AS topics_raw,
    TRIM(payload ->> 'deadline_raw') AS deadline_raw,
    TRIM(payload ->> 'deadline_iso') AS deadline_iso_raw,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _ingested_at
FROM {{ source('bronze', 'idrc__funding_calls') }}
