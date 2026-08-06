
  
  create view "dbt_warehouse"."stg"."stg_servicing__loan_events__dbt_tmp" as (
    select
    loan_id,
    event_type,
    cast(event_date as timestamp) as event_date,
    details
from "dbt_warehouse"."bronze"."raw_servicing_loan_events"
  );
