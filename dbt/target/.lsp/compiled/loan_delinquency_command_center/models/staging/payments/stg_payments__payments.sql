-- Dedup (Phase 4/5 scenario #5: duplicate events) belongs in staging, not
-- further downstream, so every model built on top of this one already sees
-- one clean row per payment_id.
with source as (
    select *
    from "LOAN_DELINQUENCY_CC"."STAGING"."raw_payments"
),

deduped as (
    select
        *,
        row_number() over (
            partition by payment_id
            order by ingestion_date desc
        ) as rn
    from source
)

select
    payment_id,
    loan_id,
    customer_id,
    cast(payment_date as date) as payment_date,
    payment_amount,
    scheduled_amount,
    payment_type,
    payment_method,
    payment_status,
    is_reversal_flag,
    nsf_flag,
    original_payment_id,
    cast(effective_date as date) as effective_date,
    cast(ingestion_date as date) as ingestion_date,
    is_late_arrival,
    is_corrupt_record
from deduped
where rn = 1