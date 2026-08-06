
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select risk_band_sk
from "dbt_warehouse"."marts"."fct_delinquency"
where risk_band_sk is null



  
  
      
    ) dbt_internal_test