
  
    
    

    create  table
      "dbt_warehouse"."marts"."dim_channel__dbt_tmp"
  
    as (
      select * from "dbt_warehouse"."seeds"."channel_seed"
    );
  
  