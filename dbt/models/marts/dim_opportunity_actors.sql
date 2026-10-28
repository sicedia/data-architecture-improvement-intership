{{
    config(
        materialized='table',
        schema='silver'
    )
}}

-- ==============================================================================
-- Dimensión: Organismos y Actores con Roles Contextuales (Section 6.3)
-- Cada actor se relaciona con un rol específico respecto a la oportunidad.
-- ==============================================================================

WITH staging AS (
    SELECT * FROM {{ ref('stg_idrc_funding_calls') }}
),

-- 1. Rol: Emisor / Autoridad Gestora (IDRC)
issuers AS (
    SELECT
        MD5(opportunity_id || '_idrc_emisor') AS actor_rel_id,
        opportunity_id,
        'International Development Research Centre (IDRC)' AS actor_name,
        'emisor_autoridad_gestora' AS contextual_role,
        official_url AS contact_reference,
        _batch_id
    FROM staging
),

-- 2. Rol: Financiador (extraído del campo funded_by)
funders AS (
    SELECT
        MD5(opportunity_id || '_financiador_' || COALESCE(funded_by_text, 'idrc')) AS actor_rel_id,
        opportunity_id,
        COALESCE(NULLIF(funded_by_text, ''), 'International Development Research Centre (IDRC)') AS actor_name,
        'financiador' AS contextual_role,
        NULL AS contact_reference,
        _batch_id
    FROM staging
),

-- 3. Rol: Punto de Contacto (si existe)
contacts AS (
    SELECT
        MD5(opportunity_id || '_contacto') AS actor_rel_id,
        opportunity_id,
        point_of_contact AS actor_name,
        'punto_contacto' AS contextual_role,
        point_of_contact AS contact_reference,
        _batch_id
    FROM staging
    WHERE point_of_contact IS NOT NULL AND point_of_contact != ''
)

SELECT * FROM issuers
UNION ALL
SELECT * FROM funders
UNION ALL
SELECT * FROM contacts
