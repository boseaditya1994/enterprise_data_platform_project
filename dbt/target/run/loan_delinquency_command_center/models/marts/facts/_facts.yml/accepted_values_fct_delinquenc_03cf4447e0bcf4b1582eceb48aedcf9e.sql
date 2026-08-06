
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        delinquency_bucket as value_field,
        count(*) as n_records

    from "dbt_warehouse"."marts"."fct_delinquency"
    group by delinquency_bucket

)

select *
from all_values
where value_field not in (
    'Current','1-29','30-59','60-89','90+','Charged-off','Settled'
)



  
  
      
    ) dbt_internal_test