"""
Writes one day's simulation events to the exact dt=YYYY-MM-DD/part-000.csv
partition convention used everywhere else in this project (landing zone,
Databricks Bronze, Snowflake staging) -- these files can drop straight into
that existing pipeline with zero changes on the consuming side.
"""
import os


TABLE_NAME_MAP = {
    "delinquency_snapshot": "raw_servicing_daily_status",
    "payments": "raw_payments",
    "contacts": "raw_call_center",
    "ptp": "raw_collections_ptp",
}


def write_daily_events(events: dict, target_date, output_root: str) -> list:
    """Returns the list of file paths actually written (empty-event tables are skipped,
    matching real production behavior -- no file lands if nothing happened that day)."""
    written = []
    date_str = target_date.date().isoformat() if hasattr(target_date, "date") else str(target_date)

    for event_key, table_name in TABLE_NAME_MAP.items():
        df = events.get(event_key)
        if df is None or len(df) == 0:
            continue

        partition_dir = os.path.join(output_root, table_name, f"dt={date_str}")
        os.makedirs(partition_dir, exist_ok=True)
        out_path = os.path.join(partition_dir, "part-000.csv")
        df.to_csv(out_path, index=False)
        written.append(out_path)

    return written