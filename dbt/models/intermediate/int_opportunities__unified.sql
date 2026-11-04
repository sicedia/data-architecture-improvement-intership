{{
    config(
        materialized='table',
        schema='silver'
    )
}}

SELECT
    opportunity_id,
    source_system,
    source_id,
    title,
    summary,
    opportunity_type,
    unit_type,
    status,
    is_active,
    official_url,
    modality_type,
    applicant_types,
    ecuador_eligible,
    geographic_scope,
    program_name,
    thematic_areas,
    deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _silver_transformed_at
FROM {{ ref('idrc_opportunities_int') }}

UNION ALL

SELECT
    opportunity_id,
    source_system,
    source_id,
    title,
    summary,
    opportunity_type,
    unit_type,
    status,
    is_active,
    official_url,
    modality_type,
    applicant_types,
    ecuador_eligible,
    geographic_scope,
    program_name,
    thematic_areas,
    deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _silver_transformed_at
FROM {{ ref('cyted_opportunities_int') }}

UNION ALL

SELECT
    opportunity_id,
    source_system,
    source_id,
    title,
    summary,
    opportunity_type,
    unit_type,
    status,
    is_active,
    official_url,
    modality_type,
    applicant_types,
    ecuador_eligible,
    geographic_scope,
    program_name,
    thematic_areas,
    deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _silver_transformed_at
FROM {{ ref('worldbank_opportunities_int') }}

UNION ALL

SELECT
    opportunity_id,
    source_system,
    source_id,
    title,
    summary,
    opportunity_type,
    unit_type,
    status,
    is_active,
    official_url,
    modality_type,
    applicant_types,
    ecuador_eligible,
    geographic_scope,
    program_name,
    thematic_areas,
    deadline_at,
    _batch_id,
    _landing_uri,
    _record_hash,
    _extracted_at,
    _silver_transformed_at
FROM {{ ref('ungm_opportunities_int') }}
