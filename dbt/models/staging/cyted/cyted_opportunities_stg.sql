{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    COALESCE(NULLIF(TRIM(payload ->> 'title'), ''), call_code) AS title_raw,
    COALESCE(TRIM(payload ->> 'description'), TRIM(payload ->> 'text_snippet')) AS summary_raw,
    COALESCE(TRIM(payload ->> 'instrument_name'), 'Redes Temáticas') AS modality_raw,
    COALESCE(TRIM(payload ->> 'area_tematica'), 'General') AS area_tematica_raw,
    TRIM(payload ->> 'linea_investigacion') AS linea_investigacion_raw,
    COALESCE(TRIM(payload ->> 'convocatoria_year'), '2026') AS convocatoria_year_raw,
    UPPER(TRIM(COALESCE(payload ->> 'status', 'OPEN'))) AS status_raw,
    TRIM(payload ->> 'url') AS official_url,
    TRIM(payload ->> 'countries') AS countries_raw,
    TRIM(payload ->> 'deadline_raw') AS deadline_raw,
    TRIM(payload ->> 'deadline_iso') AS deadline_iso_raw,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _ingested_at
FROM {{ source('bronze', 'cyted__funding_calls') }}
