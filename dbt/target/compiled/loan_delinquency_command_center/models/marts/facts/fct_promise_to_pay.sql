select
    p.ptp_id,
    l.loan_sk,
    cu.customer_sk,
    p.contact_id,
    col.collector_sk,
    cast(strftime(p.ptp_created_date, '%Y%m%d') as integer) as ptp_created_date_sk,
    cast(strftime(p.ptp_promised_date, '%Y%m%d') as integer) as ptp_promised_date_sk,
    p.ptp_amount,
    p.ptp_status,
    p.amount_paid_against_ptp,
    case when p.fulfillment_date is not null
         then cast(strftime(p.fulfillment_date, '%Y%m%d') as integer) end as fulfillment_date_sk,
    case when p.fulfillment_date is not null
         then date_diff('day', p.ptp_created_date, p.fulfillment_date) end as days_to_fulfillment
from "dbt_warehouse"."stg"."stg_collections__ptp" p
join "dbt_warehouse"."marts"."dim_loan" l
    on l.loan_id = p.loan_id
   and p.ptp_created_date >= l.effective_start_date and p.ptp_created_date < l.effective_end_date
join "dbt_warehouse"."marts"."dim_customer" cu
    on cu.customer_id = p.customer_id
   and p.ptp_created_date >= cu.effective_start_date and p.ptp_created_date < cu.effective_end_date
left join "dbt_warehouse"."marts"."dim_collector" col
    on col.collector_id = p.collector_id
   and p.ptp_created_date >= col.effective_start_date and p.ptp_created_date < col.effective_end_date