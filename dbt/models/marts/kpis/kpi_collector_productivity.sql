select
    col.collector_id, col.collector_name, col.team_name,
    count(distinct cf.contact_id) as contacts_made,
    count(distinct ptp.ptp_id) as ptps_obtained,
    sum(case when ptp.ptp_status = 'Kept' then ptp.amount_paid_against_ptp else 0 end) as kept_dollars_collected
from {{ ref('dim_collector') }} col
left join {{ ref('fct_contact') }} cf on cf.collector_sk = col.collector_sk
left join {{ ref('fct_promise_to_pay') }} ptp on ptp.collector_sk = col.collector_sk
where col.is_current
group by col.collector_id, col.collector_name, col.team_name
