
    
    

with all_values as (

    select
        ptp_status as value_field,
        count(*) as n_records

    from "dbt_warehouse"."marts"."fct_promise_to_pay"
    group by ptp_status

)

select *
from all_values
where value_field not in (
    'Open','Kept','Broken','Partial'
)


