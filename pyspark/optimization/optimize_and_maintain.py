"""
Delta Lake maintenance job -- run nightly per table, after that table's
main write job completes (Phase 11 orchestration: a downstream task, not
a separate uncoordinated schedule).

Why this matters at scale (Phase 4's "millions of loans" target):
Bronze/Silver/Gold tables are all append/merge-heavy, which left
unmanaged produces many small files (bad for read performance) and
unbounded history (storage cost, slow time-travel queries).
"""
from pyspark.sql import SparkSession

# Z-ORDER columns chosen per table based on the actual query patterns from
# this project's own KPI/dashboard SQL (Phase 8/13) -- not guessed. Every
# table's most common WHERE/JOIN column(s) go first.
ZORDER_COLUMNS = {
    "silver.delinquency": ["snapshot_date", "loan_id"],       # every KPI query filters by date first
    "silver.payment": ["payment_date", "loan_id"],
    "silver.contact": ["contact_date", "collector_id"],
    "gold.delinquency_fact": ["snapshot_date_sk", "loan_sk"],
    "gold.payment_fact": ["payment_date_sk", "loan_sk"],
    "gold.contact_fact": ["contact_date_sk", "collector_sk"],
    "gold.collections_worklist": ["priority_rank"],
}

# VACUUM retention: 7 days is Delta's default and the practical floor for
# safe time-travel + concurrent-reader safety. Bronze tables get a LONGER
# retain window (30 days) since Bronze's whole purpose is being the raw
# fallback if a downstream bug requires reprocessing (Phase 2 Principle 1) --
# vacuuming it aggressively would defeat that purpose.
VACUUM_RETENTION_HOURS = {
    "default": 24 * 7,
    "bronze": 24 * 30,
}


def optimize_table(spark: SparkSession, table_name: str) -> None:
    zorder_cols = ZORDER_COLUMNS.get(table_name)
    if zorder_cols:
        cols = ", ".join(zorder_cols)
        spark.sql(f"OPTIMIZE {table_name} ZORDER BY ({cols})")
    else:
        spark.sql(f"OPTIMIZE {table_name}")


def vacuum_table(spark: SparkSession, table_name: str) -> None:
    is_bronze = table_name.startswith("bronze.")
    retention = VACUUM_RETENTION_HOURS["bronze" if is_bronze else "default"]
    spark.sql(f"VACUUM {table_name} RETAIN {retention} HOURS")


def analyze_table_stats(spark: SparkSession, table_name: str) -> None:
    """Refreshes column statistics used by the Spark/Photon query optimizer
    for join-order and filter-pushdown decisions."""
    spark.sql(f"ANALYZE TABLE {table_name} COMPUTE STATISTICS FOR ALL COLUMNS")


def run_maintenance(spark: SparkSession, tables: list[str]) -> None:
    for table in tables:
        print(f"Optimizing {table}...")
        optimize_table(spark, table)
        analyze_table_stats(spark, table)
        vacuum_table(spark, table)


if __name__ == "__main__":
    spark = SparkSession.builder.appName("delta_maintenance").getOrCreate()
    run_maintenance(spark, tables=list(ZORDER_COLUMNS.keys()))
