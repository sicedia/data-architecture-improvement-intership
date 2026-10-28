{{
    config(
        materialized='view',
        schema='silver'
    )
}}

{% set bronze_tables = get_bronze_tables() %}

WITH unioned_bronze AS (
    {% for tbl in bronze_tables %}
    SELECT
        COALESCE(call_code, payload ->> 'call_code', payload ->> 'page_code') AS call_code,
        payload,
        _batch_id,
        _landing_uri,
        _source_record_id,
        _record_hash,
        _extracted_at,
        _ingested_at,
        '{{ tbl }}' AS _bronze_table
    FROM "idci_analytics"."bronze"."{{ tbl }}"
    {% if not loop.last %} UNION ALL {% endif %}
    {% endfor %}
),

source_data AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY call_code 
            ORDER BY _extracted_at DESC NULLS LAST, _ingested_at DESC
        ) AS rn
    FROM unioned_bronze
),

parsed_records AS (
    SELECT
        call_code AS opportunity_id,
        COALESCE(
            NULLIF(TRIM(payload ->> 'institution_name'), ''),
            REPLACE(_bronze_table, '__funding_calls', '')
        ) AS source_system,
        call_code AS source_record_id,
        COALESCE(NULLIF(TRIM(payload ->> 'title'), ''), call_code) AS title,
        TRIM(payload ->> 'url') AS official_url,
        COALESCE(TRIM(payload ->> 'call_for'), 'Convocatoria General') AS opportunity_type,
        COALESCE(NULLIF(TRIM(payload ->> 'actionability_status'), ''), 'actionable_opportunity') AS actionability_status,
        COALESCE(NULLIF(TRIM(payload ->> 'modality'), ''), 'other') AS modality,
        UPPER(TRIM(COALESCE(payload ->> 'status', 'OPEN'))) AS status_raw,
        CASE
            WHEN UPPER(TRIM(COALESCE(payload ->> 'status', 'OPEN'))) LIKE '%CLOSED%' THEN 'CLOSED'
            WHEN UPPER(TRIM(COALESCE(payload ->> 'status', 'OPEN'))) LIKE '%ANTICIPAT%' THEN 'ANTICIPATORY'
            ELSE 'OPEN'
        END AS status,
        TRIM(payload ->> 'deadline_raw') AS deadline_raw_text,
        CASE
            WHEN payload ->> 'deadline_iso' IS NOT NULL AND payload ->> 'deadline_iso' != '' 
            THEN (payload ->> 'deadline_iso')::timestamptz
            ELSE NULL
        END AS deadline_at,
        TRIM(payload ->> 'clarifications_deadline') AS clarifications_deadline_raw_text,
        TRIM(payload ->> 'budget_raw') AS budget_raw_text,
        COALESCE(NULLIF(TRIM(payload ->> 'currency'), ''), 'CAD') AS currency,
        NULLIF(TRIM(payload ->> 'minimum_award'), '')::numeric AS minimum_award,
        NULLIF(TRIM(payload ->> 'maximum_award'), '')::numeric AS maximum_award,
        NULLIF(TRIM(payload ->> 'total_budget'), '')::numeric AS total_budget,
        TRIM(payload ->> 'funding_rate') AS funding_rate,
        (payload ->> 'cost_sharing_required')::boolean AS cost_sharing_required,
        COALESCE(NULLIF(TRIM(payload ->> 'consortium_mode'), ''), 'unknown') AS consortium_mode,
        TRIM(payload ->> 'geographic_scope') AS geographic_scope,
        (payload ->> 'ecuador_eligible')::boolean AS ecuador_eligible,
        TRIM(payload ->> 'duration_raw') AS duration_raw_text,
        COALESCE(
            TRIM(payload ->> 'program'),
            TRIM(payload ->> 'institution_name'),
            REPLACE(_bronze_table, '__funding_calls', '')
        ) AS program_name,
        COALESCE(
            TRIM(payload ->> 'funded_by'),
            TRIM(payload ->> 'institution_name'),
            REPLACE(_bronze_table, '__funding_calls', '')
        ) AS funded_by_text,
        COALESCE(TRIM(payload ->> 'topics'), 'General') AS topics_text,
        COALESCE(TRIM(payload ->> 'point_of_contact'), TRIM(payload ->> 'author')) AS point_of_contact,
        COALESCE(TRIM(payload ->> 'description'), TRIM(payload ->> 'text_snippet')) AS summary,
        payload -> 'downloaded_binaries' AS downloaded_binaries,
        _batch_id,
        _landing_uri,
        _record_hash,
        _extracted_at,
        _ingested_at
    FROM source_data
    WHERE rn = 1
)

SELECT * FROM parsed_records
