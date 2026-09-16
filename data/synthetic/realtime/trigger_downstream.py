"""
Loads today's landing files directly into Snowflake's own internal stage
(PUT), then COPY INTO the staging tables, then refreshes Silver/Gold via
dbt. No external cloud storage, no Databricks -- Snowflake + dbt only.
"""
import os
import sys
import glob
import subprocess

DAILY_TABLES = ["raw_payments", "raw_servicing_daily_status", "raw_call_center", "raw_collections_ptp"]


def get_snowflake_connection():
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    with open(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"], "rb") as key_file:
        p_key = serialization.load_pem_private_key(key_file.read(), password=None)
    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=pkb,
        role="ACCOUNTADMIN",
        warehouse="COMPUTE_WH",
        database="LOAN_DELINQUENCY_CC",
        schema="STAGING",
    )


def load_todays_files_into_snowflake(run_date: str, landing_dir: str):
    conn = get_snowflake_connection()
    cur = conn.cursor()
    try:
        for table in DAILY_TABLES:
            local_path = os.path.join(landing_dir, table, f"dt={run_date}", "part-000.csv")
            if not os.path.exists(local_path):
                print(f"  {table}: no file for {run_date} (expected on days with zero events)")
                continue

            stage_path = f"@STAGING.RT_LANDING_STAGE/{table}/dt={run_date}/"
            local_path_posix = local_path.replace(os.sep, "/")
            cur.execute(f"PUT file://{local_path_posix} {stage_path} OVERWRITE=TRUE AUTO_COMPRESS=FALSE")
            print(f"  {table}: uploaded to internal stage")

            table_upper = table.upper()
            sql = f"""
                COPY INTO STAGING.{table_upper}
                FROM {stage_path}
                FILE_FORMAT = (FORMAT_NAME = STAGING.FF_CSV)
                MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
                PATTERN = '.*part-000\\\\.csv'
            """
            cur.execute(sql)
            result = cur.fetchall()
            print(f"  Snowflake COPY INTO {table_upper}: {result}")
    finally:
        cur.close()
        conn.close()


def trigger_dbt_run():
    dbt_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "dbt")
    result = subprocess.run(
        ["dbt", "run", "--target", "snowflake"],
        cwd=dbt_dir,
        env={**os.environ, "DBT_PROFILES_DIR": dbt_dir},
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("dbt run failed")


if __name__ == "__main__":
    run_date = sys.argv[1] if len(sys.argv) > 1 else None
    landing_dir = sys.argv[2] if len(sys.argv) > 2 else None
    if not run_date or not landing_dir:
        raise ValueError("Usage: python3 trigger_downstream.py YYYY-MM-DD /path/to/landing")

    print(f"=== Triggering downstream chain for {run_date} ===")
    print("\n[1/2] Loading today's files into Snowflake...")
    load_todays_files_into_snowflake(run_date, landing_dir)

    print("\n[2/2] dbt run...")
    trigger_dbt_run()

    print("\n=== Downstream chain complete ===")