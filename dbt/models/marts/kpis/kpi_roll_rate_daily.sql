select
    t.full_date as snapshot_date,
    count(case when d.bucket_index >= 1 then 1 end) as delinquent_population,
    count(case when d.roll_flag then 1 end) as rolled_count,
    rolled_count::double / nullif(delinquent_population, 0) as roll_rate
from {{ ref('fct_delinquency') }} d
join {{ ref('dim_time') }} t on t.date_sk = d.snapshot_date_sk
where d.prior_day_bucket is not null
group by t.full_date