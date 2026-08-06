"""
Reusable SCD2 merge using Delta Lake's DeltaTable.merge() Python API,
rather than the raw SQL MERGE INTO strings used in sql/silver/*.sql.

Both are legitimate, both ship in this repo deliberately: the SQL version
(Phase 7) is easier for an analyst to read and reason about; this
DataFrame-API version is what a data engineer would actually write inside
a parameterized Databricks job where the merge condition, table name, and
change-detection columns vary per entity -- string-templating raw SQL for
that gets fragile fast, while the DataFrame API composes cleanly.

Usage (customer):
    scd2_merge(
        spark, target_table="silver.customer", source_df=todays_crm_batch,
        natural_key="customer_id", compare_cols=["mailing_city", "mailing_state",
        "mailing_zip", "customer_segment", "employment_status"],
        watermark_col="source_updated_at",
    )
"""
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from delta.tables import DeltaTable


def scd2_merge(
    spark: SparkSession,
    target_table: str,
    source_df: DataFrame,
    natural_key: str,
    compare_cols: list[str],
    watermark_col: str,
) -> None:
    """
    Generic two-pass SCD2 merge (Phase 7 Section 2 pattern), parameterized
    so the same function serves silver.customer, silver.loan (via a
    pre-joined "current attributes as of this change" source), and any
    future SCD2 entity without duplicating merge logic per table.
    """
    target = DeltaTable.forName(spark, target_table)

    change_condition = " OR ".join(
        f"tgt.{c} IS DISTINCT FROM src.{c}" for c in compare_cols
    )

    # Pass 1: close out changed current versions.
    (
        target.alias("tgt")
        .merge(
            source_df.alias("src"),
            f"tgt.{natural_key} = src.{natural_key} AND tgt.is_current = true",
        )
        .whenMatchedUpdate(
            condition=change_condition,
            set={
                "is_current": "false",
                "effective_end_date": f"src.{watermark_col}",
                "_silver_updated_ts": "current_timestamp()",
            },
        )
        .execute()
    )

    # Pass 2: open a new current version for brand-new keys or rows Pass 1
    # just closed (identified by: no current row starts exactly at this
    # batch's watermark value for this key -- see sql/silver/01_customer_scd2_merge.sql
    # for the identical logic expressed as two plain SQL statements).
    target_current = target.toDF().filter("is_current = true")
    already_open_this_batch = (
        target_current
        .join(
            source_df,
            (target_current[natural_key] == source_df[natural_key])
            & (target_current["effective_start_date"] == source_df[watermark_col]),
            "inner",
        )
        .select(source_df[natural_key])
    )

    to_insert = source_df.join(already_open_this_batch, on=natural_key, how="left_anti")

    new_versions = (
        to_insert
        .withColumn("effective_start_date", F.col(watermark_col))
        .withColumn("effective_end_date", F.lit("9999-12-31").cast("timestamp"))
        .withColumn("is_current", F.lit(True))
        .withColumn("_silver_load_ts", F.current_timestamp())
    )

    new_versions.write.format("delta").mode("append").saveAsTable(target_table)


def scd2_merge_customer(spark: SparkSession, todays_crm_batch: DataFrame) -> None:
    scd2_merge(
        spark,
        target_table="silver.customer",
        source_df=todays_crm_batch,
        natural_key="customer_id",
        compare_cols=["mailing_city", "mailing_state", "mailing_zip", "customer_segment", "employment_status"],
        watermark_col="source_updated_at",
    )


def scd2_merge_collector(spark: SparkSession, todays_collector_batch: DataFrame) -> None:
    scd2_merge(
        spark,
        target_table="silver.collector",
        source_df=todays_collector_batch,
        natural_key="collector_id",
        compare_cols=["team_name", "collector_level", "manager_name"],
        watermark_col="source_updated_at",
    )


# NOTE: silver.loan is NOT a good fit for this generic function -- its
# "changes" come from a separate lifecycle-events stream, not repeated
# attribute rows on the same natural key (Phase 7 Section 2's monotonic-
# flags argument). It stays as the windowed full-history rebuild pattern
# (sql/silver/02_loan_scd2_merge.sql) even in the PySpark/Databricks
# execution path -- expressed there via Spark SQL for exactly the same
# reason a set-based window query is the right tool, regardless of engine.
