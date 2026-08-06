
  
    
    

    create  table
      "dbt_warehouse"."marts"."fct_delinquency__dbt_tmp"
  
    as (
      with contacts_with_collector as (
    select loan_id, contact_date, collector_id
    from "dbt_warehouse"."stg"."stg_collections__contacts"
    where collector_id is not null
),

base as (
    select
        d.loan_id, d.customer_id, d.snapshot_date, d.bucket_index, d.delinquency_bucket,
        d.dpd, d.prior_day_bucket, d.outstanding_balance, d.cure_flag, d.roll_flag,
        d.restructured_flag, d.fraud_flag,
        l.loan_sk, cu.customer_sk, l.risk_band_code
    from "dbt_warehouse"."int"."int_delinquency_with_flags" d
    join "dbt_warehouse"."marts"."dim_loan" l
        on l.loan_id = d.loan_id
       and d.snapshot_date >= l.effective_start_date and d.snapshot_date < l.effective_end_date
    join "dbt_warehouse"."marts"."dim_customer" cu
        on cu.customer_id = d.customer_id
       and d.snapshot_date >= cu.effective_start_date and d.snapshot_date < cu.effective_end_date
)

select
    b.loan_id, b.loan_sk, b.customer_sk,
    cast(strftime(b.snapshot_date, '%Y%m%d') as integer) as snapshot_date_sk,
    rb.risk_band_sk,
    cwc.collector_id as assigned_collector_id,
    b.bucket_index, b.delinquency_bucket, b.dpd, b.prior_day_bucket,
    b.outstanding_balance, b.cure_flag, b.roll_flag, b.restructured_flag, b.fraud_flag
from base b
join "dbt_warehouse"."marts"."dim_risk_band" rb on rb.risk_band_code = b.risk_band_code
asof left join contacts_with_collector cwc
    on cwc.loan_id = b.loan_id and b.snapshot_date >= cwc.contact_date
    );
  
  