
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select payment_id
from "dbt_warehouse"."marts"."fct_payment"
where payment_id is null



  
  
      
    ) dbt_internal_test