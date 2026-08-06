
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        channel_category as value_field,
        count(*) as n_records

    from "dbt_warehouse"."marts"."dim_channel"
    group by channel_category

)

select *
from all_values
where value_field not in (
    'Live Agent','Automated','Written','Digital Self-Serve'
)



  
  
      
    ) dbt_internal_test