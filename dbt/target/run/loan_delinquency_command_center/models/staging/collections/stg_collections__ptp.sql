
  
  create view "dbt_warehouse"."stg"."stg_collections__ptp__dbt_tmp" as (
    select
    ptp_id,
    loan_id,
    customer_id,
    contact_id,
    coalesce(collector_ref_id, collector_id) as collector_id,
    cast(ptp_created_date as date) as ptp_created_date,
    cast(ptp_promised_date as date) as ptp_promised_date,
    ptp_amount,
    ptp_status,
    amount_paid_against_ptp,
    cast(fulfillment_date as date) as fulfillment_date
from "dbt_warehouse"."bronze"."raw_collections_ptp"
  );
