{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    call_code,
    'Programa CYTED (Secretaría General y Organismos Nacionales ONCYTs)' AS funded_by_raw,
    'Secretaría General de CYTED (Madrid, España)' AS emisor_raw,
    COALESCE(NULLIF(TRIM(payload ->> 'point_of_contact'), ''), 'Secretaría General CYTED (sgral@cyted.org)') AS contact_raw,
    _batch_id,
    _extracted_at
FROM {{ source('bronze', 'cyted__funding_calls') }}
