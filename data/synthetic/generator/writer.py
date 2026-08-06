"""
Writes generated dataframes out as partitioned CSV "daily batch drops",
mirroring the Bronze landing pattern from Phase 2 (one file per source
per ingestion day). Also applies the two schema-drift scenarios
(#3 additive, #4 breaking rename) at write time, since schema drift is
fundamentally about *what shape the file lands in on a given day*.
"""
from __future__ import annotations

import os
import pandas as pd

from . import config as cfg


def _partition_path(root: str, table_name: str, dt) -> str:
    dt_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
    path = os.path.join(root, f"raw_{table_name}", f"dt={dt_str}")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "part-000.csv")


def write_partitioned(df: pd.DataFrame, date_col: str, table_name: str, root: str,
                       schema_drift_fn=None) -> int:
    """Writes df partitioned by date_col. Returns number of partitions written."""
    if df.empty:
        return 0
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    n_partitions = 0
    for dt, group in df.groupby(df[date_col].dt.date):
        group = group.copy()
        if schema_drift_fn is not None:
            group = schema_drift_fn(group, pd.Timestamp(dt))
        out_path = _partition_path(root, table_name, dt)
        group.to_csv(out_path, index=False)
        n_partitions += 1
    return n_partitions


def write_full_snapshot(df: pd.DataFrame, table_name: str, root: str) -> None:
    """For small reference/bridge tables that aren't naturally date-partitioned."""
    path = os.path.join(root, f"raw_{table_name}")
    os.makedirs(path, exist_ok=True)
    df.to_csv(os.path.join(path, "full_snapshot.csv"), index=False)


def servicing_schema_drift(group: pd.DataFrame, dt: pd.Timestamp) -> pd.DataFrame:
    """Scenario #3 (additive): loan_purpose_code column appears starting
    SCHEMA_DRIFT_ADD_COLUMN_DAY_OFFSET days into the window."""
    drift_date = pd.Timestamp(cfg.WINDOW_START) + pd.Timedelta(days=cfg.SCHEMA_DRIFT_ADD_COLUMN_DAY_OFFSET)
    if dt >= drift_date:
        group = group.copy()
        group["loan_purpose_code"] = "DEBT_CONSOLIDATION"
    return group


def collections_schema_drift(group: pd.DataFrame, dt: pd.Timestamp) -> pd.DataFrame:
    """Scenario #4 (breaking rename): collector_id -> collector_ref_id
    starting SCHEMA_DRIFT_RENAME_DAY_OFFSET days into the window."""
    drift_date = pd.Timestamp(cfg.WINDOW_START) + pd.Timedelta(days=cfg.SCHEMA_DRIFT_RENAME_DAY_OFFSET)
    if dt >= drift_date and "collector_id" in group.columns:
        group = group.rename(columns={"collector_id": "collector_ref_id"})
    return group
