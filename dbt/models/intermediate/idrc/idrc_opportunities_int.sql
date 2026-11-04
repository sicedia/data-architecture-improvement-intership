{{
    config(
        materialized='table',
        schema='silver'
    )
}}

WITH base AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY call_code
            ORDER BY _extracted_at DESC NULLS LAST, _ingested_at DESC
        ) AS rn
    FROM {{ ref('idrc_opportunities_stg') }}
)

SELECT
    call_code AS opportunity_id,
    'idrc' AS source_system,
    COALESCE(
        REGEXP_REPLACE(shortlink_raw, '^.*/node/', 'IDRC-NODE-'),
        call_code
    ) AS source_id,
    title_raw AS title,
    summary_raw AS summary,
    call_for_raw AS opportunity_type,
    CASE
        WHEN LOWER(call_for_raw) LIKE '%faq%' OR LOWER(title_raw) LIKE '%faq%' THEN 'update'
        WHEN LOWER(title_raw) LIKE '%strategy%' OR LOWER(title_raw) LIKE '%guidance%' THEN 'context'
        ELSE 'actionable_opportunity'
    END AS unit_type,
    CASE
        WHEN UPPER(status_raw) LIKE '%CLOSED%' THEN 'CLOSED'
        WHEN UPPER(status_raw) LIKE '%ANTICIPAT%' THEN 'ANTICIPATORY'
        ELSE 'OPEN'
    END AS status,
    CASE
        WHEN UPPER(status_raw) NOT LIKE '%CLOSED%'
             AND (NULLIF(deadline_iso_raw, '')::timestamptz IS NULL OR NULLIF(deadline_iso_raw, '')::timestamptz > CURRENT_TIMESTAMP)
        THEN TRUE
        ELSE FALSE
    END AS is_active,
    official_url,
    CASE
        WHEN LOWER(call_for_raw) LIKE '%fellowship%' OR LOWER(call_for_raw) LIKE '%scholarship%' THEN 'individual'
        ELSE 'consorcio_obligatorio'
    END AS modality_type,
    ARRAY['universidad', 'centro_investigacion', 'ong'] AS applicant_types,
    CASE
        WHEN LOWER(countries_raw) LIKE '%ecuador%'
             OR LOWER(geographic_scope_raw) LIKE '%global%'
             OR LOWER(geographic_scope_raw) LIKE '%latin%'
             OR LOWER(geographic_scope_raw) LIKE '%lac%'
        THEN TRUE
        ELSE FALSE
    END AS ecuador_eligible,
    COALESCE(NULLIF(countries_raw, ''), geographic_scope_raw, 'Global') AS geographic_scope,
    program_name_raw AS program_name,
    topics_raw AS thematic_areas,
    NULLIF(deadline_iso_raw, '')::timestamptz AS deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM base
WHERE rn = 1
