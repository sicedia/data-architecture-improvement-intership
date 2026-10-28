{{
    config(
        materialized='view',
        schema='silver'
    )
}}

-- ==============================================================================
-- Vista Consolidada: Oportunidades Normalizadas con Contextos y Hitos
-- Facilita el consumo unificado para aplicaciones externas y APIs.
-- ==============================================================================

WITH opps AS (
    SELECT * FROM {{ ref('fct_opportunities') }}
),

contexts AS (
    SELECT
        opportunity_id,
        STRING_AGG(context_name, ', ') AS programas_asociados
    FROM {{ ref('dim_opportunity_contexts') }}
    GROUP BY opportunity_id
),

actors AS (
    SELECT
        opportunity_id,
        STRING_AGG(DISTINCT actor_name, ', ') AS actores_involucrados
    FROM {{ ref('dim_opportunity_actors') }}
    WHERE contextual_role = 'financiador'
    GROUP BY opportunity_id
),

milestones AS (
    SELECT
        opportunity_id,
        milestone_date_at AS fecha_cierre,
        milestone_raw_text AS fecha_cierre_texto,
        days_remaining AS dias_para_cierre
    FROM {{ ref('dim_opportunity_milestones') }}
    WHERE milestone_type = 'cierre_presentacion'
),

finance AS (
    SELECT
        opportunity_id,
        condition_type AS tipo_condicion_financiera,
        raw_amount_text AS presupuesto_texto,
        original_currency AS moneda_original,
        duration_text AS duracion
    FROM {{ ref('dim_opportunity_financial_conditions') }}
)

SELECT
    o.opportunity_id,
    o.source_system,
    o.title AS titulo_oportunidad,
    o.summary AS resumen_alcance,
    o.opportunity_type AS tipo_convocatoria,
    o.status AS estado_convocatoria,
    o.is_active AS esta_vigente,
    m.fecha_cierre,
    m.fecha_cierre_texto,
    m.dias_para_cierre,
    f.presupuesto_texto,
    f.moneda_original,
    f.duracion,
    COALESCE(c.programas_asociados, 'Sin Programa Específico') AS programas,
    COALESCE(a.actores_involucrados, 'IDRC') AS financiadores,
    o.thematic_areas AS areas_tematicas,
    o.official_url AS enlace_oficial,
    o._batch_id,
    o._landing_uri,
    o._silver_transformed_at
FROM opps o
LEFT JOIN contexts c ON o.opportunity_id = c.opportunity_id
LEFT JOIN actors a ON o.opportunity_id = a.opportunity_id
LEFT JOIN milestones m ON o.opportunity_id = m.opportunity_id
LEFT JOIN finance f ON o.opportunity_id = f.opportunity_id
