
  
    
    

    create  table
      "dbt_warehouse"."marts"."dim_risk_band__dbt_tmp"
  
    as (
      select * from "dbt_warehouse"."seeds"."risk_band_seed"
    );
  
  