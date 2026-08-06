{#
    Custom generic test: fails if any row has a negative value in the given
    column. Used on balance/amount columns where negative would indicate a
    real data problem (as opposed to payment_fact.payment_amount, which is
    deliberately negative for reversals -- that column is NOT tested with this).
#}
{% test non_negative(model, column_name) %}
select *
from {{ model }}
where {{ column_name }} < 0
{% endtest %}
