
  
    
    

    create  table
      "dbt_warehouse"."marts"."dim_collector__dbt_tmp"
  
    as (
      select * from "dbt_warehouse"."int"."int_collector_scd2"
    );
  
  