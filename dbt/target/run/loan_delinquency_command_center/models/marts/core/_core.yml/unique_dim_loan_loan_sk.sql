
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    loan_sk as unique_field,
    count(*) as n_records

from "dbt_warehouse"."marts"."dim_loan"
where loan_sk is not null
group by loan_sk
having count(*) > 1



  
  
      
    ) dbt_internal_test