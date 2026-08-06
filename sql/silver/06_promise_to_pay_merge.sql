-- =============================================================================
-- Silver: silver.promise_to_pay -- conformed PTP commitments
-- =============================================================================
-- Source: bronze.raw_collections_ptp
-- Grain:  one row per ptp_id
--
-- ptp_status is mutable (Open -> Kept/Broken/Partial as the promised date
-- passes and any fulfilling payment posts), so this uses a real upsert
-- (WHEN MATCHED branch), unlike silver.contact's append-only pattern.
-- =============================================================================

MERGE INTO silver.promise_to_pay AS tgt
USING (
    SELECT * EXCLUDE (rn) FROM (
        SELECT
            ptp_id, loan_id, customer_id, contact_id,
            COALESCE(collector_ref_id, collector_id) AS collector_id,   -- same rename alias as silver.contact
            ptp_created_date, ptp_promised_date, ptp_amount, ptp_status,
            amount_paid_against_ptp, fulfillment_date,
            _ingestion_ts, _ingestion_date,
            ROW_NUMBER() OVER (PARTITION BY ptp_id ORDER BY _ingestion_ts DESC) AS rn
        FROM bronze.raw_collections_ptp
        WHERE _ingestion_date = :batch_date
    )
    WHERE rn = 1
) AS src
ON tgt.ptp_id = src.ptp_id
WHEN MATCHED THEN UPDATE SET
    ptp_status               = src.ptp_status,
    amount_paid_against_ptp  = src.amount_paid_against_ptp,
    fulfillment_date         = src.fulfillment_date,
    _silver_updated_ts       = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    ptp_id, loan_id, customer_id, contact_id, collector_id,
    ptp_created_date, ptp_promised_date, ptp_amount, ptp_status,
    amount_paid_against_ptp, fulfillment_date, _silver_load_ts
) VALUES (
    src.ptp_id, src.loan_id, src.customer_id, src.contact_id, src.collector_id,
    src.ptp_created_date, src.ptp_promised_date, src.ptp_amount, src.ptp_status,
    src.amount_paid_against_ptp, src.fulfillment_date, CURRENT_TIMESTAMP()
);
