select
    collector_id,
    collector_name,
    cast(hire_date as date) as hire_date,
    team_name,
    collector_level,
    manager_name,
    is_active_flag,
    source_updated_at,
    change_reason
from "LOAN_DELINQUENCY_CC"."STAGING"."raw_collectors_daily"