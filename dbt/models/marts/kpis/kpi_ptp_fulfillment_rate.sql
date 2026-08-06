select
    count(*) as total_ptps,
    count(*) filter (where ptp_status = 'Kept') as kept_ptps,
    kept_ptps::double / nullif(total_ptps, 0) as ptp_fulfillment_rate
from {{ ref('fct_promise_to_pay') }}
