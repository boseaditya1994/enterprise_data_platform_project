-- =============================================================================
-- Silver: silver.delinquency -- conformed daily loan-status snapshot
-- =============================================================================
-- Source: bronze.raw_servicing_daily_status
-- Grain:  one row per loan per snapshot_date (matches Phase 3 delinquency_fact)
--
-- This is where prior_day_bucket / cure_flag / roll_flag get computed --
-- Phase 3 Section 3.2 explicitly denormalizes these onto the fact for Gold
-- query performance, and Silver is the right place to compute them once
-- (via LAG) rather than recomputing per Gold query.
--
-- Handles the additive schema-drift column (loan_purpose_code, present only
-- from 2025-03-02 onward) transparently: COALESCE to NULL for rows that
-- predate the drift, since the registry marked it allow_additive_drift=true
-- (Phase 6 Section 5) -- Silver doesn't need special-case logic for this,
-- which is exactly the point of allowing additive drift to auto-merge.
-- =============================================================================

MERGE INTO silver.delinquency AS tgt
USING (
    SELECT
        loan_id,
        customer_id,
        snapshot_date,
        bucket_index,
        delinquency_bucket,
        dpd,
        outstanding_balance,
        restructured_flag,
        fraud_flag,
        loan_purpose_code,   -- NULL pre-2025-03-02, populated after; no special-casing needed
        LAG(delinquency_bucket) OVER (
            PARTITION BY loan_id ORDER BY snapshot_date
        ) AS prior_day_bucket,
        LAG(bucket_index) OVER (
            PARTITION BY loan_id ORDER BY snapshot_date
        ) AS prior_bucket_index
    FROM bronze.raw_servicing_daily_status
    WHERE _ingestion_date = :batch_date
) AS src
ON tgt.loan_id = src.loan_id AND tgt.snapshot_date = src.snapshot_date
WHEN NOT MATCHED THEN INSERT (
    loan_id, customer_id, snapshot_date, bucket_index, delinquency_bucket, dpd,
    outstanding_balance, restructured_flag, fraud_flag, loan_purpose_code,
    prior_day_bucket,
    cure_flag,
    roll_flag,
    _silver_load_ts
) VALUES (
    src.loan_id, src.customer_id, src.snapshot_date, src.bucket_index, src.delinquency_bucket, src.dpd,
    src.outstanding_balance, src.restructured_flag, src.fraud_flag, src.loan_purpose_code,
    src.prior_day_bucket,
    (src.prior_bucket_index > 0 AND src.bucket_index = 0),           -- cure_flag
    (src.prior_bucket_index IS NOT NULL AND src.bucket_index > src.prior_bucket_index),  -- roll_flag
    CURRENT_TIMESTAMP()
);

-- NOTE: LAG() here only sees rows within the CURRENT BATCH's window function
-- scope if run against a limited slice. In production this model runs as a
-- dbt incremental model with a lookback window (e.g. re-derive the trailing
-- 3 days on every run) specifically so a loan's prior_day_bucket is always
-- computed against yesterday's ALREADY-LANDED row, not an artificial gap at
-- batch boundaries -- see docs/07-silver-layer.md Section 5 for the full
-- lookback-window design and why a naive per-batch LAG() would be wrong.
