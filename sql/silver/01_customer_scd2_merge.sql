-- =============================================================================
-- Silver: silver.customer -- SCD Type 2, identity-resolved golden record
-- =============================================================================
-- Source:   bronze.raw_crm  (one row per CRM change event, Phase 6 registry)
-- Grain:    one row per customer per attribute-version
-- Runs:     once per incremental batch (one day's landed bronze.raw_crm rows),
--           parameterized by :batch_date -- this is the CDC pattern chosen in
--           Phase 2 Section 4.1 (merge on natural key + source_updated_at).
--
-- IDENTITY RESOLUTION NOTE (see docs/07-silver-layer.md Section 3): in a real
-- bank, CRM/Servicing/Bureau each mint their OWN local customer identifier and
-- this step would first need deterministic/fuzzy matching (name + DOB +
-- SSN-last4 blocking, survivorship scoring) to produce customer_id below.
-- Phase 5's synthetic generator uses one shared customer_id across sources as
-- a documented simplification, so this MERGE's join key is already the
-- resolved golden ID. The matching algorithm this step WOULD run is specified
-- in full in docs/07-silver-layer.md Section 3 and exercised independently in
-- sql/silver/local_execution/identity_resolution_demo.py against a
-- deliberately-fragmented synthetic sample, so the logic is proven even
-- though the main dataset doesn't need it.
-- =============================================================================

-- STEP 1: close out any currently-open version whose attributes changed in
-- this batch (classic two-pass SCD2 -- MERGE alone can't both close an old
-- row and open a new one for the same natural key in one pass).
MERGE INTO silver.customer AS tgt
USING (
    SELECT *
    FROM bronze.raw_crm
    WHERE source_updated_at::DATE = :batch_date
) AS src
ON tgt.customer_id = src.customer_id
   AND tgt.is_current = TRUE
WHEN MATCHED AND (
       tgt.mailing_city       IS DISTINCT FROM src.mailing_city
    OR tgt.mailing_state      IS DISTINCT FROM src.mailing_state
    OR tgt.mailing_zip        IS DISTINCT FROM src.mailing_zip
    OR tgt.customer_segment   IS DISTINCT FROM src.customer_segment
    OR tgt.employment_status  IS DISTINCT FROM src.employment_status
    OR tgt.email              IS DISTINCT FROM src.email
    OR tgt.phone_number       IS DISTINCT FROM src.phone_number
) THEN UPDATE SET
    is_current         = FALSE,
    effective_end_date = src.source_updated_at,
    _silver_updated_ts = CURRENT_TIMESTAMP();

-- STEP 2: open a new current version for (a) brand-new customer_ids this
-- batch, or (b) customer_ids Step 1 just closed out.
INSERT INTO silver.customer (
    customer_sk, customer_id, first_name, last_name, date_of_birth, ssn_last4,
    email, phone_number, mailing_city, mailing_state, mailing_zip,
    customer_segment, employment_status,
    effective_start_date, effective_end_date, is_current,
    source_system, _silver_load_ts
)
SELECT
    nextval('silver.customer_sk_seq'),
    src.customer_id, src.first_name, src.last_name, src.date_of_birth, src.ssn_last4,
    src.email, src.phone_number, src.mailing_city, src.mailing_state, src.mailing_zip,
    src.customer_segment, src.employment_status,
    src.source_updated_at            AS effective_start_date,
    TIMESTAMP '9999-12-31'           AS effective_end_date,
    TRUE                             AS is_current,
    src.source_system,
    CURRENT_TIMESTAMP()
FROM (
    SELECT * FROM bronze.raw_crm WHERE source_updated_at::DATE = :batch_date
) AS src
LEFT JOIN silver.customer cur
    ON cur.customer_id = src.customer_id
   AND cur.is_current = TRUE
   AND cur.effective_start_date = src.source_updated_at   -- Step 1 already opened it if attrs changed
WHERE cur.customer_id IS NULL;

-- Why "IS DISTINCT FROM" and not "<>": NULL-safe comparison -- employment_status
-- or email being newly populated (NULL -> value) must count as a change;
-- standard <> would silently ignore NULL-involving comparisons.
