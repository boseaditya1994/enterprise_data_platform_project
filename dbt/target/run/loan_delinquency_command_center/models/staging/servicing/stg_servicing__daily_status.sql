
  
  create view "dbt_warehouse"."stg"."stg_servicing__daily_status__dbt_tmp" as (
    select
    loan_id,
    customer_id,
    cast(snapshot_date as date) as snapshot_date,
    bucket_index,
    delinquency_bucket,
    dpd,
    restructured_flag,
    fraud_flag,
    outstanding_balance,
    loan_purpose_code   -- null pre-2025-03-02 (additive schema drift, Phase 6 Section 5); no special-casing needed
from "dbt_warehouse"."bronze"."raw_servicing_daily_status"
  );
