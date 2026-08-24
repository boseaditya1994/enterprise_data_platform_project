select
    loan_id,
    event_type,
    cast(event_date as timestamp) as event_date,
    details
from "LOAN_DELINQUENCY_CC"."STAGING"."raw_servicing_loan_events"