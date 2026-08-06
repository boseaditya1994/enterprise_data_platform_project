
  
  create view "dbt_warehouse"."stg"."stg_crm__customers__dbt_tmp" as (
    -- Thin staging: rename/cast only, no business logic (dbt staging convention).
select
    customer_id,
    first_name,
    last_name,
    date_of_birth,
    ssn_last4,
    email,
    phone_number,
    mailing_city,
    mailing_state,
    mailing_zip,
    customer_segment,
    employment_status,
    source_updated_at,
    source_system,
    change_reason
from "dbt_warehouse"."bronze"."raw_crm"
  );
