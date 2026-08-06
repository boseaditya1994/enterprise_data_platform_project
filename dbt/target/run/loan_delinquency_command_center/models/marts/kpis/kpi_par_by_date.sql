
  
  create view "dbt_warehouse"."marts"."kpi_par_by_date__dbt_tmp" as (
    select
    t.full_date as snapshot_date,
    sum(d.outstanding_balance) as total_balance,
    sum(case when d.bucket_index >= 1 then d.outstanding_balance else 0 end) as balance_30plus,
    sum(case when d.bucket_index >= 2 then d.outstanding_balance else 0 end) as balance_60plus,
    sum(case when d.bucket_index >= 4 then d.outstanding_balance else 0 end) as balance_90plus,
    balance_30plus / nullif(total_balance, 0) as par_30,
    balance_60plus / nullif(total_balance, 0) as par_60,
    balance_90plus / nullif(total_balance, 0) as par_90
from "dbt_warehouse"."marts"."fct_delinquency" d
join "dbt_warehouse"."marts"."dim_time" t on t.date_sk = d.snapshot_date_sk
group by t.full_date
  );
