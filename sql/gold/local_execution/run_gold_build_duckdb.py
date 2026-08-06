"""
Builds the Gold star schema (Phase 3) and computes all 12 KPIs (Phase 8)
for REAL against the Silver warehouse Phase 7 built (same DuckDB file --
this script reuses it rather than starting over, exactly like a real
Databricks->Snowflake pipeline reads yesterday's Silver output).

Usage:
    cd sql/gold/local_execution
    python3 run_gold_build_duckdb.py
"""
import os

import duckdb

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "..", "..", "silver", "local_execution", "warehouse.duckdb")

CHANNELS = [
    ("OUTBOUND_CALL", "Outbound Agent Call", "Live Agent", False, True),
    ("INBOUND_CALL", "Inbound Customer Call", "Live Agent", False, False),
    ("SMS", "SMS Reminder", "Automated", True, True),
    ("EMAIL", "Email Reminder", "Automated", True, True),
    ("IVR", "Interactive Voice Response", "Automated", False, True),
    ("LETTER", "Collections Letter", "Written", False, True),
    ("MOBILE_PUSH", "Mobile App Push Notification", "Digital Self-Serve", True, True),
    ("ACH", "ACH Payment", "Digital Self-Serve", True, False),
    ("BRANCH", "In-Branch Payment", "Live Agent", False, False),
    # Added while building Gold (Phase 8): payment_method values on
    # silver.payment don't fully overlap the call-center-centric channel
    # list above -- these fill the gap so fact_payment.channel_sk always
    # resolves. Documented in docs/08-gold-layer.md Section 2.
    ("DEBIT_CARD", "Debit Card Payment", "Digital Self-Serve", True, False),
    ("CHECK", "Mailed Check", "Written", False, False),
    ("WIRE", "Wire Transfer", "Digital Self-Serve", True, False),
    ("CASH", "In-Branch Cash Payment", "Live Agent", False, False),
]
PAYMENT_METHOD_TO_CHANNEL = {
    "ACH": "ACH", "Debit Card": "DEBIT_CARD", "Check": "CHECK",
    "Wire": "WIRE", "Cash": "CASH",
}

RISK_BANDS = [
    ("R1", "Super Prime", 780, 850),
    ("R2", "Prime Plus", 740, 779),
    ("R3", "Prime", 700, 739),
    ("R4", "Near Prime", 660, 699),
    ("R5", "Subprime", 620, 659),
    ("R6", "Deep Subprime", 580, 619),
    ("R7", "High Risk", 300, 579),
]


def build_dim_time(con):
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_time AS
        WITH days AS (
            SELECT unnest(generate_series(DATE '2023-01-01', DATE '2027-12-31', INTERVAL 1 DAY)) AS full_date
        )
        SELECT
            CAST(strftime(full_date, '%Y%m%d') AS INTEGER) AS date_sk,
            full_date,
            dayname(full_date) AS day_of_week_name,
            EXTRACT(day FROM full_date) AS day_of_month,
            EXTRACT(doy FROM full_date) AS day_of_year,
            EXTRACT(week FROM full_date) AS week_of_year,
            EXTRACT(month FROM full_date) AS month_number,
            monthname(full_date) AS month_name,
            EXTRACT(quarter FROM full_date) AS quarter,
            EXTRACT(year FROM full_date) AS year,
            (dayofweek(full_date) IN (0, 6)) AS is_weekend,
            (full_date IN (DATE '2025-01-01', DATE '2025-01-20', DATE '2025-02-17',
                           DATE '2025-05-26', DATE '2025-06-19')) AS is_us_bank_holiday,
            (full_date = last_day(full_date)) AS is_month_end
        FROM days
    """)
    print(f"  gold.dim_time: {con.execute('SELECT COUNT(*) FROM gold.dim_time').fetchone()[0]:,} rows")


def build_dim_channel(con):
    con.execute("CREATE OR REPLACE TABLE gold.dim_channel "
                 "(channel_sk INTEGER, channel_code VARCHAR, channel_name VARCHAR, "
                 "channel_category VARCHAR, is_digital_flag BOOLEAN, is_outbound_flag BOOLEAN)")
    for i, (code, name, cat, digital, outbound) in enumerate(CHANNELS, start=1):
        con.execute("INSERT INTO gold.dim_channel VALUES (?,?,?,?,?,?)", [i, code, name, cat, digital, outbound])
    print(f"  gold.dim_channel: {len(CHANNELS)} rows")


def build_dim_risk_band(con):
    con.execute("CREATE OR REPLACE TABLE gold.dim_risk_band "
                 "(risk_band_sk INTEGER, risk_band_code VARCHAR, risk_band_name VARCHAR, "
                 "score_range_low INTEGER, score_range_high INTEGER)")
    for i, (code, name, lo, hi) in enumerate(RISK_BANDS, start=1):
        con.execute("INSERT INTO gold.dim_risk_band VALUES (?,?,?,?,?)", [i, code, name, lo, hi])
    print(f"  gold.dim_risk_band: {len(RISK_BANDS)} rows")


def build_dim_collector(con):
    # Same incremental SCD2 pattern as silver.customer (Phase 7 Section 2) --
    # collector_dim needs true history because contact_fact/promise_to_pay_fact
    # must attribute historical productivity to the team a collector was on
    # AT THE TIME (Phase 3 Section 2.4), not their team today.
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_collector (
            collector_sk BIGINT, collector_id VARCHAR, collector_name VARCHAR,
            team_name VARCHAR, collector_level VARCHAR, manager_name VARCHAR,
            effective_start_date TIMESTAMP, effective_end_date TIMESTAMP, is_current BOOLEAN
        );
        CREATE SEQUENCE IF NOT EXISTS gold_collector_sk_seq;
    """)
    batch_dates = [r[0] for r in con.execute(
        "SELECT DISTINCT _ingestion_date FROM bronze.raw_collectors_daily ORDER BY 1"
    ).fetchall()]
    for batch_date in batch_dates:
        con.execute("""
            UPDATE gold.dim_collector tgt SET
                is_current = FALSE, effective_end_date = src.source_updated_at
            FROM (SELECT * FROM bronze.raw_collectors_daily WHERE _ingestion_date = ?) src
            WHERE tgt.collector_id = src.collector_id AND tgt.is_current = TRUE
              AND tgt.team_name IS DISTINCT FROM src.team_name
        """, [batch_date])
        con.execute("""
            INSERT INTO gold.dim_collector
            SELECT nextval('gold_collector_sk_seq'), src.collector_id, src.collector_name,
                   src.team_name, src.collector_level, src.manager_name,
                   src.source_updated_at, TIMESTAMP '9999-12-31', TRUE
            FROM (SELECT * FROM bronze.raw_collectors_daily WHERE _ingestion_date = ?) src
            LEFT JOIN gold.dim_collector cur
                ON cur.collector_id = src.collector_id AND cur.is_current = TRUE
               AND cur.effective_start_date = src.source_updated_at
            WHERE cur.collector_id IS NULL
        """, [batch_date])
    n = con.execute("SELECT COUNT(*) FROM gold.dim_collector").fetchone()[0]
    print(f"  gold.dim_collector: {n:,} versions across {len(batch_dates)} batches")


def build_dim_customer_loan(con):
    con.execute("CREATE OR REPLACE TABLE gold.dim_customer AS SELECT * FROM silver.customer")
    con.execute("CREATE OR REPLACE TABLE gold.dim_loan AS SELECT * FROM silver.loan")
    print(f"  gold.dim_customer: {con.execute('SELECT COUNT(*) FROM gold.dim_customer').fetchone()[0]:,} rows "
          "(promoted directly from silver.customer -- already Gold-shaped)")
    print(f"  gold.dim_loan: {con.execute('SELECT COUNT(*) FROM gold.dim_loan').fetchone()[0]:,} rows "
          "(promoted directly from silver.loan)")


def build_fact_payment(con):
    con.execute("""
        CREATE OR REPLACE TABLE gold.payment_fact AS
        SELECT
            p.payment_id, l.loan_sk, c.customer_sk,
            CAST(strftime(p.payment_date, '%Y%m%d') AS INTEGER) AS payment_date_sk,
            ch.channel_sk,
            p.payment_amount, p.scheduled_amount, p.payment_type, p.payment_method,
            p.payment_status, p.is_reversal_flag, p.nsf_flag, p.original_payment_id
        FROM silver.payment p
        JOIN gold.dim_loan l
            ON l.loan_id = p.loan_id AND p.payment_date >= l.effective_start_date AND p.payment_date < l.effective_end_date
        JOIN gold.dim_customer c
            ON c.customer_id = p.customer_id AND p.payment_date >= c.effective_start_date AND p.payment_date < c.effective_end_date
        LEFT JOIN gold.dim_channel ch
            ON ch.channel_code = CASE p.payment_method
                WHEN 'ACH' THEN 'ACH' WHEN 'Debit Card' THEN 'DEBIT_CARD'
                WHEN 'Check' THEN 'CHECK' WHEN 'Wire' THEN 'WIRE' WHEN 'Cash' THEN 'CASH'
               END
    """)
    n = con.execute("SELECT COUNT(*) FROM gold.payment_fact").fetchone()[0]
    n_src = con.execute("SELECT COUNT(*) FROM silver.payment").fetchone()[0]
    print(f"  gold.payment_fact: {n:,} rows (from {n_src:,} silver.payment rows"
          f"{' -- MATCH' if n == n_src else f' -- ⚠ {n_src - n} rows dropped by SCD2 join, investigate'})")


def build_fact_delinquency(con):
    con.execute("""
        CREATE OR REPLACE TABLE gold.delinquency_fact AS
        WITH contacts_with_collector AS (
            SELECT loan_id, contact_date, collector_id
            FROM silver.contact WHERE collector_id IS NOT NULL
        ),
        base AS (
            SELECT
                d.loan_id, d.customer_id, d.snapshot_date, d.bucket_index, d.delinquency_bucket,
                d.dpd, d.prior_day_bucket, d.outstanding_balance, d.cure_flag, d.roll_flag,
                d.restructured_flag, d.fraud_flag,
                l.loan_sk, cu.customer_sk, l.risk_band_code
            FROM silver.delinquency d
            JOIN gold.dim_loan l
                ON l.loan_id = d.loan_id AND d.snapshot_date >= l.effective_start_date AND d.snapshot_date < l.effective_end_date
            JOIN gold.dim_customer cu
                ON cu.customer_id = d.customer_id AND d.snapshot_date >= cu.effective_start_date AND d.snapshot_date < cu.effective_end_date
        )
        SELECT
            b.loan_id, b.loan_sk, b.customer_sk,
            CAST(strftime(b.snapshot_date, '%Y%m%d') AS INTEGER) AS snapshot_date_sk,
            rb.risk_band_sk,
            -- last-touch collector as of this snapshot date (Phase 8 doc Section 3:
            -- our generator has no explicit "assignment" table, so this is the
            -- documented analytical proxy for "currently assigned collector")
            cwc.collector_id AS assigned_collector_id,
            b.bucket_index, b.delinquency_bucket, b.dpd, b.prior_day_bucket,
            b.outstanding_balance, b.cure_flag, b.roll_flag, b.restructured_flag, b.fraud_flag
        FROM base b
        JOIN gold.dim_risk_band rb ON rb.risk_band_code = b.risk_band_code
        ASOF LEFT JOIN contacts_with_collector cwc
            ON cwc.loan_id = b.loan_id AND b.snapshot_date >= cwc.contact_date
    """)
    n = con.execute("SELECT COUNT(*) FROM gold.delinquency_fact").fetchone()[0]
    n_src = con.execute("SELECT COUNT(*) FROM silver.delinquency").fetchone()[0]
    n_with_collector = con.execute(
        "SELECT COUNT(*) FROM gold.delinquency_fact WHERE assigned_collector_id IS NOT NULL"
    ).fetchone()[0]
    print(f"  gold.delinquency_fact: {n:,} rows (from {n_src:,} silver rows), "
          f"{n_with_collector:,} ({n_with_collector/n:.1%}) have an as-of collector attribution")


def build_fact_contact(con):
    con.execute("""
        CREATE OR REPLACE TABLE gold.contact_fact AS
        SELECT
            ct.contact_id, l.loan_sk, cu.customer_sk,
            CAST(strftime(ct.contact_date, '%Y%m%d') AS INTEGER) AS contact_date_sk,
            col.collector_sk, ch.channel_sk,
            ct.contact_direction, ct.contact_outcome, ct.is_rpc_flag,
            ct.call_duration_seconds, ct.complaint_flag
        FROM silver.contact ct
        JOIN gold.dim_loan l
            ON l.loan_id = ct.loan_id AND ct.contact_date >= l.effective_start_date AND ct.contact_date < l.effective_end_date
        JOIN gold.dim_customer cu
            ON cu.customer_id = ct.customer_id AND ct.contact_date >= cu.effective_start_date AND ct.contact_date < cu.effective_end_date
        LEFT JOIN gold.dim_collector col
            ON col.collector_id = ct.collector_id AND ct.contact_date >= col.effective_start_date AND ct.contact_date < col.effective_end_date
        LEFT JOIN gold.dim_channel ch ON ch.channel_code = ct.channel_code
    """)
    n = con.execute("SELECT COUNT(*) FROM gold.contact_fact").fetchone()[0]
    print(f"  gold.contact_fact: {n:,} rows")


def build_fact_ptp(con):
    con.execute("""
        CREATE OR REPLACE TABLE gold.promise_to_pay_fact AS
        SELECT
            p.ptp_id, l.loan_sk, cu.customer_sk, p.contact_id, col.collector_sk,
            CAST(strftime(p.ptp_created_date, '%Y%m%d') AS INTEGER) AS ptp_created_date_sk,
            CAST(strftime(p.ptp_promised_date, '%Y%m%d') AS INTEGER) AS ptp_promised_date_sk,
            p.ptp_amount, p.ptp_status, p.amount_paid_against_ptp,
            CASE WHEN p.fulfillment_date IS NOT NULL
                 THEN CAST(strftime(p.fulfillment_date, '%Y%m%d') AS INTEGER) END AS fulfillment_date_sk,
            CASE WHEN p.fulfillment_date IS NOT NULL
                 THEN date_diff('day', p.ptp_created_date, p.fulfillment_date) END AS days_to_fulfillment
        FROM silver.promise_to_pay p
        JOIN gold.dim_loan l
            ON l.loan_id = p.loan_id AND p.ptp_created_date >= l.effective_start_date AND p.ptp_created_date < l.effective_end_date
        JOIN gold.dim_customer cu
            ON cu.customer_id = p.customer_id AND p.ptp_created_date >= cu.effective_start_date AND p.ptp_created_date < cu.effective_end_date
        LEFT JOIN gold.dim_collector col
            ON col.collector_id = p.collector_id AND p.ptp_created_date >= col.effective_start_date AND p.ptp_created_date < col.effective_end_date
    """)
    n = con.execute("SELECT COUNT(*) FROM gold.promise_to_pay_fact").fetchone()[0]
    print(f"  gold.promise_to_pay_fact: {n:,} rows")


def compute_kpis(con):
    print("\n=== KPI Layer -- computed for real against gold.* ===\n")

    def scalar(sql):
        return con.execute(sql).fetchone()[0]

    # PAR 30/60/90 as of the LAST snapshot date in the window
    last_date = scalar("SELECT MAX(t.full_date) FROM gold.delinquency_fact d "
                        "JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk")
    par = con.execute("""
        SELECT
            SUM(CASE WHEN bucket_index >= 1 THEN outstanding_balance ELSE 0 END) / SUM(outstanding_balance) AS par30,
            SUM(CASE WHEN bucket_index >= 2 THEN outstanding_balance ELSE 0 END) / SUM(outstanding_balance) AS par60,
            SUM(CASE WHEN bucket_index >= 4 THEN outstanding_balance ELSE 0 END) / SUM(outstanding_balance) AS par90
        FROM gold.delinquency_fact d JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk
        WHERE t.full_date = ?
    """, [last_date]).fetchone()
    print(f"PAR 30 (as of {last_date}): {par[0]:.2%}")
    print(f"PAR 60 (as of {last_date}): {par[1]:.2%}")
    print(f"PAR 90 (as of {last_date}): {par[2]:.2%}")

    roll_rate = scalar("""
        SELECT SUM(CASE WHEN roll_flag THEN 1 ELSE 0 END)::DOUBLE
             / NULLIF(SUM(CASE WHEN bucket_index >= 1 THEN 1 ELSE 0 END), 0)
        FROM gold.delinquency_fact WHERE prior_day_bucket IS NOT NULL
    """)
    print(f"Roll Rate (daily, delinquent population): {roll_rate:.3%}")

    cure_rate = scalar("""
        SELECT SUM(CASE WHEN cure_flag THEN 1 ELSE 0 END)::DOUBLE
             / NULLIF(SUM(CASE WHEN prior_day_bucket != 'Current' THEN 1 ELSE 0 END), 0)
        FROM gold.delinquency_fact WHERE prior_day_bucket IS NOT NULL
    """)
    print(f"Cure Rate (daily, delinquent population): {cure_rate:.3%}")

    recovery_rate = scalar("""
        SELECT SUM(CASE WHEN pf.payment_type = 'Settlement' THEN pf.payment_amount ELSE 0 END)::DOUBLE
             / NULLIF(SUM(l.origination_amount), 0)
        FROM gold.dim_loan l LEFT JOIN gold.payment_fact pf ON pf.loan_sk = l.loan_sk
        WHERE l.charge_off_flag AND l.is_current
    """)
    print(f"Recovery Rate (settlement $ / charged-off original balance): {recovery_rate:.2%}")

    connect_rate = scalar("""
        SELECT SUM(CASE WHEN is_rpc_flag THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)
        FROM gold.contact_fact cf JOIN gold.dim_channel ch ON ch.channel_sk = cf.channel_sk
        WHERE ch.channel_category = 'Live Agent'
    """)
    print(f"Call Connect Rate (live-agent RPC rate): {connect_rate:.2%}")

    ptp_fulfill = scalar("""
        SELECT SUM(CASE WHEN ptp_status = 'Kept' THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)
        FROM gold.promise_to_pay_fact
    """)
    print(f"Promise-to-Pay Fulfillment Rate: {ptp_fulfill:.2%}")

    print("\nCollector Productivity (top 5 by PTP-kept dollars):")
    prod = con.execute("""
        SELECT col.collector_name, col.team_name,
               COUNT(DISTINCT cf.contact_id) AS contacts,
               COUNT(DISTINCT ptp.ptp_id) AS ptps_obtained,
               SUM(CASE WHEN ptp.ptp_status = 'Kept' THEN ptp.amount_paid_against_ptp ELSE 0 END) AS kept_dollars
        FROM gold.dim_collector col
        LEFT JOIN gold.contact_fact cf ON cf.collector_sk = col.collector_sk
        LEFT JOIN gold.promise_to_pay_fact ptp ON ptp.collector_sk = col.collector_sk
        WHERE col.is_current
        GROUP BY 1, 2 ORDER BY kept_dollars DESC LIMIT 5
    """).fetchall()
    for row in prod:
        print(f"    {row[0]:<22} {row[1]:<20} contacts={row[2]:<5} ptps={row[3]:<4} kept_$={row[4]:,.0f}")

    avg_days_delinq = scalar("""
        SELECT AVG(dpd) FROM gold.delinquency_fact WHERE bucket_index BETWEEN 1 AND 4
    """)
    print(f"\nAverage Days Delinquent (across all delinquent loan-days): {avg_days_delinq:.1f} days")

    collection_efficiency = scalar("""
        SELECT SUM(CASE WHEN d.prior_day_bucket != 'Current' AND d.bucket_index = 0
                        THEN d.outstanding_balance ELSE 0 END)::DOUBLE
             / NULLIF(SUM(CASE WHEN d.prior_day_bucket != 'Current' THEN d.outstanding_balance ELSE 0 END), 0)
        FROM gold.delinquency_fact d WHERE d.prior_day_bucket IS NOT NULL
    """)
    print(f"Collection Efficiency (past-due $ cured / past-due $ at risk): {collection_efficiency:.2%}")

    contact_success = scalar("""
        SELECT SUM(CASE WHEN resulted = 1 THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)
        FROM (
            SELECT cf.contact_id,
                   CASE WHEN EXISTS (SELECT 1 FROM gold.promise_to_pay_fact p WHERE p.contact_id = cf.contact_id) THEN 1 ELSE 0 END AS resulted
            FROM gold.contact_fact cf
            JOIN gold.dim_channel ch ON ch.channel_sk = cf.channel_sk
            WHERE ch.channel_category = 'Live Agent'
        )
    """)
    print(f"Contact Success Rate (live-agent contacts resulting in a PTP): {contact_success:.2%}")


def main():
    con = duckdb.connect(DB_PATH)
    con.execute("CREATE SCHEMA IF NOT EXISTS gold;")

    print("=== Building Gold dimensions ===")
    build_dim_time(con)
    build_dim_channel(con)
    build_dim_risk_band(con)
    build_dim_collector(con)
    build_dim_customer_loan(con)

    print("\n=== Building Gold facts ===")
    build_fact_payment(con)
    build_fact_delinquency(con)
    build_fact_contact(con)
    build_fact_ptp(con)

    compute_kpis(con)

    print(f"\nDone. Gold schema added to {DB_PATH}.")
    con.close()


if __name__ == "__main__":
    main()
