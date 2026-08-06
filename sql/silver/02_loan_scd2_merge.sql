-- =============================================================================
-- Silver: silver.loan -- SCD Type 2
-- =============================================================================
-- Sources:  bronze.raw_servicing_loans (initial terms, one row per loan)
--         + bronze.raw_servicing_loan_events (RESTRUCTURE / CHARGE_OFF /
--           SETTLEMENT / FRAUD_FLAG -- Phase 5's loan_events stream)
--
-- DESIGN CHOICE: unlike silver.customer (01_customer_scd2_merge.sql), which
-- applies a true incremental daily MERGE because CRM changes are independent,
-- unordered attribute edits, silver.loan is built as a WINDOWED FULL-HISTORY
-- REBUILD. Loan lifecycle flags (restructured/charged-off/settled/fraud) are
-- monotonic and cumulative -- once true, always true for that loan -- so the
-- correct value "as of" any change-point is a simple "does an earlier event
-- of this type exist" check, which is naturally a set-based query rather
-- than a per-day loop. This is also the standard way to BOOTSTRAP any SCD2
-- table from full source history (a one-time backfill), vs. the day-by-day
-- MERGE pattern used for steady-state incremental batches.
--
-- In production this SQL would run as a dbt incremental model with an
-- is_incremental() branch: full rebuild on first run, then only recompute
-- change-points for loan_ids present in today's bronze.raw_servicing_loan_events
-- batch (Phase 9).
-- =============================================================================

CREATE OR REPLACE TABLE silver.loan AS
WITH change_points AS (
    -- every date on which SOMETHING about a loan changed: origination itself,
    -- plus every lifecycle event
    SELECT loan_id, origination_date::TIMESTAMP AS effective_date FROM bronze.raw_servicing_loans
    UNION
    SELECT loan_id, event_date FROM bronze.raw_servicing_loan_events
),
flags_as_of AS (
    SELECT
        cp.loan_id,
        cp.effective_date,
        COALESCE(BOOL_OR(e.event_type = 'RESTRUCTURE' AND e.event_date <= cp.effective_date), FALSE) AS restructured_flag,
        COALESCE(BOOL_OR(e.event_type = 'CHARGE_OFF'  AND e.event_date <= cp.effective_date), FALSE) AS charge_off_flag,
        MIN(CASE WHEN e.event_type = 'CHARGE_OFF' AND e.event_date <= cp.effective_date THEN e.event_date END) AS charge_off_date,
        COALESCE(BOOL_OR(e.event_type = 'SETTLEMENT' AND e.event_date <= cp.effective_date), FALSE) AS settlement_flag,
        COALESCE(BOOL_OR(e.event_type = 'FRAUD_FLAG'  AND e.event_date <= cp.effective_date), FALSE) AS fraud_flag
    FROM change_points cp
    LEFT JOIN bronze.raw_servicing_loan_events e ON e.loan_id = cp.loan_id
    GROUP BY cp.loan_id, cp.effective_date
),
versioned AS (
    SELECT
        f.loan_id,
        s.application_id,
        s.primary_customer_id,
        s.loan_type,
        s.loan_sub_product,
        s.origination_date,
        s.disbursement_date,
        s.origination_amount,
        s.interest_rate,
        s.loan_term_months,
        s.is_secured_flag,
        s.collateral_type,
        s.due_day_of_month,
        s.risk_band_code,
        f.restructured_flag,
        f.charge_off_flag,
        f.charge_off_date,
        f.settlement_flag,
        f.fraud_flag,
        f.effective_date AS effective_start_date,
        LEAD(f.effective_date) OVER (PARTITION BY f.loan_id ORDER BY f.effective_date) AS next_effective_date,
        s.source_system
    FROM flags_as_of f
    JOIN bronze.raw_servicing_loans s ON s.loan_id = f.loan_id
)
SELECT
    ROW_NUMBER() OVER (ORDER BY loan_id, effective_start_date) AS loan_sk,
    loan_id, application_id, primary_customer_id, loan_type, loan_sub_product,
    origination_date, disbursement_date, origination_amount, interest_rate,
    loan_term_months, is_secured_flag, collateral_type, due_day_of_month,
    risk_band_code, restructured_flag, charge_off_flag, charge_off_date,
    settlement_flag, fraud_flag,
    effective_start_date,
    COALESCE(next_effective_date, TIMESTAMP '9999-12-31') AS effective_end_date,
    (next_effective_date IS NULL) AS is_current,
    source_system,
    CURRENT_TIMESTAMP() AS _silver_load_ts
FROM versioned;

-- Note: "account" (from the original brief's Silver entity list of
-- "customer, loan, account, payment, contact, delinquency") is intentionally
-- NOT a separate table here -- see docs/07-silver-layer.md Section 2 for why
-- it's modeled as 1:1 with silver.loan in this single-product-per-loan design.
