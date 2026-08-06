
  
    
    

    create  table
      "dbt_warehouse"."marts"."dim_loan__dbt_tmp"
  
    as (
      select * from "dbt_warehouse"."int"."int_loan_scd2"
    );
  
  