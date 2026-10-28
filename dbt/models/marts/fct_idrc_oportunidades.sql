{{
    config(
        materialized='view',
        schema='silver'
    )
}}

-- Alias de compatibilidad hacia la vista consolidada
SELECT * FROM {{ ref('v_opportunities_consolidated') }}
