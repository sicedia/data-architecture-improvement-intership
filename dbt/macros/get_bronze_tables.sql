{% macro get_bronze_tables() %}
    {% set query %}
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'bronze' 
          AND table_type = 'BASE TABLE'
          AND table_name NOT LIKE 'v_%'
        ORDER BY table_name
    {% endset %}
    {% if execute %}
        {% set results = run_query(query) %}
        {% set tables = results.columns[0].values() %}
    {% else %}
        {% set tables = ['idrc__funding_calls'] %}
    {% endif %}
    {{ return(tables) }}
{% endmacro %}
