-- =============================================================================
-- Silver: silver.contact -- conforms Call Center + Collections Platform events
-- =============================================================================
-- Sources: bronze.raw_call_center, bronze.raw_collections
-- Grain:   one row per contact_id
--
-- Conforming work done here:
--   1. UNION two sources with different source_system values into one entity
--   2. Alias the post-2025-04-11 collector_ref_id column back to collector_id
--      (Phase 6 Section 5's resolved schema-drift rename) so downstream Gold
--      never has to know the rename happened at all
--   3. Dedup on contact_id (scenario #5 duplicates), latest ingestion wins
-- =============================================================================

MERGE INTO silver.contact AS tgt
USING (
    WITH unioned AS (
        SELECT contact_id, loan_id, customer_id, contact_date, collector_id,
               channel_code, contact_direction, contact_outcome, is_rpc_flag,
               call_duration_seconds, complaint_flag, source_system,
               is_corrupt_record, _ingestion_ts, _ingestion_date
        FROM bronze.raw_call_center

        UNION ALL

        SELECT contact_id, loan_id, customer_id, contact_date,
               COALESCE(collector_ref_id, collector_id) AS collector_id,   -- rename alias
               channel_code, contact_direction, contact_outcome, is_rpc_flag,
               call_duration_seconds, complaint_flag, source_system,
               is_corrupt_record, _ingestion_ts, _ingestion_date
        FROM bronze.raw_collections
    )
    SELECT * EXCLUDE (rn) FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY contact_id ORDER BY _ingestion_ts DESC
        ) AS rn
        FROM unioned
        WHERE _ingestion_date = :batch_date
          AND NOT COALESCE(is_corrupt_record, FALSE)   -- corrupt rows stay quarantined at Bronze (Phase 6 Section 6)
    )
    WHERE rn = 1
) AS src
ON tgt.contact_id = src.contact_id
WHEN NOT MATCHED THEN INSERT (
    contact_id, loan_id, customer_id, contact_date, collector_id, channel_code,
    contact_direction, contact_outcome, is_rpc_flag, call_duration_seconds,
    complaint_flag, source_system, _silver_load_ts
) VALUES (
    src.contact_id, src.loan_id, src.customer_id, src.contact_date, src.collector_id,
    src.channel_code, src.contact_direction, src.contact_outcome, src.is_rpc_flag,
    src.call_duration_seconds, src.complaint_flag, src.source_system, CURRENT_TIMESTAMP()
);
-- contact_fact rows are immutable once landed (append-only per Phase 6
-- registry's cdc_strategy), so there is deliberately no WHEN MATCHED branch --
-- an update here would indicate a genuinely corrected upstream record, which
-- Phase 14's DQ framework should flag for review rather than this job
-- silently overwriting contact history.
