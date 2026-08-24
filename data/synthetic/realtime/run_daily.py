"""
The single entry point run once per day.
"""
import argparse
import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from advance_one_day import advance_one_day  # noqa: E402
from write_daily_events import write_daily_events  # noqa: E402
from state_store import save_state, load_state, azure_download_state, azure_upload_state  # noqa: E402
from upload_to_azure import upload_landing_files, upload_to_databricks_volume  # noqa: E402

EMPTY_PENDING_PTPS_COLUMNS = ["ptp_id", "loan_id", "customer_id", "contact_id", "collector_ref_id",
                              "ptp_created_date", "ptp_promised_date", "ptp_amount",
                              "ptp_status", "amount_paid_against_ptp", "fulfillment_date"]


def run_daily(state_dir: str, landing_dir: str, target_date: pd.Timestamp,
              seed_state_path: str = None, seed_roster_path: str = None, rng=None,
              use_azure: bool = False):
    rng = rng or np.random.default_rng()

    if use_azure:
        azure_download_state(state_dir)

    loaded = load_state(state_dir)
    if loaded is None:
        if seed_state_path is None:
            raise ValueError("No persisted state found and no --seed-state-path given -- "
                              "run extract_seed_state.sql against Snowflake first.")
        print(f"Cold start: seeding from {seed_state_path}")
        state = pd.read_csv(seed_state_path)
        state.columns = state.columns.str.lower()
        pending_ptps = pd.DataFrame(columns=EMPTY_PENDING_PTPS_COLUMNS)
    else:
        state, pending_ptps, last_date = loaded
        print(f"Resuming from persisted state (last simulated: {last_date.date()})")
        if target_date <= last_date:
            raise ValueError(f"target_date {target_date.date()} is not after last simulated date "
                              f"{last_date.date()} -- refusing to re-simulate or skip backwards.")

    roster = pd.read_csv(seed_roster_path) if seed_roster_path else None
    if roster is not None:
        roster.columns = roster.columns.str.lower()
    if roster is None:
        roster_path = os.path.join(state_dir, "collector_roster.csv")
        if not os.path.exists(roster_path):
            raise ValueError("No collector roster available -- pass --seed-roster-path on first run.")
        roster = pd.read_csv(roster_path)
    os.makedirs(state_dir, exist_ok=True)
    roster.to_csv(os.path.join(state_dir, "collector_roster.csv"), index=False)

    new_state, new_pending_ptps, events = advance_one_day(state, pending_ptps, roster, target_date, rng=rng)

    written_files = write_daily_events(events, target_date, landing_dir)
    save_state(new_state, new_pending_ptps, target_date, state_dir)

    if use_azure:
        if written_files:
            upload_landing_files(written_files, landing_dir)
            upload_to_databricks_volume(written_files, landing_dir)
        azure_upload_state(state_dir)

    print(f"\nDay complete: {target_date.date()}")
    print(f"Files written: {written_files or '(none -- no events today)'}")
    return new_state, new_pending_ptps, events, written_files


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--landing-dir", required=True)
    parser.add_argument("--target-date", default=None)
    parser.add_argument("--seed-state-path", default=None)
    parser.add_argument("--seed-roster-path", default=None)
    parser.add_argument("--use-azure", action="store_true")
    args = parser.parse_args()

    target = pd.Timestamp(args.target_date) if args.target_date else pd.Timestamp.today().normalize()
    run_daily(args.state_dir, args.landing_dir, target, args.seed_state_path, args.seed_roster_path,
              use_azure=args.use_azure)