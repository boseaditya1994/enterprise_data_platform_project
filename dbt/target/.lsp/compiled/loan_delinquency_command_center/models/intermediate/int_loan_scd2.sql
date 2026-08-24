-- Same windowed full-history pattern as int_customer_scd2, but the "changes"
-- come from a separate lifecycle-events stream rather than repeated
-- attribute rows -- see sql/silver/02_loan_scd2_merge.sql for the original
-- hand-rolled version this was translated from; identical logic here,
-- expressed as a dbt model with ref()s instead of hard-coded table names.


with change_points as (
    select loan_id, cast(origination_date as timestamp) as effective_date
    from "dbt_warehouse"."stg"."stg_servicing__loans"
    union
    select loan_id, event_date as effective_date
    from "dbt_warehouse"."stg"."stg_servicing__loan_events"
),

flags_as_of as (
    select
        cp.loan_id,
        cp.effective_date,
        coalesce(boolor_agg(e.event_type = 'RESTRUCTURE' and e.event_date <= cp.effective_date), false) as restructured_flag,
        coalesce(boolor_agg(e.event_type = 'CHARGE_OFF'  and e.event_date <= cp.effective_date), false) as charge_off_flag,
        min(case when e.event_type = 'CHARGE_OFF' and e.event_date <= cp.effective_date then e.event_date end) as charge_off_date,
        coalesce(boolor_agg(e.event_type = 'SETTLEMENT' and e.event_date <= cp.effective_date), false) as settlement_flag,
        coalesce(boolor_agg(e.event_type = 'FRAUD_FLAG'  and e.event_date <= cp.effective_date), false) as fraud_flag
    from change_points cp
    left join "dbt_warehouse"."stg"."stg_servicing__loan_events" e on e.loan_id = cp.loan_id
    group by cp.loan_id, cp.effective_date
),

versioned as (
    select
        f.loan_id, s.application_id, s.primary_customer_id, s.loan_type, s.loan_sub_product,
        s.origination_date, s.disbursement_date, s.origination_amount, s.interest_rate,
        s.loan_term_months, s.is_secured_flag, s.collateral_type, s.due_day_of_month,
        s.risk_band_code, f.restructured_flag, f.charge_off_flag, f.charge_off_date,
        f.settlement_flag, f.fraud_flag, f.effective_date as effective_start_date,
        lead(f.effective_date) over (partition by f.loan_id order by f.effective_date) as next_effective_date,
        s.source_system
    from flags_as_of f
    join "dbt_warehouse"."stg"."stg_servicing__loans" s on s.loan_id = f.loan_id
)

select
    row_number() over (order by loan_id, effective_start_date) as loan_sk,
    loan_id, application_id, primary_customer_id, loan_type, loan_sub_product,
    origination_date, disbursement_date, origination_amount, interest_rate,
    loan_term_months, is_secured_flag, collateral_type, due_day_of_month,
    risk_band_code, restructured_flag, charge_off_flag, charge_off_date,
    settlement_flag, fraud_flag, effective_start_date,
    coalesce(next_effective_date, timestamp '9999-12-31') as effective_end_date,
    (next_effective_date is null) as is_current,
    source_system
from versioned