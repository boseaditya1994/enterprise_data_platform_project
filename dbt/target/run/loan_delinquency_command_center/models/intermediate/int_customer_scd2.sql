
  
    
    

    create  table
      "dbt_warehouse"."int"."int_customer_scd2__dbt_tmp"
  
    as (
      -- Windowed full-history SCD2 build. NOTE on why this isn't a dbt snapshot:
-- a dbt snapshot is designed for a source that only ever exposes CURRENT
-- state, with dbt itself accumulating history across repeated runs.
-- bronze.raw_crm already IS a full historical change log (Phase 5's
-- generator emits one row per version, not just the latest) -- snapshotting
-- it would be redundant with history the source already provides. This
-- model instead derives effective_start/end_date directly via LEAD(), which
-- is both simpler and correct for an already-historized source. See
-- docs/09-dbt-models.md Section 3 for the full design discussion, including
-- where a genuine dbt snapshot WOULD be the right tool (snapshots/ folder).


with source as (
    select * from "dbt_warehouse"."stg"."stg_crm__customers"
),

versioned as (
    select
        *,
        lead(source_updated_at) over (
            partition by customer_id order by source_updated_at
        ) as next_updated_at
    from source
)

select
    md5(customer_id || '|' || cast(source_updated_at as varchar)) as customer_version_id,
    row_number() over (order by customer_id, source_updated_at) as customer_sk,
    customer_id, first_name, last_name, date_of_birth, ssn_last4, email, phone_number,
    mailing_city, mailing_state, mailing_zip, customer_segment, employment_status,
    source_updated_at as effective_start_date,
    coalesce(next_updated_at, timestamp '9999-12-31') as effective_end_date,
    (next_updated_at is null) as is_current,
    source_system
from versioned
    );
  
  