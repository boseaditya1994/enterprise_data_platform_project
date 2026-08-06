
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    collector_sk as unique_field,
    count(*) as n_records

from "dbt_warehouse"."marts"."dim_collector"
where collector_sk is not null
group by collector_sk
having count(*) > 1



  
  
      
    ) dbt_internal_test