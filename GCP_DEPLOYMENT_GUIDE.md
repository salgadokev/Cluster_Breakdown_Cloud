# GCP Deployment Guide for Cluster Breakdown Cloud

This application has been refactored to use Google Cloud Platform (GCP) services instead of Azure.

## Service Mapping

| Azure Service | GCP Equivalent | Purpose |
|---|---|---|
| Azure Blob Storage | Google Cloud Storage (GCS) | Store CSV cost reports |
| Azure Cosmos DB (Table API) | Firestore | Store metadata and upload logs |
| Azure App Service | Cloud Run / App Engine | Host the Flask application |

## Prerequisites

1. **GCP Project**: Create a GCP project at [Google Cloud Console](https://console.cloud.google.com)
2. **gcloud CLI**: Install and authenticate the Google Cloud CLI
3. **Python 3.9+**: Ensure Python is installed locally
4. **Permissions**: Your GCP account must have permissions to create Cloud Storage buckets, Firestore databases, and Cloud Run services

## Setup Instructions

### 1. Create GCP Resources

#### A. Create a Cloud Storage Bucket
```bash
gsutil mb gs://cost-reports
```
Replace `cost-reports` with your desired bucket name.

#### B. Create a Firestore Database
```bash
gcloud firestore databases create --region=us-central1
```
Choose a region appropriate for your location.

### 2. Set Environment Variables

Create a `.env` file or set environment variables in your deployment platform:

```bash
export GCP_PROJECT_ID="your-gcp-project-id"
export GCP_BUCKET_NAME="kev-breakdowntooly"
```

### 3. Update Dependencies

The `requirements.txt` has been updated to use GCP SDKs:
```
flask
pandas
numpy
gunicorn
google-cloud-storage
google-cloud-firestore
```

Install dependencies:
```bash
pip install -r requirements.txt
```

### 4. Authentication

The application uses Application Default Credentials (ADC). Choose one:

#### Option A: Local Development
```bash
gcloud auth application-default login
```

#### Option B: Cloud Run Deployment
Assign the `Editor` role to the Cloud Run service account, or create a custom role with:
- `storage.buckets.get`
- `storage.objects.create`
- `storage.objects.delete`
- `storage.objects.get`
- `datastore.databases.get`
- `datastore.entities.create`
- `datastore.entities.delete`
- `datastore.entities.get`
- `datastore.entities.list`
- `datastore.entities.update`

### 5. Run Locally

```bash
flask run
```

The application will be available at `http://localhost:5000`

### 6. Deploy to Cloud Run

#### Build and Deploy
```bash
gcloud run deploy cluster-breakdown-cloud \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCP_PROJECT_ID=your-project-id,GCP_BUCKET_NAME=cost-reports
```

#### Or using a Dockerfile
Create a `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app
```

Deploy:
```bash
gcloud run deploy cluster-breakdown-cloud \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCP_PROJECT_ID=your-project-id,GCP_BUCKET_NAME=cost-reports
```

### 7. Deploy to App Engine

Create `app.yaml`:
```yaml
runtime: python311
env: standard

env_variables:
  GCP_PROJECT_ID: "your-project-id"
  GCP_BUCKET_NAME: "cost-reports"

handlers:
- url: /.*
  script: auto
```

Deploy:
```bash
gcloud app deploy
```

## Code Changes Made

### 1. Imports
- Replaced: `from azure.storage.blob import BlobServiceClient`
- With: `from google.cloud import storage`

- Replaced: `from azure.data.tables import TableServiceClient, UpdateMode`
- With: `from google.cloud import firestore`

### 2. Initialization
- **Azure**:
  ```python
  blob_service_client = BlobServiceClient.from_connection_string(STORAGE_CONN_STR)
  table_service_client = TableServiceClient.from_connection_string(COSMOS_CONN_STR)
  ```
- **GCP**:
  ```python
  storage_client = storage.Client(project=PROJECT_ID)
  bucket = storage_client.bucket(BUCKET_NAME)
  db = firestore.Client(project=PROJECT_ID)
  ```

### 3. Blob Operations
- **Azure**: `blob_client.upload_blob(file.stream, overwrite=True)`
- **GCP**: `blob.upload_from_string(file.read())`

- **Azure**: `downloader = blob_client.download_blob()` → `stream = io.BytesIO(downloader.readall())`
- **GCP**: `data = blob.download_as_bytes()` → `stream = io.BytesIO(data)`

### 4. Database Operations
- **Azure**: `table_client.upsert_entity(entity=log_entity, mode=UpdateMode.MERGE)`
- **GCP**: `db.collection(collection_name).document(filename).set(log_data, merge=True)`

- **Azure**: `table_client.get_entity(partition_key="Uploads", row_key=filename)`
- **GCP**: `db.collection(collection_name).document(filename).get()`

- **Azure**: `table_client.list_entities()`
- **GCP**: `db.collection(collection_name).stream()`

## Testing

### Local Testing
```bash
# Install test dependencies
pip install pytest pytest-flask

# Run tests
pytest
```

### Production Validation
1. Upload a CSV file through the UI
2. Verify it appears in the Cloud Storage bucket
3. Check Firestore for metadata entries
4. Generate a dashboard and verify calculations

## Monitoring and Logging

### View Logs
```bash
# Cloud Run logs
gcloud run logs read cluster-breakdown-cloud --limit 50

# App Engine logs
gcloud app logs read
```

### Enable Cloud Logging
```python
import logging
from google.cloud import logging as cloud_logging

client = cloud_logging.Client()
client.setup_logging()
logging.basicConfig(level=logging.INFO)
```

## Cost Comparison

### Azure (Previous)
- Azure Blob Storage: ~$0.018/GB stored
- Azure Cosmos DB: ~$1.25/100 RU/s
- App Service: ~$15-100/month

### GCP (New)
- Cloud Storage: ~$0.020/GB stored
- Firestore: ~$0.06 per 100K reads/writes
- Cloud Run: Pay per request (~$0.40 per 1M invocations)
- App Engine: ~$11/month base

## Troubleshooting

### Issue: "CRITICAL: Failed to initialize GCP clients"
**Solution**: 
- Verify `GCP_PROJECT_ID` environment variable is set
- Ensure authenticated with `gcloud auth application-default login`
- Check IAM permissions for the service account

### Issue: "Permission denied" on bucket operations
**Solution**:
- Verify service account has `storage.objects.*` permissions
- Re-authenticate: `gcloud auth application-default login`

### Issue: "NotFound" error from Firestore
**Solution**:
- Ensure Firestore database is created
- Verify `collection_name` variable matches your setup

## Reverting to Azure

If you need to switch back to Azure:
1. Restore `app.py` from Git history
2. Restore `requirements.txt` with Azure dependencies
3. Set Azure connection string environment variables

## Additional Resources

- [Google Cloud Storage Documentation](https://cloud.google.com/storage/docs)
- [Cloud Firestore Documentation](https://cloud.google.com/firestore/docs)
- [Cloud Run Deployment Guide](https://cloud.google.com/run/docs/quickstarts/build-and-deploy)
- [App Engine Python Deployment](https://cloud.google.com/appengine/docs/standard/python-runtime)
