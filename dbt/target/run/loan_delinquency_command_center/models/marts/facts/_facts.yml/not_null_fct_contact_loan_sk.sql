
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select loan_sk
from "dbt_warehouse"."marts"."fct_contact"
where loan_sk is null



  
  
      
    ) dbt_internal_test