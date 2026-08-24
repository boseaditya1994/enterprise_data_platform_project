"""
Persists and loads the simulation's state between daily runs.
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


STATE_CONTAINER = "simstate"


def azure_download_state(local_state_dir: str):
    from azure.storage.blob import BlobServiceClient

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is not set")

    service_client = BlobServiceClient.from_connection_string(conn_str)
    container_client = service_client.get_container_client(STATE_CONTAINER)

    os.makedirs(local_state_dir, exist_ok=True)
    downloaded_any = False
    for filename in [STATE_FILE, PENDING_PTPS_FILE, METADATA_FILE, "collector_roster.csv"]:
        blob_client = container_client.get_blob_client(filename)
        if blob_client.exists():
            with open(os.path.join(local_state_dir, filename), "wb") as f:
                f.write(blob_client.download_blob().readall())
            downloaded_any = True
    if downloaded_any:
        print(f"Downloaded persisted state from Azure container '{STATE_CONTAINER}'")
    else:
        print(f"No prior state found in Azure container '{STATE_CONTAINER}' -- this is a cold start")


def azure_upload_state(local_state_dir: str):
    from azure.storage.blob import BlobServiceClient

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is not set")

    service_client = BlobServiceClient.from_connection_string(conn_str)
    container_client = service_client.get_container_client(STATE_CONTAINER)
    try:
        container_client.create_container()
    except Exception:
        pass

    for filename in [STATE_FILE, PENDING_PTPS_FILE, METADATA_FILE, "collector_roster.csv"]:
        local_path = os.path.join(local_state_dir, filename)
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                container_client.upload_blob(name=filename, data=f, overwrite=True)
    print(f"Uploaded state to Azure container '{STATE_CONTAINER}'")