
    
    

select
    risk_band_sk as unique_field,
    count(*) as n_records

from "dbt_warehouse"."marts"."dim_risk_band"
where risk_band_sk is not null
group by risk_band_sk
having count(*) > 1


