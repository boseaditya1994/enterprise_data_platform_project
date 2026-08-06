"""
"Is the platform healthy right now" -- the FIRST command in the Runbook
(docs/16-documentation.md Section 4) for any on-call engineer responding
to an alert. Queries the same DuckDB warehouse every phase has built
against; production equivalent would point at Snowflake's
dq.check_results, AUDIT.pipeline_run_log, and INFORMATION_SCHEMA instead
(swap DB_PATH/connection for a Snowflake connector -- the QUERIES below
are written to be nearly copy-paste portable to Snowflake SQL already).

Usage:
    cd ops
    python3 health_check.py
"""
import os

import duckdb

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "..", "sql", "silver", "local_execution", "warehouse.duckdb")


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    con = duckdb.connect(DB_PATH, read_only=True)

    section("1. Layer row counts (sanity check -- does data exist where expected)")
    for schema, table in [
        ("bronze", "raw_payments"), ("bronze", "raw_servicing_daily_status"),
        ("silver", "customer"), ("silver", "loan"), ("silver", "payment"), ("silver", "delinquency"),
        ("gold", "dim_customer"), ("gold", "dim_loan"), ("gold", "delinquency_fact"), ("gold", "payment_fact"),
    ]:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0]
            print(f"  {schema}.{table:<28} {n:>12,} rows")
        except Exception as e:
            print(f"  {schema}.{table:<28} ⚠ ERROR: {e}")

    section("2. Most recent DQ check run (Phase 14)")
    try:
        latest = con.execute("SELECT run_id, MAX(checked_at) FROM dq.check_results GROUP BY run_id ORDER BY 2 DESC LIMIT 1").fetchone()
        if latest:
            run_id, checked_at = latest
            summary = con.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE passed) AS passed,
                    COUNT(*) FILTER (WHERE NOT passed AND severity = 'FAIL') AS fail_failures,
                    COUNT(*) FILTER (WHERE NOT passed AND severity = 'WARN') AS warn_failures
                FROM dq.check_results WHERE run_id = ?
            """, [run_id]).fetchone()
            print(f"  Run {run_id} at {checked_at}")
            print(f"  Passed: {summary[0]}  |  FAIL-severity failures: {summary[1]}  |  WARN-severity failures: {summary[2]}")
            if summary[1] > 0:
                print("  🔴 ACTION: FAIL-severity failures present -- see Runbook Section 4.2 (DQ FAIL response)")
                bad = con.execute("""
                    SELECT table_name, check_name, detail FROM dq.check_results
                    WHERE run_id = ? AND NOT passed AND severity = 'FAIL'
                """, [run_id]).fetchall()
                for b in bad:
                    print(f"      - {b[0]}.{b[1]}: {b[2]}")
        else:
            print("  No DQ check runs found -- run dq/run_dq_checks_duckdb.py first.")
    except Exception as e:
        print(f"  ⚠ Could not read dq.check_results: {e}")

    section("3. SCD2 sanity checks (every current-flagged natural key should be unique)")
    for table, key in [("silver.customer", "customer_id"), ("silver.loan", "loan_id"), ("gold.dim_collector", "collector_id")]:
        try:
            dupes = con.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT {key} FROM {table} WHERE is_current GROUP BY {key} HAVING COUNT(*) > 1
                )
            """).fetchone()[0]
            status = "✅" if dupes == 0 else "🔴"
            print(f"  {status} {table}: {dupes} duplicate current-version key(s)")
        except Exception as e:
            print(f"  ⚠ {table}: {e}")

    section("4. Referential integrity spot-check (Gold facts -> dims)")
    try:
        orphans = con.execute("""
            SELECT COUNT(*) FROM gold.delinquency_fact d
            LEFT JOIN gold.dim_loan l ON d.loan_sk = l.loan_sk
            WHERE l.loan_sk IS NULL
        """).fetchone()[0]
        status = "✅" if orphans == 0 else "🔴"
        print(f"  {status} gold.delinquency_fact -> gold.dim_loan: {orphans} orphaned loan_sk")
    except Exception as e:
        print(f"  ⚠ {e}")

    section("Summary")
    print("  If everything above is ✅/green, the platform is in a known-good state.")
    print("  If anything is 🔴, follow the corresponding Runbook section in docs/16-documentation.md before escalating.")

    con.close()


if __name__ == "__main__":
    main()
