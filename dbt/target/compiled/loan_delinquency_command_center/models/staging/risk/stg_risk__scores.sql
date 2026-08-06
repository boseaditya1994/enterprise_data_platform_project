select
    loan_id,
    customer_id,
    cast(file_date as date) as file_date,
    internal_risk_score,
    risk_band_code,
    fraud_flag,
    source_system
from "dbt_warehouse"."bronze"."raw_risk_scores"