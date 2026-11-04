{{
    config(
        materialized='table',
        schema='silver'
    )
}}

WITH base AS (
    SELECT DISTINCT ON (call_code)
        call_code,
        deadline_raw,
        NULLIF(deadline_iso_raw, '')::timestamptz AS deadline_at,
        _batch_id
    FROM {{ ref('cyted_milestones_stg') }}
    ORDER BY call_code, _extracted_at DESC NULLS LAST
)

SELECT
    MD5(call_code || '_closing') AS milestone_id,
    call_code AS opportunity_id,
    'cierre_presentacion' AS milestone_type,
    deadline_at AS milestone_date_at,
    deadline_raw AS milestone_raw_text,
    CASE
        WHEN deadline_at IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM (deadline_at - CURRENT_TIMESTAMP)) / 86400)
        ELSE NULL
    END AS days_remaining,
    _batch_id,
    CURRENT_TIMESTAMP AS _silver_transformed_at
FROM base
WHERE deadline_raw IS NOT NULL
