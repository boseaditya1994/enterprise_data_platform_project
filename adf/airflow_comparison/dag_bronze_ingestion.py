"""
Airflow equivalent of pl_master_bronze_ingestion + pl_silver_gold_orchestration,
built specifically as a like-for-like comparison artifact (promised in
docs/02-architecture.md's tech-stack table: "Airflow included specifically
because it's the most commonly asked-about orchestrator in DE interviews
even when ADF is used in production").

This is NOT a competing production path -- ADF is what's actually
deployed (Phase 11 Section 1's reasoning: native CDC connectors, Azure
governance integration). This DAG exists so the tradeoff discussion in
docs/11-adf-pipelines.md Section 5 has a real artifact behind it, not just
a table of adjectives.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.providers.databricks.operators.databricks import DatabricksSubmitRunOperator
from airflow.providers.microsoft.teams.operators.teams_webhook import MSTeamsWebhookOperator
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.utils.task_group import TaskGroup
from airflow.models.baseoperator import chain

# The Airflow-native equivalent of pipeline_control (adf/control_table_ddl.sql)
# -- same metadata-driven principle, but expressed as Python since Airflow
# DAGs ARE Python, which is exactly the biggest practical difference from
# ADF's JSON+expression-language config (Section 5 of the doc).
PIPELINE_CONTROL = [
    {"source_name": "raw_crm", "depends_on_source": None, "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_collectors_daily", "depends_on_source": None, "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_servicing_applications", "depends_on_source": None, "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_servicing_loans", "depends_on_source": None, "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_servicing_daily_status", "depends_on_source": "raw_servicing_loans", "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_servicing_loan_events", "depends_on_source": "raw_servicing_loans", "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_servicing_loan_applicant_bridge", "depends_on_source": None, "max_retries": 3, "retry_delay_s": 30},
    {"source_name": "raw_payments", "depends_on_source": None, "max_retries": 5, "retry_delay_s": 60},
    {"source_name": "raw_bureau", "depends_on_source": None, "max_retries": 2, "retry_delay_s": 120},
    {"source_name": "raw_risk_scores", "depends_on_source": None, "max_retries": 3, "retry_delay_s": 30},
]

default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email_on_failure": False,  # Teams webhook handles alerting instead (see on_failure_callback)
    "retries": 0,  # per-task retries set individually below from PIPELINE_CONTROL, not a DAG-wide default
}


def alert_on_failure(context):
    MSTeamsWebhookOperator(
        task_id="teams_alert",
        http_conn_id="teams_webhook",
        message=(
            f"🔴 Bronze ingestion FAILED: {context['task_instance'].task_id} "
            f"(run={context['ds']}, dag_run={context['run_id']})"
        ),
    ).execute(context=context)


with DAG(
    dag_id="loan_delinquency_bronze_to_gold",
    description="Airflow comparison DAG -- see docs/11-adf-pipelines.md Section 5",
    schedule_interval="0 6 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    on_failure_callback=alert_on_failure,
    tags=["bronze", "silver", "gold", "comparison-artifact"],
) as dag:

    with TaskGroup("bronze_ingestion") as bronze_group:
        task_by_source = {}
        for source in PIPELINE_CONTROL:
            task_by_source[source["source_name"]] = DatabricksSubmitRunOperator(
                task_id=f"ingest_{source['source_name']}",
                databricks_conn_id="databricks_default",
                json={
                    "new_cluster": {
                        "spark_version": "14.3.x-scala2.12",
                        "node_type_id": "Standard_DS4_v2",
                        "autoscale": {"min_workers": 2, "max_workers": 8},
                    },
                    "notebook_task": {
                        "notebook_path": "/Repos/prod/pyspark/bronze/ingest_bronze.py",
                        "base_parameters": {
                            "table_name": source["source_name"],
                            "run_date": "{{ ds }}",
                        },
                    },
                },
                retries=source["max_retries"],
                retry_delay=timedelta(seconds=source["retry_delay_s"]),
            )

        # Dependency wiring directly from PIPELINE_CONTROL -- this loop is
        # the Airflow-native equivalent of ADF's two-wave ForEach
        # (pl_master_bronze_ingestion's "no dependency" then "dependent"
        # sections), expressed as plain Python control flow instead of a
        # declarative two-pass pipeline structure.
        for source in PIPELINE_CONTROL:
            if source["depends_on_source"]:
                task_by_source[source["depends_on_source"]] >> task_by_source[source["source_name"]]

    silver_customer = DatabricksSubmitRunOperator(
        task_id="silver_customer_scd2_merge",
        databricks_conn_id="databricks_default",
        json={
            "new_cluster": {"spark_version": "14.3.x-scala2.12", "node_type_id": "Standard_DS4_v2",
                             "autoscale": {"min_workers": 1, "max_workers": 4}},
            "notebook_task": {"notebook_path": "/Repos/prod/pyspark/silver/scd2_merge_deltalake.py",
                               "base_parameters": {"entity": "customer", "run_date": "{{ ds }}"}},
        },
        retries=1,
    )

    silver_collector = DatabricksSubmitRunOperator(
        task_id="silver_collector_scd2_merge",
        databricks_conn_id="databricks_default",
        json={
            "new_cluster": {"spark_version": "14.3.x-scala2.12", "node_type_id": "Standard_DS4_v2",
                             "autoscale": {"min_workers": 1, "max_workers": 4}},
            "notebook_task": {"notebook_path": "/Repos/prod/pyspark/silver/scd2_merge_deltalake.py",
                               "base_parameters": {"entity": "collector", "run_date": "{{ ds }}"}},
        },
        retries=1,
    )

    silver_loan = DatabricksSubmitRunOperator(
        task_id="silver_loan_windowed_rebuild",
        databricks_conn_id="databricks_default",
        json={
            "new_cluster": {"spark_version": "14.3.x-scala2.12", "node_type_id": "Standard_DS4_v2",
                             "autoscale": {"min_workers": 1, "max_workers": 4}},
            "notebook_task": {"notebook_path": "/Repos/prod/sql/silver/02_loan_scd2_merge.sql",
                               "base_parameters": {"run_date": "{{ ds }}"}},
        },
        retries=1,
    )

    trigger_dbt = PythonOperator(
        task_id="trigger_dbt_cloud_run",
        python_callable=lambda **ctx: __import__("requests").post(
            "https://cloud.getdbt.com/api/v2/accounts/{account_id}/jobs/{job_id}/run/",
            headers={"Authorization": "Bearer {{ conn.dbt_cloud.password }}"},
            json={"cause": f"Airflow DAG run {ctx['run_id']}"},
        ),
        # NOTE: a real implementation would use Airflow's own
        # DbtCloudRunJobOperator (astronomer-cosmos / dbt Cloud provider),
        # which also handles the poll-until-complete step ADF needed a
        # manual Until loop for -- one of the concrete ergonomic
        # advantages Section 5 credits to Airflow's native provider ecosystem.
    )

    gold_pyspark = DatabricksSubmitRunOperator(
        task_id="gold_pyspark_exceptions",
        databricks_conn_id="databricks_default",
        json={
            "new_cluster": {"spark_version": "14.3.x-scala2.12", "node_type_id": "Standard_DS4_v2",
                             "autoscale": {"min_workers": 2, "max_workers": 6}},
            "notebook_task": {"notebook_path": "/Repos/prod/pyspark/gold/build_gold_aggregates.py",
                               "base_parameters": {"run_date": "{{ ds }}"}},
        },
        retries=1,
    )

    delta_maintenance = DatabricksSubmitRunOperator(
        task_id="delta_maintenance",
        databricks_conn_id="databricks_default",
        json={
            "new_cluster": {"spark_version": "14.3.x-scala2.12", "node_type_id": "Standard_DS4_v2",
                             "autoscale": {"min_workers": 1, "max_workers": 4}},
            "notebook_task": {"notebook_path": "/Repos/prod/pyspark/optimization/optimize_and_maintain.py"},
        },
        retries=1,
    )

    chain(
        bronze_group,
        [silver_customer, silver_collector, silver_loan],
        trigger_dbt,
        gold_pyspark,
        delta_maintenance,
    )
