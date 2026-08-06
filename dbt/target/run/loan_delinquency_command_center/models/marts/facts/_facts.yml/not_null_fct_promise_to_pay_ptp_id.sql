
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select ptp_id
from "dbt_warehouse"."marts"."fct_promise_to_pay"
where ptp_id is null



  
  
      
    ) dbt_internal_test