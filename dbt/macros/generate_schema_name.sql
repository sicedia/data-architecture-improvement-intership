{% macro generate_schema_name(custom_schema_name, node) -%}
    {# Si se especifica un custom_schema en el modelo, se usa directamente sin prefijo #}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
