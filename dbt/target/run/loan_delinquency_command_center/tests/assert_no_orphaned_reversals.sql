
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- Referential integrity: a reversal's original_payment_id must exist.
-- Fails (returns rows) if any reversal is orphaned.
select r.payment_id, r.original_payment_id
from "dbt_warehouse"."stg"."stg_payments__payments" r
where r.is_reversal_flag
  and not exists (
      select 1 from "dbt_warehouse"."stg"."stg_payments__payments" o
      where o.payment_id = r.original_payment_id
  )
  
  
      
    ) dbt_internal_test