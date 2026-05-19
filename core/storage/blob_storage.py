import os
from io import BytesIO
import pandas as pd
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

load_dotenv()

CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_BLOB_CONTAINER")

blob_service_client = None
container_client = None

# -------------------------------------------------
# Initialize Blob Client
# -------------------------------------------------
def get_container_client():

    global blob_service_client
    global container_client

    if container_client is None:

        blob_service_client = BlobServiceClient.from_connection_string(
            CONNECTION_STRING
        )

        container_client = blob_service_client.get_container_client(
            CONTAINER_NAME
        )

    return container_client


# -------------------------------------------------
# Upload File
# -------------------------------------------------
def upload_file(file, blob_name):

    container = get_container_client()

    blob_client = container.get_blob_client(blob_name)

    blob_client.upload_blob(
        file.getvalue(),
        overwrite=True
    )

    return blob_name


# -------------------------------------------------
# List Files
# -------------------------------------------------
def list_files(prefix=None):

    container = get_container_client()

    blobs = container.list_blobs(
        name_starts_with=prefix
    )

    return [b.name for b in blobs]


# -------------------------------------------------
# Read CSV
# -------------------------------------------------
def read_csv_blob(blob_name):

    container = get_container_client()

    blob_client = container.get_blob_client(blob_name)

    data = blob_client.download_blob().readall()

    return pd.read_csv(BytesIO(data))


# -------------------------------------------------
# Read Excel
# -------------------------------------------------
def read_excel_blob(blob_name):

    container = get_container_client()

    blob_client = container.get_blob_client(blob_name)

    data = blob_client.download_blob().readall()

    return pd.read_excel(BytesIO(data))