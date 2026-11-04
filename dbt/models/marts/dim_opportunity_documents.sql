{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Documentos Oficiales y Evidencia (Kimball Core)
-- ==============================================================================

SELECT document_id, opportunity_id, document_title, document_type, language, scope, official_url, evidence_storage_uri, integrity_hash, _batch_id, _silver_transformed_at
FROM {{ ref('idrc_documents_int') }}

UNION ALL

SELECT document_id, opportunity_id, document_title, document_type, language, scope, official_url, evidence_storage_uri, integrity_hash, _batch_id, _silver_transformed_at
FROM {{ ref('cyted_documents_int') }}

UNION ALL

SELECT document_id, opportunity_id, document_title, document_type, language, scope, official_url, evidence_storage_uri, integrity_hash, _batch_id, _silver_transformed_at
FROM {{ ref('worldbank_documents_int') }}

UNION ALL

SELECT document_id, opportunity_id, document_title, document_type, language, scope, official_url, evidence_storage_uri, integrity_hash, _batch_id, _silver_transformed_at
FROM {{ ref('ungm_documents_int') }}
