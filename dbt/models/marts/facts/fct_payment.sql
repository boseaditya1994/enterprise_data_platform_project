select
    p.payment_id,
    l.loan_sk,
    c.customer_sk,
    cast({{ "to_char(p.payment_date, 'YYYYMMDD')" if target.type == 'snowflake' else "strftime(p.payment_date, '%Y%m%d')" }} as integer) as payment_date_sk,
    ch.channel_sk,
    p.payment_amount,
    p.scheduled_amount,
    p.payment_type,
    p.payment_method,
    p.payment_status,
    p.is_reversal_flag,
    p.nsf_flag,
    p.original_payment_id
from {{ ref('stg_payments__payments') }} p
join {{ ref('dim_loan') }} l
    on l.loan_id = p.loan_id
   and p.payment_date >= l.effective_start_date and p.payment_date < l.effective_end_date
join {{ ref('dim_customer') }} c
    on c.customer_id = p.customer_id
   and p.payment_date >= c.effective_start_date and p.payment_date < c.effective_end_date
left join {{ ref('dim_channel') }} ch
    on ch.channel_code = case p.payment_method
        when 'ACH' then 'ACH' when 'Debit Card' then 'DEBIT_CARD'
        when 'Check' then 'CHECK' when 'Wire' then 'WIRE' when 'Cash' then 'CASH'
       end
-- Rows that fail these joins (customer_id null from a corrupt-record
-- scenario, or an "Extra" payment dated before its loan's origination --
-- see docs/08-gold-layer.md Section 3.2) are intentionally excluded, not
-- silently coerced -- same behavior as the hand-rolled Gold build.
