-- Turns the Phase 8 investigation (docs/08-gold-layer.md Section 3.2) into
-- a permanent regression test: we KNOW roughly 1.5% of staged payments
-- won't join to fct_payment (corrupt-record nulls + pre-origination
-- "Extra" payments, both intentionally excluded). If that gap ever grows
-- meaningfully beyond the known baseline, something NEW broke and deserves
-- investigation -- this test fails (returns a row) if the loss rate drifts
-- above 3% (roughly double the observed ~1.47% baseline, leaving room for
-- normal random variation without being a tripwire on every run).
with counts as (
    select
        (select count(*) from "dbt_warehouse"."stg"."stg_payments__payments") as staged_count,
        (select count(*) from "dbt_warehouse"."marts"."fct_payment") as fact_count
)
select
    staged_count,
    fact_count,
    (staged_count - fact_count)::double / staged_count as loss_rate
from counts
where (staged_count - fact_count)::double / staged_count > 0.03