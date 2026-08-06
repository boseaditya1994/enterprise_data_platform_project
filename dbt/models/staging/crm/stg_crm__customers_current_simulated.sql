-- Simulates what raw_crm would look like if the source system only ever
-- exposed CURRENT state (no historical versions) -- the situation dbt
-- snapshots are actually built for. Real bronze.raw_crm already carries
-- full history (Phase 5 generator), so this view deliberately throws that
-- away and keeps only the latest row per customer as of a point in time,
-- controlled by the `crm_current_as_of_ingestion_day` var. See
-- snapshots/snap_crm_current_demo.sql and docs/09-dbt-models.md Section 4.
with source as (
    select *
    from {{ source('bronze', 'raw_crm') }}
    where source_updated_at <= cast('{{ var("crm_current_as_of_ingestion_day") }}' as timestamp)
),

latest_per_customer as (
    select *, row_number() over (partition by customer_id order by source_updated_at desc) as rn
    from source
)

select
    customer_id, first_name, last_name, date_of_birth, ssn_last4, email, phone_number,
    mailing_city, mailing_state, mailing_zip, customer_segment, employment_status,
    source_updated_at, source_system
from latest_per_customer
where rn = 1
