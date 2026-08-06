
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select channel_sk
from "dbt_warehouse"."marts"."dim_channel"
where channel_sk is null



  
  
      
    ) dbt_internal_test