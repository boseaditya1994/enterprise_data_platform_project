import os
from azure.storage.blob import BlobServiceClient

conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
service_client = BlobServiceClient.from_connection_string(conn_str)
container_client = service_client.get_container_client("landing")

# Test 1: simple flat blob name, no nested folders
container_client.upload_blob(name="diagnostic_test.txt", data=b"hello", overwrite=True)
print("Flat upload: SUCCESS")

# Test 2: the actual nested path style our pipeline uses
container_client.upload_blob(name="raw_payments/dt=2026-09-16/diagnostic_test.csv", data=b"hello", overwrite=True)
print("Nested-path upload: SUCCESS")