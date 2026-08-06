
select *
from "dbt_warehouse"."marts"."dim_loan"
where origination_amount < 0
