
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with child as (
    select loan_sk as from_field
    from "dbt_warehouse"."marts"."fct_payment"
    where loan_sk is not null
),

parent as (
    select loan_sk as to_field
    from "dbt_warehouse"."marts"."dim_loan"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null



  
  
      
    ) dbt_internal_test