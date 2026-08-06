"""
Proves the schema_registry.yaml contract and drift-detection logic
(implemented for real in ingest_bronze.py's Spark/Databricks code) against
the ACTUAL Phase 5 generated data -- runnable in this sandbox without a
Spark cluster.

Usage:
    cd pyspark/bronze
    python3 validate_registry_local.py
"""
import glob
import os

import pandas as pd
import yaml

HERE = os.path.dirname(__file__)
OUTPUT_ROOT = os.path.join(HERE, "..", "..", "data", "synthetic", "output")


def load_registry():
    with open(os.path.join(HERE, "schema_registry.yaml")) as f:
        return yaml.safe_load(f)["tables"]


def detect_drift(actual_cols: set, cfg: dict):
    expected_cols = set(cfg["expected_columns"].keys())
    added = actual_cols - expected_cols
    missing = expected_cols - actual_cols

    known_renames = {
        e["detail"].split(" renamed to ")[0].strip(): e["detail"].split(" renamed to ")[1].strip()
        for e in cfg.get("known_drift_events", [])
        if e["type"] == "breaking_rename"
    }
    resolved_missing = set()
    for old_col, new_col in known_renames.items():
        if old_col in missing and new_col in added:
            resolved_missing.add(old_col)
            added.discard(new_col)
    missing -= resolved_missing

    if missing:
        return "breaking", added, missing
    if added and not cfg.get("allow_additive_drift", True):
        return "breaking", added, missing
    if added:
        return "additive", added, missing
    return "none", added, missing


def main():
    registry = load_registry()
    print("=== Bronze Schema Registry Validation (local, pandas) ===\n")

    for table_name, cfg in registry.items():
        table_dir = os.path.join(OUTPUT_ROOT, f"raw_{table_name}" if not table_name.startswith("raw_") else table_name)
        files = sorted(glob.glob(os.path.join(table_dir, "**", "*.csv"), recursive=True))
        if not files:
            print(f"{table_name:<38} -- NO FILES FOUND at {table_dir}")
            continue

        classifications = {}
        for f in files:
            partition_label = os.path.basename(os.path.dirname(f)) if "dt=" in f else "full_snapshot"
            cols = set(pd.read_csv(f, nrows=0).columns)
            classification, added, missing = detect_drift(cols, cfg)
            classifications.setdefault(classification, []).append((partition_label, added, missing))

        total = sum(len(v) for v in classifications.values())
        summary = ", ".join(f"{k}={len(v)}" for k, v in classifications.items())
        print(f"{table_name:<38} {total:>4} files scanned  ->  {summary}")

        for cls in ("breaking",):
            if cls in classifications:
                for partition_label, added, missing in classifications[cls][:2]:
                    print(f"    [{cls}] {partition_label}: added={added or '{}'} missing={missing or '{}'}")
        if "additive" in classifications:
            examples = classifications["additive"][:1]
            for partition_label, added, missing in examples:
                print(f"    [additive example] {partition_label}: added={added}")

    print("\nDone. 'breaking' counts above that persist across MANY files (not just the "
          "documented rename window) would indicate a registry/generator mismatch.")


if __name__ == "__main__":
    main()
