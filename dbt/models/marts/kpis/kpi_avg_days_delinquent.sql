select
    t.full_date as snapshot_date,
    avg(d.dpd) as avg_days_delinquent
from {{ ref('fct_delinquency') }} d
join {{ ref('dim_time') }} t on t.date_sk = d.snapshot_date_sk
where d.bucket_index between 1 and 4
group by t.full_date
