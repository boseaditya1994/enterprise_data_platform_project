select
    count(*) as total_ptps,
    count(case when ptp_status = 'Kept' then 1 end) as kept_ptps,
    kept_ptps::double / nullif(total_ptps, 0) as ptp_fulfillment_rate
from {{ ref('fct_promise_to_pay') }}