{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Catálogo de Documentos y Evidencia (Section 6.16 y 6.17)
-- Mantiene trazabilidad al enlace oficial y al contenido original en RustFS S3.
-- ==============================================================================

WITH staging AS (
    SELECT * FROM {{ ref('stg_idrc_funding_calls') }}
),

portal_docs AS (
    SELECT
        MD5(opportunity_id || '_portal_web') AS document_id,
        opportunity_id,
        'Página Oficial y Bases de Convocatoria' AS document_title,
        'official_portal_guidelines' AS document_type,
        'en' AS language,
        official_url,
        _landing_uri AS evidence_storage_uri,
        _record_hash AS integrity_hash,
        _batch_id,
        _extracted_at,
        CURRENT_TIMESTAMP AS _silver_transformed_at
    FROM staging
),

binary_docs AS (
    SELECT
        MD5(s.opportunity_id || '_' || (b.value ->> 'file_name')) AS document_id,
        s.opportunity_id,
        COALESCE(b.value ->> 'file_name', 'Documento Adjunto') AS document_title,
        COALESCE(b.value ->> 'document_type', 'guidelines') AS document_type,
        CASE
            WHEN b.value ->> 'file_name' LIKE '%_PT%' OR b.value ->> 'file_name' LIKE '%_pt%' THEN 'pt'
            WHEN b.value ->> 'file_name' LIKE '%_SP%' OR b.value ->> 'file_name' LIKE '%_sp%' OR b.value ->> 'file_name' LIKE '%_ES%' THEN 'es'
            ELSE 'en'
        END AS language,
        COALESCE(b.value ->> 'source_url', s.official_url) AS official_url,
        COALESCE(b.value ->> 's3_uri', s._landing_uri) AS evidence_storage_uri,
        COALESCE(b.value ->> 'sha256_hash', s._record_hash) AS integrity_hash,
        s._batch_id,
        s._extracted_at,
        CURRENT_TIMESTAMP AS _silver_transformed_at
    FROM staging s,
    LATERAL jsonb_array_elements(
        CASE 
            WHEN s.downloaded_binaries IS NOT NULL AND jsonb_typeof(s.downloaded_binaries) = 'array' 
            THEN s.downloaded_binaries 
            ELSE '[]'::jsonb 
        END
    ) AS b(value)
)

SELECT * FROM portal_docs
UNION ALL
SELECT * FROM binary_docs
