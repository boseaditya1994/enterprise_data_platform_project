"""
Persists and loads the simulation's state between daily runs. State now
lives as plain files inside the git repo itself (committed by the
workflow after each run) -- no external cloud storage needed at all.
"""
import os
import json
import pandas as pd

STATE_FILE = "loan_state.csv"
PENDING_PTPS_FILE = "pending_ptps.csv"
METADATA_FILE = "metadata.json"


def save_state(state_df: pd.DataFrame, pending_ptps_df: pd.DataFrame, last_simulated_date, state_dir: str):
    os.makedirs(state_dir, exist_ok=True)
    state_df.to_csv(os.path.join(state_dir, STATE_FILE), index=False)
    pending_ptps_df.to_csv(os.path.join(state_dir, PENDING_PTPS_FILE), index=False)
    with open(os.path.join(state_dir, METADATA_FILE), "w") as f:
        json.dump({"last_simulated_date": str(last_simulated_date)}, f)


def load_state(state_dir: str):
    state_path = os.path.join(state_dir, STATE_FILE)
    if not os.path.exists(state_path):
        return None

    state_df = pd.read_csv(state_path)
    pending_ptps_df = pd.read_csv(os.path.join(state_dir, PENDING_PTPS_FILE))
    with open(os.path.join(state_dir, METADATA_FILE)) as f:
        metadata = json.load(f)

    return state_df, pending_ptps_df, pd.Timestamp(metadata["last_simulated_date"])