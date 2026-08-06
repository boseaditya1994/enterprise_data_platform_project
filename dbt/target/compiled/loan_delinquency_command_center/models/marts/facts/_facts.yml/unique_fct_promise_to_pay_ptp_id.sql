
    
    

select
    ptp_id as unique_field,
    count(*) as n_records

from "dbt_warehouse"."marts"."fct_promise_to_pay"
where ptp_id is not null
group by ptp_id
having count(*) > 1


