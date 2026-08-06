select
    ct.contact_id,
    l.loan_sk,
    cu.customer_sk,
    cast(strftime(ct.contact_date, '%Y%m%d') as integer) as contact_date_sk,
    col.collector_sk,
    ch.channel_sk,
    ct.contact_direction,
    ct.contact_outcome,
    ct.is_rpc_flag,
    ct.call_duration_seconds,
    ct.complaint_flag
from {{ ref('stg_collections__contacts') }} ct
join {{ ref('dim_loan') }} l
    on l.loan_id = ct.loan_id
   and ct.contact_date >= l.effective_start_date and ct.contact_date < l.effective_end_date
join {{ ref('dim_customer') }} cu
    on cu.customer_id = ct.customer_id
   and ct.contact_date >= cu.effective_start_date and ct.contact_date < cu.effective_end_date
left join {{ ref('dim_collector') }} col
    on col.collector_id = ct.collector_id
   and ct.contact_date >= col.effective_start_date and ct.contact_date < col.effective_end_date
left join {{ ref('dim_channel') }} ch on ch.channel_code = ct.channel_code
