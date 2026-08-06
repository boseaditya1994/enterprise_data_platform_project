"""
Databricks Structured Streaming job: Call Center + Collections Platform
contact/action events, Event Hubs -> Bronze -> Silver (Phase 2 Section 4.2).

This is REAL Databricks/PySpark code, not executed in this sandbox (no
Spark cluster available here -- Phase 1's stated constraint). It's written
to be deployment-correct: idempotent on restart, bounded state via
watermarking, and never drops a late event.

Run as a Databricks Workflows continuous job (one job per source stream,
per Phase 11's per-table task design so one stream's failure doesn't
block the other).
"""
from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.window import Window

EVENT_HUBS_CONNECTION_SECRET = "{{secrets/eventhubs/collections-connection-string}}"
CHECKPOINT_ROOT = "/mnt/checkpoints/streaming"
BRONZE_DB = "bronze"
SILVER_DB = "silver"

# Late-arrival tolerance (Phase 2 Section 4.2): agent mobile apps and the
# Collections Platform's own dialer can lag by minutes when offline; 30
# minutes covers observed sync delays with margin, without holding
# streaming state indefinitely.
WATERMARK_DELAY = "30 minutes"
TRIGGER_INTERVAL = "1 minute"

CONTACT_EVENT_SCHEMA = T.StructType([
    T.StructField("contact_id", T.StringType()),
    T.StructField("loan_id", T.StringType()),
    T.StructField("customer_id", T.StringType()),
    T.StructField("event_time", T.TimestampType()),      # when the contact ACTUALLY happened
    T.StructField("collector_id", T.StringType()),
    T.StructField("channel_code", T.StringType()),
    T.StructField("contact_direction", T.StringType()),
    T.StructField("contact_outcome", T.StringType()),
    T.StructField("is_rpc_flag", T.BooleanType()),
    T.StructField("call_duration_seconds", T.IntegerType()),
    T.StructField("complaint_flag", T.BooleanType()),
    T.StructField("source_system", T.StringType()),
])


def read_event_hubs_stream(spark: SparkSession, event_hub_name: str) -> DataFrame:
    eh_conf = {
        "eventhubs.connectionString": EVENT_HUBS_CONNECTION_SECRET,
        "eventhubs.consumerGroup": "bronze-ingestion",
        "eventhubs.startingPosition": '{"offset": "-1", "seqNo": -1, "enqueuedTime": null, "isInclusive": true}',
    }
    raw = (
        spark.readStream
        .format("eventhubs")
        .options(**eh_conf)
        .load()
    )
    parsed = (
        raw
        .select(F.from_json(F.col("body").cast("string"), CONTACT_EVENT_SCHEMA).alias("event"),
                F.col("enqueuedTime").alias("ingestion_time"))
        .select("event.*", "ingestion_time")
    )
    return parsed


def write_bronze_and_flag_late_arrivals(batch_df: DataFrame, batch_id: int, target_table: str) -> None:
    """
    foreachBatch sink: Bronze gets EVERY event, watermark-closed or not
    (Bronze never drops data, Phase 2 Section 4.2). Events arriving after
    their window's watermark has closed are flagged `late_arrival = true`
    for Silver's separate batch-reconciliation pass to pick up, rather
    than being silently absorbed into (and skewing) the streaming
    aggregation that already closed for that window.
    """
    enriched = (
        batch_df
        .withColumn("_batch_id", F.lit(batch_id))
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn(
            "late_arrival",
            F.col("event_time") < (F.col("ingestion_time") - F.expr(f"INTERVAL {WATERMARK_DELAY}")),
        )
    )
    (
        enriched.write
        .format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(f"{BRONZE_DB}.{target_table}")
    )


def merge_into_silver_contact(batch_df: DataFrame, batch_id: int) -> None:
    """
    foreachBatch sink #2: idempotent upsert into Silver on contact_id.
    Structured Streaming + Delta MERGE gives effectively-once semantics on
    restart -- the checkpoint tracks committed offsets, and MERGE on the
    natural key means replaying an already-processed micro-batch after a
    failure is a safe no-op, not a duplicate.
    """
    if batch_df.rdd.isEmpty():
        return

    deduped = (
        batch_df
        .withColumn(
            "rn",
            F.row_number().over(Window.partitionBy("contact_id").orderBy(F.col("event_time").desc())),
        )
        .filter("rn = 1")
        .drop("rn")
    )

    silver_table = DeltaTable.forName(batch_df.sparkSession, f"{SILVER_DB}.contact")
    (
        silver_table.alias("tgt")
        .merge(deduped.alias("src"), "tgt.contact_id = src.contact_id")
        .whenNotMatchedInsert(values={
            "contact_id": "src.contact_id", "loan_id": "src.loan_id", "customer_id": "src.customer_id",
            "contact_date": "src.event_time", "collector_id": "src.collector_id",
            "channel_code": "src.channel_code", "contact_direction": "src.contact_direction",
            "contact_outcome": "src.contact_outcome", "is_rpc_flag": "src.is_rpc_flag",
            "call_duration_seconds": "src.call_duration_seconds", "complaint_flag": "src.complaint_flag",
            "source_system": "src.source_system",
        })
        # No whenMatchedUpdate: contact events are immutable once landed
        # (Phase 6 registry cdc_strategy = append_only) -- a genuinely
        # corrected upstream record should be a DQ-flagged review case
        # (Phase 14), not a silent overwrite of contact history.
        .execute()
    )


def run_stream(spark: SparkSession, event_hub_name: str, bronze_table: str) -> None:
    parsed = read_event_hubs_stream(spark, event_hub_name)

    watermarked = parsed.withWatermark("event_time", WATERMARK_DELAY)

    bronze_query = (
        watermarked.writeStream
        .foreachBatch(lambda df, bid: write_bronze_and_flag_late_arrivals(df, bid, bronze_table))
        .option("checkpointLocation", f"{CHECKPOINT_ROOT}/{bronze_table}/bronze")
        .trigger(processingTime=TRIGGER_INTERVAL)
        .start()
    )

    silver_query = (
        watermarked.writeStream
        .foreachBatch(merge_into_silver_contact)
        .option("checkpointLocation", f"{CHECKPOINT_ROOT}/{bronze_table}/silver")
        .trigger(processingTime=TRIGGER_INTERVAL)
        .start()
    )

    bronze_query.awaitTermination()
    silver_query.awaitTermination()


if __name__ == "__main__":
    spark = SparkSession.builder.appName("stream_call_center_collections").getOrCreate()
    dbutils.widgets.text("event_hub_name", "collections-contact-events")  # noqa: F821
    dbutils.widgets.text("bronze_table", "raw_collections")  # noqa: F821
    run_stream(
        spark,
        event_hub_name=dbutils.widgets.get("event_hub_name"),  # noqa: F821
        bronze_table=dbutils.widgets.get("bronze_table"),  # noqa: F821
    )
