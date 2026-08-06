
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select loan_id
from "dbt_warehouse"."marts"."dim_loan"
where loan_id is null



  
  
      
    ) dbt_internal_test