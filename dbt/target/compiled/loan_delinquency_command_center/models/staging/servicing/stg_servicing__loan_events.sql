select
    loan_id,
    event_type,
    cast(event_date as timestamp) as event_date,
    details
from "dbt_warehouse"."bronze"."raw_servicing_loan_events"