{#- Producto OI model of the harness-only fixture source. Hand-designed (a business decision, unlike
    staging and intermediate, which are generated from contracts). Real Producto OI models are
    designed per source by the silver-designer agent (F5) and approved at Gate H2. -#}
{{ config(tags=['source_fixture', 'producto_oi']) }}

select
    id as record_id,
    name as record_name,
    source_system,
    bronze_batch_id as source_batch_id,
    bronze_ingested_at as last_ingested_at
from (
    select *, 'fixture'::text as source_system
    from {{ ref('int_fixture__records') }}
) as current_records
