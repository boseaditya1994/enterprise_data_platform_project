"""
Generic, metadata-driven Bronze ingestion job for Databricks.

Reads pyspark/bronze/schema_registry.yaml to decide, per source table:
  * where to read from and what format
  * what schema is expected, and what to do about drift from it
  * what column(s) form the natural key / watermark for downstream Silver CDC
  * how to partition and how long to retain

Run for a single source per job/task (Databricks Workflows task-per-table,
Phase 11), so a schema-drift quarantine on one source never blocks the
other twelve from landing.

    databricks jobs run-now --job-id <bronze_ingest_job_id> \
        --notebook-params '{"table_name": "raw_payments"}'

This is written as REAL Databricks/PySpark code (not executed in this
portfolio's sandbox, which has no Spark cluster -- see Phase 2 Section
"Constraints"). pyspark/bronze/validate_registry_local.py is the
pandas-based stand-in that proves the *registry + drift-detection logic*
against the actual Phase 5 generated data without needing a cluster.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime

import yaml
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

REGISTRY_PATH = "/Workspace/loan-delinquency-command-center/pyspark/bronze/schema_registry.yaml"
BRONZE_DB = "bronze"
QUARANTINE_DB = "bronze_quarantine"
CONTROL_TABLE = "bronze.ingestion_control_log"

SPARK_TYPE_MAP = {
    "string": T.StringType(),
    "int": T.IntegerType(),
    "boolean": T.BooleanType(),
    "date": T.DateType(),
    "timestamp": T.TimestampType(),
}


def _spark_type(type_str: str):
    if type_str.startswith("decimal"):
        precision, scale = type_str[8:-1].split(",")
        return T.DecimalType(int(precision), int(scale))
    return SPARK_TYPE_MAP[type_str]


def load_registry(spark: SparkSession) -> dict:
    # dbutils.fs.head / open() both work against Workspace Files in Databricks Runtime 11.3+
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)["tables"]


def detect_schema_drift(actual_cols: set, table_cfg: dict) -> dict:
    """
    Compares the columns actually present in a landed file against the
    registry contract. Returns a classification, not a side effect --
    caller decides what to do (Phase 2 Section 4.3).
    """
    expected_cols = set(table_cfg["expected_columns"].keys())
    added = actual_cols - expected_cols
    missing = expected_cols - actual_cols

    # Known renames (e.g. raw_collections collector_id -> collector_ref_id)
    # are resolved via known_drift_events so a documented rename doesn't
    # get misclassified as "missing required column" every single day
    # after it happens.
    known_renames = {
        e["detail"].split(" renamed to ")[0].strip(): e["detail"].split(" renamed to ")[1].strip()
        for e in table_cfg.get("known_drift_events", [])
        if e["type"] == "breaking_rename"
    }
    resolved_missing = set()
    for old_col, new_col in known_renames.items():
        if old_col in missing and new_col in added:
            resolved_missing.add(old_col)
            added.discard(new_col)

    missing -= resolved_missing

    if missing:
        # A genuinely missing expected column (not a known rename) is a
        # BREAKING drift -- Bronze still lands the raw file (never lose
        # data) but the batch is flagged for quarantine review rather
        # than silently promoted.
        return {"classification": "breaking", "added": added, "missing": missing}
    if added and not table_cfg.get("allow_additive_drift", True):
        return {"classification": "breaking", "added": added, "missing": missing}
    if added:
        return {"classification": "additive", "added": added, "missing": missing}
    return {"classification": "none", "added": added, "missing": missing}


def ingest_table(spark: SparkSession, table_name: str, run_date: str) -> None:
    registry = load_registry(spark)
    if table_name not in registry:
        raise ValueError(f"{table_name} is not in the schema registry")
    cfg = registry[table_name]

    batch_id = str(uuid.uuid4())
    start_ts = datetime.utcnow()

    landing_path = cfg["landing_path_pattern"].format(date=run_date)
    reader = spark.read.option("header", True) if cfg["file_format"] == "csv" else spark.read
    try:
        raw_df: DataFrame = reader.format(cfg["file_format"]).load(landing_path)
    except Exception as e:
        _log_run(spark, table_name, batch_id, start_ts, status="NO_FILE_LANDED",
                  detail=f"{landing_path}: {e}", row_count=0, quarantined_count=0)
        if "freshness_sla_days" in cfg:
            # Missing bureau file, month-2 outage scenario (Phase 4 #2) --
            # absence is expected occasionally; Phase 14's freshness check
            # (not this job) is what pages someone if it persists beyond
            # freshness_sla_days.
            pass
        return

    actual_cols = set(raw_df.columns)
    drift = detect_schema_drift(actual_cols, cfg)

    raw_df = (
        raw_df
        .withColumn("_batch_id", F.lit(batch_id))
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_file", F.input_file_name())
        .withColumn("_ingestion_date", F.lit(run_date))
        .withColumn("_is_quarantined", F.lit(drift["classification"] == "breaking"))
        .withColumn("_schema_drift_classification", F.lit(drift["classification"]))
    )

    # Route source-flagged corrupt records (Phase 4 #13) to quarantine too,
    # independent of schema-level drift.
    if "is_corrupt_record" in raw_df.columns:
        raw_df = raw_df.withColumn(
            "_is_quarantined",
            F.col("_is_quarantined") | F.coalesce(F.col("is_corrupt_record"), F.lit(False)),
        )

    clean_df = raw_df.filter(~F.col("_is_quarantined"))
    quarantined_df = raw_df.filter(F.col("_is_quarantined"))

    write_opts = {"mergeSchema": "true"} if drift["classification"] == "additive" else {}
    partition_col = cfg.get("partition_col")

    writer = clean_df.write.format("delta").mode("append").options(**write_opts)
    if partition_col:
        writer = writer.partitionBy("_ingestion_date")
    writer.saveAsTable(f"{BRONZE_DB}.{table_name}")

    if quarantined_df.count() > 0:
        (quarantined_df.write.format("delta").mode("append")
         .saveAsTable(f"{QUARANTINE_DB}.{table_name}"))

    _log_run(
        spark, table_name, batch_id, start_ts,
        status="BREAKING_DRIFT_DETECTED" if drift["classification"] == "breaking" else "SUCCESS",
        detail=str(drift), row_count=clean_df.count(), quarantined_count=quarantined_df.count(),
    )


def _log_run(spark, table_name, batch_id, start_ts, status, detail, row_count, quarantined_count):
    row = [(table_name, batch_id, start_ts, datetime.utcnow(), status, detail, row_count, quarantined_count)]
    schema = T.StructType([
        T.StructField("table_name", T.StringType()),
        T.StructField("batch_id", T.StringType()),
        T.StructField("start_ts", T.TimestampType()),
        T.StructField("end_ts", T.TimestampType()),
        T.StructField("status", T.StringType()),
        T.StructField("detail", T.StringType()),
        T.StructField("row_count", T.LongType()),
        T.StructField("quarantined_count", T.LongType()),
    ])
    spark.createDataFrame(row, schema).write.format("delta").mode("append").saveAsTable(CONTROL_TABLE)
    if status == "BREAKING_DRIFT_DETECTED":
        # Phase 11/16: this is the hook Databricks Workflows / ADF alerting
        # attaches to -- page on-call, do not fail silently.
        print(f"[ALERT] {table_name} batch {batch_id}: {detail}")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("bronze_ingest").getOrCreate()
    table_arg = sys.argv[1] if len(sys.argv) > 1 else dbutils.widgets.get("table_name")  # noqa: F821
    date_arg = sys.argv[2] if len(sys.argv) > 2 else dbutils.widgets.get("run_date")  # noqa: F821
    ingest_table(spark, table_arg, date_arg)
