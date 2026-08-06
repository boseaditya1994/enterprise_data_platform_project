-- =============================================================================
-- Silver: silver.payment -- CDC merge on natural key, idempotent, reversal-linked
-- =============================================================================
-- Source: bronze.raw_payments
-- Grain:  one row per payment_id (Phase 2 Section 4.1 CDC pattern: natural
--         key + latest-wins on watermark)
--
-- Two things this MUST handle that customer/loan didn't:
--   1. DUPLICATES (Phase 4/5 scenario #5): the same payment_id can land twice
--      from an upstream retry. Dedup picks the row Bronze ingested LAST
--      (highest _ingestion_ts) as the source of truth for that natural key.
--   2. LATE ARRIVALS (scenario #1): a payment's effective_date can predate
--      its ingestion_date by up to 10 days. Because Bronze partitions by
--      ingestion_date (Phase 6 Section 4) but Silver's natural-key MERGE
--      doesn't care about partitioning at all, a late-arriving payment still
--      merges into the correct historical position by effective_date -- the
--      partitioning choice only affected WHERE Bronze stored the file, never
--      the correctness of this merge.
-- =============================================================================

MERGE INTO silver.payment AS tgt
USING (
    SELECT * EXCLUDE (rn) FROM (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY payment_id
                ORDER BY _ingestion_ts DESC
            ) AS rn
        FROM bronze.raw_payments
        WHERE _ingestion_date = :batch_date
    )
    WHERE rn = 1
) AS src
ON tgt.payment_id = src.payment_id
WHEN MATCHED THEN UPDATE SET
    payment_status      = src.payment_status,
    nsf_flag             = src.nsf_flag,
    is_reversal_flag      = src.is_reversal_flag,
    _silver_updated_ts   = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    payment_id, loan_id, customer_id, payment_date, payment_amount,
    scheduled_amount, payment_type, payment_method, payment_status,
    is_reversal_flag, nsf_flag, original_payment_id, effective_date,
    _silver_load_ts
) VALUES (
    src.payment_id, src.loan_id, src.customer_id, src.payment_date, src.payment_amount,
    src.scheduled_amount, src.payment_type, src.payment_method, src.payment_status,
    src.is_reversal_flag, src.nsf_flag, src.original_payment_id, src.effective_date,
    CURRENT_TIMESTAMP()
);

-- Referential-integrity check (feeds Phase 14 DQ dashboard): every reversal
-- should resolve back to a real original payment. A non-zero result here is
-- exactly the kind of thing that should alert, not fail silently.
-- SELECT COUNT(*) AS orphaned_reversals
-- FROM silver.payment r
-- WHERE r.is_reversal_flag
--   AND NOT EXISTS (SELECT 1 FROM silver.payment o WHERE o.payment_id = r.original_payment_id);
