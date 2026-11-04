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
    FROM {{ ref('worldbank_opportunities_stg') }}
)

SELECT
    call_code AS opportunity_id,
    'worldbank' AS source_system,
    notice_id_raw AS source_id,
    title_raw AS title,
    summary_raw AS summary,
    modality_raw AS opportunity_type,
    CASE
        WHEN LOWER(notice_type_raw) LIKE '%general%' OR LOWER(title_raw) LIKE '%strategy%' THEN 'context'
        WHEN LOWER(status_raw) LIKE '%cancel%' OR LOWER(title_raw) LIKE '%award%' THEN 'outcome'
        WHEN LOWER(title_raw) LIKE '%amendment%' OR LOWER(title_raw) LIKE '%corrigendum%' THEN 'update'
        ELSE 'actionable_opportunity'
    END AS unit_type,
    CASE
        WHEN UPPER(status_raw) LIKE '%CANCEL%' OR UPPER(status_raw) LIKE '%CLOSED%' THEN 'CLOSED'
        ELSE 'OPEN'
    END AS status,
    CASE
        WHEN UPPER(status_raw) NOT LIKE '%CANCEL%' AND UPPER(status_raw) NOT LIKE '%CLOSED%'
             AND (NULLIF(deadline_raw, '')::timestamptz IS NULL OR NULLIF(deadline_raw, '')::timestamptz > CURRENT_TIMESTAMP)
        THEN TRUE
        ELSE FALSE
    END AS is_active,
    official_url,
    CASE
        WHEN LOWER(modality_raw) LIKE '%individual%' THEN 'individual'
        ELSE 'consorcio_permitido'
    END AS modality_type,
    ARRAY['empresa', 'universidad', 'centro_investigacion', 'ong'] AS applicant_types,
    TRUE AS ecuador_eligible,
    country_raw AS geographic_scope,
    parent_program_name_raw AS program_name,
    parent_program_id_raw AS thematic_areas,
    NULLIF(deadline_raw, '')::timestamptz AS deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM base
WHERE rn = 1
