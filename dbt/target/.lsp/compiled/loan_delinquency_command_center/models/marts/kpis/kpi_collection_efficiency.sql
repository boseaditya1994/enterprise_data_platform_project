select
    t.full_date as snapshot_date,
    sum(case when d.prior_day_bucket != 'Current' then d.outstanding_balance else 0 end) as past_due_balance_at_risk,
    sum(case when d.prior_day_bucket != 'Current' and d.bucket_index = 0
             then d.outstanding_balance else 0 end) as past_due_balance_cured,
    past_due_balance_cured / nullif(past_due_balance_at_risk, 0) as collection_efficiency
from "dbt_warehouse"."marts"."fct_delinquency" d
join "dbt_warehouse"."marts"."dim_time" t on t.date_sk = d.snapshot_date_sk
where d.prior_day_bucket is not null
group by t.full_date