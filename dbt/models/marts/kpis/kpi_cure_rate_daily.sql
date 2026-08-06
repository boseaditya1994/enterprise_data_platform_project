select
    t.full_date as snapshot_date,
    count(*) filter (where d.prior_day_bucket != 'Current') as delinquent_population,
    count(*) filter (where d.cure_flag) as cured_count,
    cured_count::double / nullif(delinquent_population, 0) as cure_rate
from {{ ref('fct_delinquency') }} d
join {{ ref('dim_time') }} t on t.date_sk = d.snapshot_date_sk
where d.prior_day_bucket is not null
group by t.full_date
