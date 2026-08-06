
  
    
    

    create  table
      "dbt_warehouse"."marts"."dim_customer__dbt_tmp"
  
    as (
      select * from "dbt_warehouse"."int"."int_customer_scd2"
    );
  
  