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
    FROM {{ ref('cyted_opportunities_stg') }}
)

SELECT
    call_code AS opportunity_id,
    'cyted' AS source_system,
    COALESCE(
        NULLIF(TRIM(linea_investigacion_raw), ''),
        'CYTED-' || convocatoria_year_raw || '-RT-' || call_code
    ) AS source_id,
    title_raw AS title,
    summary_raw AS summary,
    modality_raw AS opportunity_type,
    CASE
        WHEN LOWER(title_raw) LIKE '%adjudicación%' OR LOWER(title_raw) LIKE '%aprobada%' THEN 'outcome'
        WHEN LOWER(title_raw) LIKE '%área%' OR LOWER(title_raw) LIKE '%comité%' THEN 'context'
        WHEN LOWER(title_raw) LIKE '%prórroga%' OR LOWER(title_raw) LIKE '%ampliación%' THEN 'update'
        ELSE 'actionable_opportunity'
    END AS unit_type,
    CASE
        WHEN UPPER(status_raw) LIKE '%CLOSED%' THEN 'CLOSED'
        ELSE 'OPEN'
    END AS status,
    CASE
        WHEN UPPER(status_raw) NOT LIKE '%CLOSED%'
             AND (NULLIF(deadline_iso_raw, '')::timestamptz IS NULL OR NULLIF(deadline_iso_raw, '')::timestamptz > CURRENT_TIMESTAMP)
        THEN TRUE
        ELSE FALSE
    END AS is_active,
    official_url,
    'consorcio_obligatorio' AS modality_type,
    ARRAY['universidad', 'centro_investigacion', 'empresa', 'ong'] AS applicant_types,
    TRUE AS ecuador_eligible,
    'Iberoamérica (22 países miembros incluyendo Ecuador)' AS geographic_scope,
    'CYTED - ' || area_tematica_raw AS program_name,
    area_tematica_raw AS thematic_areas,
    NULLIF(deadline_iso_raw, '')::timestamptz AS deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM base
WHERE rn = 1
