{{
    config(
        materialized='table',
        schema='silver'
    )
}}

WITH base AS (
    SELECT DISTINCT ON (call_code)
        call_code,
        official_url,
        binaries_json,
        _landing_uri,
        _record_hash,
        _batch_id
    FROM {{ ref('idrc_documents_stg') }}
    ORDER BY call_code, _extracted_at DESC NULLS LAST
),

portal_doc AS (
    SELECT
        MD5(call_code || '_portal_web') AS document_id,
        call_code AS opportunity_id,
        'Página Oficial y Bases de Convocatoria (IDRC)' AS document_title,
        'official_portal_guidelines' AS document_type,
        'en' AS language,
        'agency_general' AS scope,
        official_url,
        _landing_uri AS evidence_storage_uri,
        _record_hash AS integrity_hash,
        _batch_id,
        CURRENT_TIMESTAMP AS _silver_transformed_at
    FROM base
),

binary_docs AS (
    SELECT
        MD5(b.call_code || '_' || (elem.value ->> 'file_name')) AS document_id,
        b.call_code AS opportunity_id,
        COALESCE(elem.value ->> 'file_name', 'Documento Adjunto IDRC') AS document_title,
        COALESCE(elem.value ->> 'document_type', 'guidelines') AS document_type,
        CASE
            WHEN elem.value ->> 'file_name' LIKE '%_PT%' OR elem.value ->> 'file_name' LIKE '%_pt%' THEN 'pt'
            WHEN elem.value ->> 'file_name' LIKE '%_SP%' OR elem.value ->> 'file_name' LIKE '%_es%' THEN 'es'
            WHEN elem.value ->> 'file_name' LIKE '%_FR%' OR elem.value ->> 'file_name' LIKE '%_fr%' THEN 'fr'
            ELSE 'en'
        END AS language,
        CASE
            WHEN LOWER(elem.value ->> 'file_name') LIKE '%general%' OR LOWER(elem.value ->> 'file_name') LIKE '%terms%' THEN 'agency_general'
            ELSE 'opportunity_specific'
        END AS scope,
        COALESCE(elem.value ->> 'source_url', b.official_url) AS official_url,
        COALESCE(elem.value ->> 's3_uri', b._landing_uri) AS evidence_storage_uri,
        COALESCE(elem.value ->> 'sha256_hash', b._record_hash) AS integrity_hash,
        b._batch_id,
        CURRENT_TIMESTAMP AS _silver_transformed_at
    FROM base b,
    LATERAL jsonb_array_elements(
        CASE
            WHEN b.binaries_json IS NOT NULL AND jsonb_typeof(b.binaries_json) = 'array'
            THEN b.binaries_json
            ELSE '[]'::jsonb
        END
    ) AS elem(value)
)

SELECT * FROM portal_doc
UNION ALL
SELECT * FROM binary_docs
