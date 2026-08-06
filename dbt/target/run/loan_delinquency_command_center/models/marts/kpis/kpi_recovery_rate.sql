
  
  create view "dbt_warehouse"."marts"."kpi_recovery_rate__dbt_tmp" as (
    select
    sum(case when pf.payment_type = 'Settlement' then pf.payment_amount else 0 end) as recovered_amount,
    sum(l.origination_amount) as charged_off_original_balance,
    recovered_amount / nullif(charged_off_original_balance, 0) as recovery_rate
from "dbt_warehouse"."marts"."dim_loan" l
left join "dbt_warehouse"."marts"."fct_payment" pf on pf.loan_sk = l.loan_sk
where l.charge_off_flag and l.is_current
  );
