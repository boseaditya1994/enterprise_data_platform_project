select
    customer_id,
    cast(file_date as date) as file_date,
    source_updated_at,
    fico_score,
    risk_band_code,
    is_late_arrival,
    source_system
from "LOAN_DELINQUENCY_CC"."STAGING"."raw_bureau"