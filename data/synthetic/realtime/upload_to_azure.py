"""
Uploads today's locally-written CSV files to the real Azure Storage landing
container, and separately pushes them into the Databricks Unity Catalog
volume via the Files API.
"""
import os
import requests

try:
    from azure.storage.blob import BlobServiceClient
except ImportError:
    BlobServiceClient = None


def upload_landing_files(file_paths: list, local_landing_root: str, container_name: str = "landing"):
    if BlobServiceClient is None:
        raise ImportError("azure-storage-blob not installed -- pip install azure-storage-blob")

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is not set")

    service_client = BlobServiceClient.from_connection_string(conn_str)
    container_client = service_client.get_container_client(container_name)

    uploaded = []
    for path in file_paths:
        blob_path = os.path.relpath(path, local_landing_root).replace(os.sep, "/")
        with open(path, "rb") as f:
            container_client.upload_blob(name=blob_path, data=f, overwrite=True)
        uploaded.append(blob_path)
        print(f"  Uploaded to Azure Blob: {blob_path}")

    return uploaded


def upload_to_databricks_volume(file_paths: list, local_landing_root: str,
                                  volume_base: str = "/Volumes/workspace/landing/raw_landing/output"):
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    uploaded = []
    for path in file_paths:
        rel_path = os.path.relpath(path, local_landing_root).replace(os.sep, "/")
        volume_path = f"{volume_base}/{rel_path}"
        with open(path, "rb") as f:
            resp = requests.put(
                f"{host}/api/2.0/fs/files{volume_path}",
                headers=headers,
                data=f,
                params={"overwrite": "true"},
            )
        resp.raise_for_status()
        uploaded.append(volume_path)
        print(f"  Uploaded to Databricks volume: {volume_path}")

    return uploaded