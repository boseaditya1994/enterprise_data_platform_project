-- Conforms two streaming sources into one entity, and resolves the
-- collector_id -> collector_ref_id rename (Phase 6 Section 5) right here
-- in staging so nothing downstream needs to know it ever happened.
with call_center as (
    select
        contact_id, loan_id, customer_id, cast(contact_date as date) as contact_date,
        collector_id, channel_code, contact_direction, contact_outcome, is_rpc_flag,
        call_duration_seconds, complaint_flag, source_system, is_corrupt_record
    from {{ source('bronze', 'raw_call_center') }}
),

collections as (
    select
        contact_id, loan_id, customer_id, cast(contact_date as date) as contact_date,
        coalesce(collector_ref_id, collector_id) as collector_id,   -- rename alias
        channel_code, contact_direction, contact_outcome, is_rpc_flag,
        call_duration_seconds, complaint_flag, source_system, is_corrupt_record
    from {{ source('bronze', 'raw_collections') }}
),

unioned as (
    select * from call_center
    union all
    select * from collections
),

deduped as (
    select *, row_number() over (partition by contact_id order by contact_date desc) as rn
    from unioned
    where not coalesce(is_corrupt_record, false)   -- quarantined at Bronze, never promoted (Phase 6 Section 6)
)

select
    contact_id, loan_id, customer_id, contact_date, collector_id, channel_code,
    contact_direction, contact_outcome, is_rpc_flag, call_duration_seconds,
    complaint_flag, source_system
from deduped
where rn = 1
