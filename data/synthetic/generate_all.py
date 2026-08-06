"""
Orchestrates the full synthetic data generation run described in
Phase 4 (docs/04-dataset-design.md) and Phase 5 (docs/05-synthetic-data-generation.md).

Usage:
    cd data/synthetic
    python3 generate_all.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from generator import config as cfg
from generator import identities, simulate_lifecycle, generate_events, bureau_risk, messiness, writer


def main():
    t0 = time.time()
    root = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(root, exist_ok=True)

    print(f"=== Loan Delinquency & Collections Command Center — Synthetic Data Generator ===")
    print(f"Scale profile: {cfg.SCALE_PROFILE}  (customers={cfg.N_CUSTOMERS}, loans={cfg.N_LOANS})")
    print(f"Window: {cfg.WINDOW_START} .. {cfg.WINDOW_END} ({cfg.N_DAYS} days)\n")

    print("[1/9] Generating customers (CRM)...")
    customers_df = identities.generate_customers()
    customers_df = identities.apply_relocations(customers_df)
    print(f"      customers: {customers_df['customer_id'].nunique()} unique, {len(customers_df)} CRM records (incl. relocations)")

    print("[2/9] Generating collector roster...")
    collectors_df = identities.generate_collectors()
    print(f"      collectors: {collectors_df['collector_id'].nunique()} unique, {len(collectors_df)} records (incl. reorg)")

    print("[3/9] Generating applications & loans...")
    customer_ids = customers_df["customer_id"].unique().tolist()
    applications_df, loans_df, bridge_df = identities.generate_applications_and_loans(customer_ids)
    print(f"      applications: {len(applications_df)}  |  approved loans: {len(loans_df)}  |  joint-applicant links: {len(bridge_df)}")

    print("[4/9] Simulating loan lifecycle (delinquency, payments, restructure/charge-off)...")
    daily_df, payment_events_df, loan_events_df = simulate_lifecycle.simulate(loans_df)
    print(f"      delinquency-fact rows: {len(daily_df):,}  |  scheduled payment events: {len(payment_events_df):,}  |  loan events: {len(loan_events_df):,}")

    print("[5/9] Finalizing payments (methods, reversals, NSF returns, extras, late arrivals)...")
    payments_df = messiness.finalize_payments(payment_events_df, loans_df)
    payments_df = messiness.inject_duplicates(payments_df, cfg.PCT_DUPLICATE_PAYMENT_EVENTS, seed_offset=10)
    payments_df = messiness.inject_corrupt_records(payments_df, amount_col="payment_amount", seed_offset=11)
    print(f"      payment_fact rows (post-messiness): {len(payments_df):,}")

    print("[6/9] Generating contact events & promises-to-pay...")
    contacts_df = generate_events.generate_contacts(daily_df, collectors_df)
    contacts_df = messiness.inject_duplicates(contacts_df, cfg.PCT_DUPLICATE_CONTACT_EVENTS, seed_offset=12)
    contacts_df = messiness.inject_corrupt_records(contacts_df, amount_col=None, seed_offset=13)
    ptp_df = generate_events.generate_promises_to_pay(contacts_df, daily_df)
    print(f"      contact_fact rows: {len(contacts_df):,}  |  promise_to_pay_fact rows: {len(ptp_df):,}")

    print("[7/9] Generating Bureau & Risk Engine extracts...")
    bureau_df = bureau_risk.generate_bureau_extracts(loans_df)
    risk_df = bureau_risk.generate_risk_engine_extracts(loans_df, loan_events_df)
    print(f"      bureau records: {len(bureau_df):,}  |  risk engine records: {len(risk_df):,}")

    print("[8/9] Writing partitioned Bronze-style raw extracts to disk...")
    n = 0
    n += writer.write_partitioned(customers_df, "source_updated_at", "crm", root)
    writer.write_full_snapshot(collectors_df, "collectors", root)  # small; also partition below for realism
    n += writer.write_partitioned(collectors_df, "source_updated_at", "collectors_daily", root)
    n += writer.write_partitioned(applications_df, "application_date", "servicing_applications", root)
    n += writer.write_partitioned(loans_df, "origination_date", "servicing_loans", root)
    n += writer.write_partitioned(daily_df, "snapshot_date", "servicing_daily_status", root,
                                   schema_drift_fn=writer.servicing_schema_drift)
    n += writer.write_partitioned(loan_events_df, "event_date", "servicing_loan_events", root)
    n += writer.write_partitioned(payments_df, "ingestion_date", "payments", root)
    call_center = contacts_df[contacts_df["source_system"] == "CALL_CENTER"]
    collections_contacts = contacts_df[contacts_df["source_system"] == "COLLECTIONS_PLATFORM"]
    n += writer.write_partitioned(call_center, "contact_date", "call_center", root)
    n += writer.write_partitioned(collections_contacts, "contact_date", "collections", root,
                                   schema_drift_fn=writer.collections_schema_drift)
    n += writer.write_partitioned(ptp_df, "ptp_created_date", "collections_ptp", root,
                                   schema_drift_fn=writer.collections_schema_drift)
    n += writer.write_partitioned(bureau_df, "source_updated_at", "bureau", root)
    n += writer.write_partitioned(risk_df, "file_date", "risk_scores", root)
    writer.write_full_snapshot(bridge_df, "servicing_loan_applicant_bridge", root)
    print(f"      wrote {n} daily partitions + 2 full-snapshot reference files under {root}/")

    print("[9/9] Summary vs. Phase 4 targets:")
    summary = [
        ("customer_dim (incl. SCD2 versions)", len(customers_df), "~8,500"),
        ("loan_dim (incl. SCD2 versions)", len(loans_df) + len(loan_events_df[loan_events_df.event_type.isin(["RESTRUCTURE"])]), "~10,800"),
        ("collector_dim (incl. SCD2 versions)", len(collectors_df), "~140"),
        ("payment_fact", len(payments_df), "~69,000"),
        ("delinquency_fact", len(daily_df), "~1,800,000"),
        ("contact_fact", len(contacts_df), "~40,000"),
        ("promise_to_pay_fact", len(ptp_df), "~3,500"),
        ("loan_applicant_bridge", len(bridge_df), "~1,500"),
    ]
    for name, actual, target in summary:
        print(f"      {name:<38} actual={actual:>10,}   target={target}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s.")


if __name__ == "__main__":
    main()
