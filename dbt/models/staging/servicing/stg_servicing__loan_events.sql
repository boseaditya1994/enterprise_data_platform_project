select
    loan_id,
    event_type,
    cast(event_date as timestamp) as event_date,
    details
from {{ source('bronze', 'raw_servicing_loan_events') }}
