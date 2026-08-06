{#
    Standard dbt override: without this, dbt prefixes every custom schema
    with the target schema (e.g. "dev_stg" instead of just "stg"). For this
    project we want clean, predictable schema names (bronze/stg/int/marts/
    seeds/snapshots) that match the layer names used throughout the docs.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
