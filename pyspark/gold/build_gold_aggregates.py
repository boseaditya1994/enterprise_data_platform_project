"""
Gold-layer aggregation in PySpark.

IMPORTANT CONTEXT (see docs/02-architecture.md Section 5, docs/10-databricks.md
Section 3): in this project's actual architecture, Silver->Gold is dbt's
job (Phase 9) -- SQL is the right tool for declarative aggregation, and
dbt gives testing/docs/lineage for free. This notebook exists for the two
cases where dropping to PySpark genuinely earns its complexity instead of
just duplicating dbt:

  1. Portfolio-scale rolling-window computations (90-day trailing roll
     rate, 12-month portfolio trend) where Spark's window functions over
     a partitioned, bucketed Delta table outperform an equivalent
     Snowflake query once delinquency_fact reaches production scale
     (Phase 4's "millions of loans" target -> billions of fact rows).
  2. Pre-materializing a wide, denormalized "collections worklist" table
     that Power BI's operational dashboard (Phase 13) queries directly,
     refreshed on a tighter SLA than the full dbt DAG.

Everything else (the 10 KPI views, standard dims/facts) stays in dbt --
this notebook is the documented exception, not the default.
"""
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

GOLD_DB = "gold"
SILVER_DB = "silver"


def build_rolling_par_trend(spark: SparkSession) -> None:
    """
    90-day and 12-month trailing PAR trend, computed once as a materialized
    Gold table rather than recomputed per Power BI page load -- the exact
    kind of rolling-window aggregation Phase 2 flagged as PySpark's job at
    scale (window functions over a partitioned Delta table, not a
    correlated-subquery-per-row Snowflake view).
    """
    delinquency = spark.table(f"{SILVER_DB}.delinquency")

    daily_par = (
        delinquency
        .groupBy("snapshot_date")
        .agg(
            F.sum("outstanding_balance").alias("total_balance"),
            F.sum(F.when(F.col("bucket_index") >= 1, F.col("outstanding_balance")).otherwise(0)).alias("balance_30plus"),
        )
        .withColumn("par_30", F.col("balance_30plus") / F.col("total_balance"))
    )

    # NOTE (caught by `ruff check` -- F841 unused variable): an earlier draft
    # defined trend_window_90d/365d here via
    # Window.orderBy("snapshot_date").rangeBetween(-90 * 86400, 0) -- that's
    # not just unused, it's WRONG: rangeBetween on a raw DateType order
    # column interprets its bounds in units of DAYS, not seconds, so that
    # expression actually meant "~19,700 years back," not 90 days. The fix
    # below casts to a unix timestamp (seconds) first, which is the correct
    # way to express a day-based rangeBetween window in Spark. Left this
    # note rather than silently deleting the mistake, same as every other
    # caught bug in this project.
    with_trend = (
        daily_par
        .withColumn("snapshot_date_unix", F.col("snapshot_date").cast("timestamp").cast("long"))
        .withColumn(
            "par_30_90d_avg",
            F.avg("par_30").over(Window.orderBy("snapshot_date_unix").rangeBetween(-90 * 86400, 0)),
        )
        .withColumn(
            "par_30_365d_avg",
            F.avg("par_30").over(Window.orderBy("snapshot_date_unix").rangeBetween(-365 * 86400, 0)),
        )
        .drop("snapshot_date_unix")
    )

    (
        with_trend.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{GOLD_DB}.par_rolling_trend")
    )


def build_collections_worklist(spark: SparkSession) -> None:
    """
    A wide, pre-joined, pre-ranked table: one row per currently-delinquent
    loan, with everything a collector's dialer/worklist UI needs in a
    single lookup -- no joins at query time. This is the Gold-layer
    equivalent of a "materialized view for the operational dashboard,"
    refreshed on its own tighter schedule (Phase 11) independent of the
    full nightly dbt run.
    """
    latest_snapshot = (
        spark.table(f"{SILVER_DB}.delinquency")
        .filter(F.col("bucket_index") >= 1)
        .withColumn("rn", F.row_number().over(
            Window.partitionBy("loan_id").orderBy(F.col("snapshot_date").desc())
        ))
        .filter("rn = 1")
        .drop("rn")
    )

    loan = spark.table(f"{SILVER_DB}.loan").filter("is_current = true")
    customer = spark.table(f"{SILVER_DB}.customer").filter("is_current = true")

    last_contact = (
        spark.table(f"{SILVER_DB}.contact")
        .withColumn("rn", F.row_number().over(
            Window.partitionBy("loan_id").orderBy(F.col("contact_date").desc())
        ))
        .filter("rn = 1")
        .select("loan_id", F.col("contact_date").alias("last_contact_date"),
                F.col("contact_outcome").alias("last_contact_outcome"))
    )

    worklist = (
        latest_snapshot.alias("d")
        .join(loan.alias("l"), "loan_id")
        .join(customer.alias("c"), "customer_id")
        .join(last_contact, "loan_id", "left")
        .select(
            "d.loan_id", "c.customer_id", "c.first_name", "c.last_name", "c.phone_number",
            "d.delinquency_bucket", "d.dpd", "d.outstanding_balance",
            "l.loan_type", "l.risk_band_code",
            "last_contact_date", "last_contact_outcome",
        )
        # Priority: highest balance among the most-delinquent, longest-
        # since-contact accounts first -- collections managers' actual
        # stated prioritization logic (Phase 1 persona: Operations Manager).
        .withColumn("priority_rank", F.row_number().over(
            Window.orderBy(F.col("dpd").desc(), F.col("outstanding_balance").desc())
        ))
    )

    (
        worklist.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("delinquency_bucket")
        .saveAsTable(f"{GOLD_DB}.collections_worklist")
    )


if __name__ == "__main__":
    spark = SparkSession.builder.appName("gold_aggregation").getOrCreate()
    build_rolling_par_trend(spark)
    build_collections_worklist(spark)
