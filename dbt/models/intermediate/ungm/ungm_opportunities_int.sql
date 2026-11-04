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
    FROM {{ ref('ungm_opportunities_stg') }}
)

SELECT
    call_code AS opportunity_id,
    'ungm' AS source_system,
    COALESCE(
        NULLIF(TRIM(agency_reference_raw), ''),
        'UNGM-' || notice_id_raw
    ) AS source_id,
    title_raw AS title,
    summary_raw AS summary,
    modality_raw AS opportunity_type,
    CASE
        WHEN LOWER(modality_raw) LIKE '%rfi%' OR LOWER(modality_raw) LIKE '%pre-bid%' THEN 'context'
        WHEN LOWER(title_raw) LIKE '%award%' OR LOWER(status_raw) LIKE '%closed%' THEN 'outcome'
        WHEN LOWER(title_raw) LIKE '%revision%' OR LOWER(agency_reference_raw) LIKE '%,%' THEN 'update'
        ELSE 'actionable_opportunity'
    END AS unit_type,
    CASE
        WHEN UPPER(status_raw) LIKE '%CLOSED%' THEN 'CLOSED'
        ELSE 'OPEN'
    END AS status,
    CASE
        WHEN UPPER(status_raw) NOT LIKE '%CLOSED%'
        THEN TRUE
        ELSE FALSE
    END AS is_active,
    official_url,
    CASE
        WHEN LOWER(modality_raw) LIKE '%consultant%' THEN 'individual'
        ELSE 'consorcio_permitido'
    END AS modality_type,
    ARRAY['empresa', 'universidad', 'ong', 'persona_natural'] AS applicant_types,
    CASE
        WHEN LOWER(beneficiary_country_raw) LIKE '%ecuador%' OR LOWER(beneficiary_country_raw) LIKE '%global%' THEN TRUE
        ELSE FALSE
    END AS ecuador_eligible,
    beneficiary_country_raw AS geographic_scope,
    organization_raw AS program_name,
    'UN Procurement - ' || organization_raw AS thematic_areas,
    NULL::timestamptz AS deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM base
WHERE rn = 1
