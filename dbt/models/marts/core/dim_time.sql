with days as (
    select unnest(generate_series(date '2023-01-01', date '2027-12-31', interval 1 day)) as full_date
)

select
    cast(strftime(full_date, '%Y%m%d') as integer) as date_sk,
    full_date,
    dayname(full_date) as day_of_week_name,
    extract(day from full_date) as day_of_month,
    extract(doy from full_date) as day_of_year,
    extract(week from full_date) as week_of_year,
    extract(month from full_date) as month_number,
    monthname(full_date) as month_name,
    extract(quarter from full_date) as quarter,
    extract(year from full_date) as year,
    (dayofweek(full_date) in (0, 6)) as is_weekend,
    (full_date in (
        date '2025-01-01', date '2025-01-20', date '2025-02-17',
        date '2025-05-26', date '2025-06-19'
    )) as is_us_bank_holiday,
    (full_date = last_day(full_date)) as is_month_end
from days
