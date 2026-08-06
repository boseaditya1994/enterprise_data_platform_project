-- Full-history LAG (Phase 7 Section 5 explains why a naive per-batch LAG
-- would be wrong for an incrementally-loaded source; this dbt model runs
-- as a full table rebuild each time, which sidesteps that problem entirely
-- for a project at this scale -- documented tradeoff in docs/09-dbt-models.md).
{{ config(materialized='table') }}

select
    loan_id,
    customer_id,
    snapshot_date,
    bucket_index,
    delinquency_bucket,
    dpd,
    outstanding_balance,
    restructured_flag,
    fraud_flag,
    loan_purpose_code,
    lag(delinquency_bucket) over (partition by loan_id order by snapshot_date) as prior_day_bucket,
    (
        lag(bucket_index) over (partition by loan_id order by snapshot_date) > 0
        and bucket_index = 0
    ) as cure_flag,
    (
        lag(bucket_index) over (partition by loan_id order by snapshot_date) is not null
        and bucket_index > lag(bucket_index) over (partition by loan_id order by snapshot_date)
    ) as roll_flag
from {{ ref('stg_servicing__daily_status') }}
