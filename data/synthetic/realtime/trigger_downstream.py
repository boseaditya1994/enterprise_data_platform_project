"""
Triggers the downstream chain for one day's already-uploaded landing files:
  1. Databricks: incremental Bronze append (via the Jobs API -- same
     Web-Activity-proven pattern from earlier today, just called from
     Python/GitHub Actions instead of ADF).
  2. Snowflake: COPY INTO scoped to just today's new partition folder (not
     a full historical reload) for the 4 daily-generating tables.
  3. dbt: a full `dbt run --target snowflake` -- at this data scale (a
     handful of new rows/day against a ~10K-loan portfolio), a full
     rebuild finishes in well under a minute, as proven earlier today, so
     true incremental dbt models weren't worth the added complexity for
     v1. Worth revisiting if the portfolio scale grows significantly.

Requires environment variables (set as GitHub Actions secrets):
  DATABRICKS_HOST, DATABRICKS_TOKEN, SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
  SNOWFLAKE_PASSWORD
"""
import os
import sys
import time
import subprocess
import requests

DAILY_TABLES = ["raw_payments", "raw_servicing_daily_status", "raw_call_center", "raw_collections_ptp"]


def trigger_databricks_ingest(run_date: str, notebook_path: str = "/Workspace/Users/boseaditya1994@gmail.com/incremental_daily_bronze_ingest"):
    """Submits the incremental notebook as a one-time job run, same runs/submit
    pattern proven via ADF's Web Activity earlier today, and polls until it finishes."""
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    submit_resp = requests.post(
        f"{host}/api/2.1/jobs/runs/submit",
        headers=headers,
        json={
            "run_name": f"daily_ingest_{run_date}",
            "tasks": [{
                "task_key": "incremental_ingest",
                "notebook_task": {
                    "notebook_path": notebook_path,
                    "base_parameters": {"run_date": run_date},
                    "source": "WORKSPACE",
                },
            }],
        },
    )
    submit_resp.raise_for_status()
    run_id = submit_resp.json()["run_id"]
    print(f"Databricks run submitted: run_id={run_id}")

    for _ in range(60):
        status_resp = requests.get(f"{host}/api/2.1/jobs/runs/get", headers=headers, params={"run_id": run_id})
        status_resp.raise_for_status()
        state = status_resp.json().get("state", {})
        life_cycle = state.get("life_cycle_state")
        if life_cycle in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            result_state = state.get("result_state")
            print(f"Databricks run finished: {life_cycle} / {result_state}")
            if result_state != "SUCCESS":
                raise RuntimeError(f"Databricks ingest failed: {state}")
            return
        time.sleep(5)
    raise TimeoutError("Databricks run did not finish within 5 minutes")


def trigger_snowflake_copy(run_date: str):
    """Runs COPY INTO scoped to just today's new partition. Uses key-pair auth
    (not password) so this can run unattended -- MFA has no way to approve
    an automated, unattended run."""
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    with open(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"], "rb") as key_file:
        p_key = serialization.load_pem_private_key(key_file.read(), password=None)

    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=pkb,
        role="ACCOUNTADMIN",
        warehouse="COMPUTE_WH",
        database="LOAN_DELINQUENCY_CC",
        schema="STAGING",
    )
    cur = conn.cursor()
    try:
        for table in DAILY_TABLES:
            table_upper = table.upper()
            sql = f"""
                COPY INTO STAGING.{table_upper}
                FROM @STAGING.STG_LANDING_ADLS/{table}/dt={run_date}/
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
    """Reuses the exact dbt CLI invocation proven earlier today."""
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
    if not run_date:
        raise ValueError("Usage: python3 trigger_downstream.py YYYY-MM-DD")

    print(f"=== Triggering downstream chain for {run_date} ===")
    print("\n[1/3] Databricks incremental ingest...")
    trigger_databricks_ingest(run_date)

    print("\n[2/3] Snowflake COPY INTO...")
    trigger_snowflake_copy(run_date)

    print("\n[3/3] dbt run...")
    trigger_dbt_run()

    print("\n=== Downstream chain complete ===")