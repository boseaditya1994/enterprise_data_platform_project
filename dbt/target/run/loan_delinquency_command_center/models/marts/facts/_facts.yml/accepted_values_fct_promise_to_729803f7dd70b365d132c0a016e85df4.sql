
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

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



  
  
      
    ) dbt_internal_test