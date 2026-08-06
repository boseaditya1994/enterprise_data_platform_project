"""
Reads back the generated Bronze-style raw extracts and reports the
ACTUAL achieved rate of every Phase 4 Section 5 scenario, so the
dataset's realism claims are verifiable rather than asserted.

Usage:
    cd data/synthetic
    python3 validate.py
"""
import glob
import os

import pandas as pd


def load_table(root: str, table_name: str) -> pd.DataFrame:
    paths = sorted(glob.glob(os.path.join(root, f"raw_{table_name}", "**", "*.csv"), recursive=True))
    if not paths:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)


def main():
    root = os.path.join(os.path.dirname(__file__), "output")
    print("=== Synthetic Data Validation Report ===\n")

    payments = load_table(root, "payments")
    contacts_cc = load_table(root, "call_center")
    contacts_col = load_table(root, "collections")
    daily = load_table(root, "servicing_daily_status")
    loan_events = load_table(root, "servicing_loan_events")
    bureau = load_table(root, "bureau")

    n_pay = len(payments)
    print(f"payment_fact rows: {n_pay:,}")
    if n_pay:
        print(f"  reversal rate:        {payments['is_reversal_flag'].mean():.2%}  (target ~2%)")
        print(f"  NSF/returned rate:    {payments['nsf_flag'].mean():.2%}  (target ~1.5%)")
        print(f"  late-arrival rate:    {payments['is_late_arrival'].mean():.2%}  (target ~4%)")
        dupe_rate = 1 - payments['payment_id'].nunique() / n_pay
        print(f"  duplicate rate:       {dupe_rate:.2%}  (target ~1%)")
        print(f"  corrupt record rate:  {payments.get('is_corrupt_record', pd.Series(dtype=bool)).mean():.2%}  (target ~0.3%)")
        print(f"  payment type mix:\n{payments['payment_type'].value_counts(normalize=True).round(3).to_string()}")

    n_contacts = len(contacts_cc) + len(contacts_col)
    print(f"\ncontact_fact rows: {n_contacts:,}  (call_center={len(contacts_cc):,}, collections={len(contacts_col):,})")
    if len(contacts_col):
        # collector_id renamed to collector_ref_id after schema-drift date; unify for the report
        col = "collector_ref_id" if "collector_ref_id" in contacts_col.columns else "collector_id"
        print(f"  schema-drift rename present in raw_collections: "
              f"{'collector_ref_id' in contacts_col.columns and 'collector_id' in contacts_col.columns}")
    all_contacts = pd.concat([contacts_cc, contacts_col], ignore_index=True) if n_contacts else pd.DataFrame()
    if len(all_contacts):
        print(f"  RPC rate: {all_contacts['is_rpc_flag'].mean():.2%}")
        print(f"  complaint flag rate: {all_contacts['complaint_flag'].mean():.3%}")

    print(f"\ndelinquency_fact rows: {len(daily):,}")
    if len(daily):
        print(f"  bucket distribution:\n{daily['delinquency_bucket'].value_counts(normalize=True).round(4).to_string()}")
        drift_col_present = "loan_purpose_code" in daily.columns
        print(f"  schema-drift additive column present: {drift_col_present}")
        if drift_col_present:
            pct_with_col = daily["loan_purpose_code"].notna().mean()
            print(f"    rows carrying loan_purpose_code (post drift-date): {pct_with_col:.2%}")

    print(f"\nloan_events: {len(loan_events):,}")
    if len(loan_events):
        print(loan_events["event_type"].value_counts().to_string())

    print(f"\nbureau records: {len(bureau):,}")
    if len(bureau):
        print(f"  late-arrival rate: {bureau['is_late_arrival'].mean():.2%}  (target ~5%)")

    outage_partitions = sorted(glob.glob(os.path.join(root, "raw_bureau", "dt=*")))
    print(f"\nraw_bureau partitions written: {len(outage_partitions)} "
          f"(out of 181 calendar days -- gaps include weekends/non-file-days AND the 2 simulated outage days)")


if __name__ == "__main__":
    main()
