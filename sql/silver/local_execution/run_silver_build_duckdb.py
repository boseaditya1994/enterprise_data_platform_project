"""
Executes the Silver layer build logic (SCD2, CDC merge, dedup, conform) for
REAL against the actual Bronze-style CSVs Phase 5 generated -- using DuckDB
as a stand-in for Snowflake/Databricks (both support the same MERGE INTO
syntax used in the sibling .sql files; this script runs equivalent logic
so the design is provably correct, not just narrated).

Usage:
    cd sql/silver/local_execution
    python3 run_silver_build_duckdb.py
"""
import glob
import os
import re

import duckdb

HERE = os.path.dirname(__file__)
OUTPUT_ROOT = os.path.join(HERE, "..", "..", "..", "data", "synthetic", "output")
DB_PATH = os.path.join(HERE, "warehouse.duckdb")


def load_bronze_table(con, table_name, date_col_hint=None):
    """
    Loads all CSV partitions for one raw_<table> into bronze.<table_name>,
    synthesizing the _ingestion_ts / _ingestion_date / _batch_id audit
    columns that Phase 6's real ingest_bronze.py adds at ingestion time
    (Phase 5's generator only produces the pre-Bronze business columns).
    """
    table_dir = os.path.join(OUTPUT_ROOT, f"raw_{table_name}")
    is_full_snapshot = os.path.exists(os.path.join(table_dir, "full_snapshot.csv"))

    if is_full_snapshot:
        con.execute(f"""
            CREATE OR REPLACE TABLE bronze.raw_{table_name} AS
            SELECT *,
                   TIMESTAMP '2025-01-01' AS _ingestion_ts,
                   DATE '2025-01-01' AS _ingestion_date
            FROM read_csv_auto('{table_dir}/full_snapshot.csv', union_by_name=true)
        """)
    else:
        glob_path = os.path.join(table_dir, "dt=*", "*.csv")
        con.execute(f"""
            CREATE OR REPLACE TABLE bronze.raw_{table_name} AS
            SELECT *,
                   filename,
                   regexp_extract(filename, 'dt=([0-9\\-]+)', 1) AS _ingestion_date_str
            FROM read_csv_auto('{glob_path}', union_by_name=true, filename=true)
        """)
        con.execute(f"""
            ALTER TABLE bronze.raw_{table_name} ADD COLUMN _ingestion_date DATE;
            UPDATE bronze.raw_{table_name} SET _ingestion_date = _ingestion_date_str::DATE;
            ALTER TABLE bronze.raw_{table_name} ADD COLUMN _row_seq BIGINT;
            CREATE SEQUENCE IF NOT EXISTS seq_raw_{table_name};
            UPDATE bronze.raw_{table_name} SET _row_seq = nextval('seq_raw_{table_name}');
            ALTER TABLE bronze.raw_{table_name} ADD COLUMN _ingestion_ts TIMESTAMP;
            UPDATE bronze.raw_{table_name}
                SET _ingestion_ts = _ingestion_date::TIMESTAMP + (_row_seq % 86400) * INTERVAL 1 SECOND;
            ALTER TABLE bronze.raw_{table_name} DROP COLUMN filename;
            ALTER TABLE bronze.raw_{table_name} DROP COLUMN _ingestion_date_str;
            ALTER TABLE bronze.raw_{table_name} DROP COLUMN _row_seq;
        """)
    n = con.execute(f"SELECT COUNT(*) FROM bronze.raw_{table_name}").fetchone()[0]
    print(f"  loaded bronze.raw_{table_name}: {n:,} rows")


def build_customer_scd2(con):
    print("\n[Silver] building silver.customer (true incremental SCD2, day-by-day)...")
    con.execute("""
        CREATE OR REPLACE TABLE silver.customer (
            customer_sk BIGINT, customer_id VARCHAR, first_name VARCHAR, last_name VARCHAR,
            date_of_birth DATE, ssn_last4 VARCHAR, email VARCHAR, phone_number VARCHAR,
            mailing_city VARCHAR, mailing_state VARCHAR, mailing_zip VARCHAR,
            customer_segment VARCHAR, employment_status VARCHAR,
            effective_start_date TIMESTAMP, effective_end_date TIMESTAMP, is_current BOOLEAN,
            source_system VARCHAR, _silver_load_ts TIMESTAMP, _silver_updated_ts TIMESTAMP
        );
        CREATE SEQUENCE IF NOT EXISTS silver_customer_sk_seq;
    """)
    batch_dates = [r[0] for r in con.execute(
        "SELECT DISTINCT _ingestion_date FROM bronze.raw_crm ORDER BY 1"
    ).fetchall()]

    for batch_date in batch_dates:
        con.execute("""
            UPDATE silver.customer tgt SET
                is_current = FALSE,
                effective_end_date = src.source_updated_at,
                _silver_updated_ts = CURRENT_TIMESTAMP
            FROM (SELECT * FROM bronze.raw_crm WHERE _ingestion_date = ?) src
            WHERE tgt.customer_id = src.customer_id AND tgt.is_current = TRUE
              AND (tgt.mailing_city IS DISTINCT FROM src.mailing_city
                OR tgt.mailing_state IS DISTINCT FROM src.mailing_state
                OR tgt.mailing_zip IS DISTINCT FROM src.mailing_zip
                OR tgt.customer_segment IS DISTINCT FROM src.customer_segment
                OR tgt.employment_status IS DISTINCT FROM src.employment_status)
        """, [batch_date])

        con.execute("""
            INSERT INTO silver.customer
            SELECT
                nextval('silver_customer_sk_seq'), src.customer_id, src.first_name, src.last_name,
                src.date_of_birth, src.ssn_last4, src.email, src.phone_number,
                src.mailing_city, src.mailing_state, src.mailing_zip,
                src.customer_segment, src.employment_status,
                src.source_updated_at, TIMESTAMP '9999-12-31', TRUE,
                src.source_system, CURRENT_TIMESTAMP, NULL
            FROM (SELECT * FROM bronze.raw_crm WHERE _ingestion_date = ?) src
            LEFT JOIN silver.customer cur
                ON cur.customer_id = src.customer_id AND cur.is_current = TRUE
               AND cur.effective_start_date = src.source_updated_at
            WHERE cur.customer_id IS NULL
        """, [batch_date])

    n = con.execute("SELECT COUNT(*) FROM silver.customer").fetchone()[0]
    n_cur = con.execute("SELECT COUNT(*) FROM silver.customer WHERE is_current").fetchone()[0]
    n_hist = con.execute("SELECT COUNT(*) FROM silver.customer WHERE NOT is_current").fetchone()[0]
    print(f"  silver.customer: {n:,} total versions ({n_cur:,} current, {n_hist:,} historical) "
          f"across {len(batch_dates)} incremental batches")


def build_loan_scd2(con):
    print("\n[Silver] building silver.loan (windowed full-history rebuild)...")
    con.execute("""
        CREATE OR REPLACE TABLE silver.loan AS
        WITH change_points AS (
            SELECT loan_id, origination_date::TIMESTAMP AS effective_date FROM bronze.raw_servicing_loans
            UNION
            SELECT loan_id, event_date FROM bronze.raw_servicing_loan_events
        ),
        flags_as_of AS (
            SELECT
                cp.loan_id, cp.effective_date,
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
                f.loan_id, s.application_id, s.primary_customer_id, s.loan_type, s.loan_sub_product,
                s.origination_date, s.disbursement_date, s.origination_amount, s.interest_rate,
                s.loan_term_months, s.is_secured_flag, s.collateral_type, s.due_day_of_month,
                s.risk_band_code, f.restructured_flag, f.charge_off_flag, f.charge_off_date,
                f.settlement_flag, f.fraud_flag, f.effective_date AS effective_start_date,
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
            settlement_flag, fraud_flag, effective_start_date,
            COALESCE(next_effective_date, TIMESTAMP '9999-12-31') AS effective_end_date,
            (next_effective_date IS NULL) AS is_current,
            source_system, CURRENT_TIMESTAMP AS _silver_load_ts
        FROM versioned
    """)
    n = con.execute("SELECT COUNT(*) FROM silver.loan").fetchone()[0]
    n_cur = con.execute("SELECT COUNT(*) FROM silver.loan WHERE is_current").fetchone()[0]
    n_restructured = con.execute("SELECT COUNT(DISTINCT loan_id) FROM silver.loan WHERE restructured_flag").fetchone()[0]
    n_chargeoff = con.execute("SELECT COUNT(DISTINCT loan_id) FROM silver.loan WHERE charge_off_flag").fetchone()[0]
    print(f"  silver.loan: {n:,} total versions ({n_cur:,} current loans), "
          f"{n_restructured:,} restructured, {n_chargeoff:,} charged off")


def build_payment(con):
    print("\n[Silver] building silver.payment (dedup + CDC upsert, single full pass)...")
    con.execute("""
        CREATE OR REPLACE TABLE silver.payment AS
        SELECT * EXCLUDE (rn, _ingestion_ts, _ingestion_date) FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY payment_id ORDER BY _ingestion_ts DESC) AS rn
            FROM bronze.raw_payments
        )
        WHERE rn = 1
    """)
    n_raw = con.execute("SELECT COUNT(*) FROM bronze.raw_payments").fetchone()[0]
    n_silver = con.execute("SELECT COUNT(*) FROM silver.payment").fetchone()[0]
    n_reversals = con.execute("SELECT COUNT(*) FROM silver.payment WHERE is_reversal_flag").fetchone()[0]
    orphans = con.execute("""
        SELECT COUNT(*) FROM silver.payment r
        WHERE r.is_reversal_flag
          AND NOT EXISTS (SELECT 1 FROM silver.payment o WHERE o.payment_id = r.original_payment_id)
    """).fetchone()[0]
    print(f"  silver.payment: {n_raw:,} bronze rows -> {n_silver:,} deduped silver rows "
          f"({n_raw - n_silver:,} duplicates removed)")
    print(f"  reversal referential-integrity check: {orphans} orphaned reversals (expect 0)")


def build_contact(con):
    print("\n[Silver] building silver.contact (union + rename-alias + dedup)...")
    con.execute("""
        CREATE OR REPLACE TABLE silver.contact AS
        WITH unioned AS (
            SELECT contact_id, loan_id, customer_id, contact_date, collector_id,
                   channel_code, contact_direction, contact_outcome, is_rpc_flag,
                   call_duration_seconds, complaint_flag, source_system,
                   is_corrupt_record, _ingestion_ts
            FROM bronze.raw_call_center
            UNION ALL
            SELECT contact_id, loan_id, customer_id, contact_date,
                   COALESCE(collector_ref_id, collector_id) AS collector_id,
                   channel_code, contact_direction, contact_outcome, is_rpc_flag,
                   call_duration_seconds, complaint_flag, source_system,
                   is_corrupt_record, _ingestion_ts
            FROM bronze.raw_collections
        )
        SELECT * EXCLUDE (rn, is_corrupt_record, _ingestion_ts) FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY contact_id ORDER BY _ingestion_ts DESC) AS rn
            FROM unioned
            WHERE NOT COALESCE(is_corrupt_record, FALSE)
        )
        WHERE rn = 1
    """)
    n_cc = con.execute("SELECT COUNT(*) FROM bronze.raw_call_center").fetchone()[0]
    n_col = con.execute("SELECT COUNT(*) FROM bronze.raw_collections").fetchone()[0]
    n_silver = con.execute("SELECT COUNT(*) FROM silver.contact").fetchone()[0]
    n_quarantined = con.execute(
        "SELECT COUNT(*) FROM bronze.raw_call_center WHERE is_corrupt_record "
        "UNION ALL SELECT COUNT(*) FROM bronze.raw_collections WHERE is_corrupt_record"
    ).fetchall()
    n_quarantined = sum(r[0] for r in n_quarantined)
    print(f"  silver.contact: {n_cc:,} call_center + {n_col:,} collections bronze rows "
          f"-> {n_silver:,} silver rows ({n_quarantined:,} corrupt rows quarantined, dupes deduped)")


def build_delinquency(con):
    print("\n[Silver] building silver.delinquency (full-history LAG -- see docs/07 Section 5 "
          "on why this differs from a naive per-batch MERGE)...")
    con.execute("""
        CREATE OR REPLACE TABLE silver.delinquency AS
        SELECT
            loan_id, customer_id, snapshot_date, bucket_index, delinquency_bucket, dpd,
            outstanding_balance, restructured_flag, fraud_flag, loan_purpose_code,
            LAG(delinquency_bucket) OVER (PARTITION BY loan_id ORDER BY snapshot_date) AS prior_day_bucket,
            (LAG(bucket_index) OVER (PARTITION BY loan_id ORDER BY snapshot_date) > 0 AND bucket_index = 0) AS cure_flag,
            (LAG(bucket_index) OVER (PARTITION BY loan_id ORDER BY snapshot_date) IS NOT NULL
             AND bucket_index > LAG(bucket_index) OVER (PARTITION BY loan_id ORDER BY snapshot_date)) AS roll_flag,
            CURRENT_TIMESTAMP AS _silver_load_ts
        FROM bronze.raw_servicing_daily_status
    """)
    n = con.execute("SELECT COUNT(*) FROM silver.delinquency").fetchone()[0]
    n_cures = con.execute("SELECT COUNT(*) FROM silver.delinquency WHERE cure_flag").fetchone()[0]
    n_rolls = con.execute("SELECT COUNT(*) FROM silver.delinquency WHERE roll_flag").fetchone()[0]
    print(f"  silver.delinquency: {n:,} rows, {n_cures:,} cure events, {n_rolls:,} roll events")


def build_promise_to_pay(con):
    print("\n[Silver] building silver.promise_to_pay (upsert on mutable ptp_status)...")
    con.execute("""
        CREATE OR REPLACE TABLE silver.promise_to_pay AS
        SELECT * EXCLUDE (rn, _ingestion_ts) FROM (
            SELECT
                ptp_id, loan_id, customer_id, contact_id,
                COALESCE(collector_ref_id, collector_id) AS collector_id,
                ptp_created_date, ptp_promised_date, ptp_amount, ptp_status,
                amount_paid_against_ptp, fulfillment_date, _ingestion_ts,
                ROW_NUMBER() OVER (PARTITION BY ptp_id ORDER BY _ingestion_ts DESC) AS rn
            FROM bronze.raw_collections_ptp
        )
        WHERE rn = 1
    """)
    n = con.execute("SELECT COUNT(*) FROM silver.promise_to_pay").fetchone()[0]
    dist = con.execute("SELECT ptp_status, COUNT(*) FROM silver.promise_to_pay GROUP BY 1 ORDER BY 2 DESC").fetchall()
    print(f"  silver.promise_to_pay: {n:,} rows -- {dist}")


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = duckdb.connect(DB_PATH)
    con.execute("CREATE SCHEMA bronze; CREATE SCHEMA silver;")

    print("=== Loading Bronze (real Phase 5 generated data) ===")
    for table in [
        "crm", "collectors_daily", "servicing_applications", "servicing_loans",
        "servicing_daily_status", "servicing_loan_events", "servicing_loan_applicant_bridge",
        "payments", "call_center", "collections", "collections_ptp", "bureau", "risk_scores",
    ]:
        load_bronze_table(con, table)

    print("\n=== Building Silver ===")
    build_customer_scd2(con)
    build_loan_scd2(con)
    build_payment(con)
    build_contact(con)
    build_delinquency(con)
    build_promise_to_pay(con)

    print(f"\nDone. DuckDB warehouse persisted at {DB_PATH} (reused by Phase 8 Gold build).")
    con.close()


if __name__ == "__main__":
    main()
