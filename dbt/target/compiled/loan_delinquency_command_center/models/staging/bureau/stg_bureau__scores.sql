select
    customer_id,
    cast(file_date as date) as file_date,
    source_updated_at,
    fico_score,
    risk_band_code,
    is_late_arrival,
    source_system
from "dbt_warehouse"."bronze"."raw_bureau"