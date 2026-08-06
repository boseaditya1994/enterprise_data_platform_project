
  
    
    

    create  table
      "dbt_warehouse"."int"."int_collector_scd2__dbt_tmp"
  
    as (
      

with source as (
    select * from "dbt_warehouse"."stg"."stg_collectors__roster"
),

versioned as (
    select
        *,
        lead(source_updated_at) over (
            partition by collector_id order by source_updated_at
        ) as next_updated_at
    from source
)

select
    row_number() over (order by collector_id, source_updated_at) as collector_sk,
    collector_id, collector_name, team_name, collector_level, manager_name,
    source_updated_at as effective_start_date,
    coalesce(next_updated_at, timestamp '9999-12-31') as effective_end_date,
    (next_updated_at is null) as is_current
from versioned
    );
  
  