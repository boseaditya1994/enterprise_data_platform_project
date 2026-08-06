
    
    

select
    loan_id as unique_field,
    count(*) as n_records

from "dbt_warehouse"."bronze"."raw_servicing_loans"
where loan_id is not null
group by loan_id
having count(*) > 1


