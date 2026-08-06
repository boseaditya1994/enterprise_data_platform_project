{#
    Single source of truth for bucket_index -> label. Any model or test
    needing the label instead of the raw index calls this macro rather than
    re-writing the CASE expression -- the exact kind of duplication that
    caused Phase 1's root-cause problem (different teams' definitions of
    "which bucket is this" silently drifting apart).
#}
{% macro bucket_label(bucket_index_col) -%}
    case {{ bucket_index_col }}
        when 0 then 'Current'
        when 1 then '1-29'
        when 2 then '30-59'
        when 3 then '60-89'
        when 4 then '90+'
        when 5 then 'Charged-off'
        when 6 then 'Settled'
    end
{%- endmacro %}
