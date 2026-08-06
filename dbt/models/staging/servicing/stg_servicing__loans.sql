select
    loan_id,
    application_id,
    primary_customer_id,
    loan_type,
    loan_sub_product,
    cast(origination_date as timestamp) as origination_date,
    cast(disbursement_date as timestamp) as disbursement_date,
    origination_amount,
    interest_rate,
    loan_term_months,
    is_secured_flag,
    collateral_type,
    due_day_of_month,
    risk_band_code,
    source_system
from {{ source('bronze', 'raw_servicing_loans') }}
