# Azure to GCP Migration Summary

## Overview
The Cluster Breakdown Cloud application has been successfully refactored from Azure to Google Cloud Platform (GCP). All functionality remains identical, with only the underlying cloud services changed.

## Quick Reference: Service Changes

### Data Storage
| Operation | Azure (Old) | GCP (New) |
|-----------|-----------|----------|
| Upload CSV | `blob_client.upload_blob()` | `blob.upload_from_string()` |
| Download CSV | `blob_client.download_blob()` | `blob.download_as_bytes()` |
| List files | `blob_service_client.list_blobs()` | `bucket.list_blobs()` |

### Metadata & Logging
| Operation | Azure (Old) | GCP (New) |
|-----------|-----------|----------|
| Create record | `table_client.upsert_entity()` | `db.collection().document().set()` |
| Get record | `table_client.get_entity()` | `db.collection().document().get()` |
| List records | `table_client.list_entities()` | `db.collection().stream()` |

## File Changes

### Modified Files
1. **app.py** - Updated all Azure SDK calls to GCP equivalents
2. **requirements.txt** - Swapped Azure packages for Google Cloud packages

### New Files
1. **GCP_DEPLOYMENT_GUIDE.md** - Complete GCP deployment instructions
2. **AZURE_TO_GCP_MIGRATION.md** - This file

## Key Code Differences

### Configuration
```python
# Azure
STORAGE_CONN_STR = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
COSMOS_CONN_STR = os.environ.get('AZURE_COSMOS_CONNECTION_STRING')

# GCP
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
BUCKET_NAME = os.environ.get('GCP_BUCKET_NAME', 'cost-reports')
```

### Client Initialization
```python
# Azure
blob_service_client = BlobServiceClient.from_connection_string(STORAGE_CONN_STR)
table_service_client = TableServiceClient.from_connection_string(COSMOS_CONN_STR)

# GCP
storage_client = storage.Client(project=PROJECT_ID)
bucket = storage_client.bucket(BUCKET_NAME)
db = firestore.Client(project=PROJECT_ID)
```

### File Upload
```python
# Azure
blob_client.upload_blob(file.stream, overwrite=True)

# GCP
blob.upload_from_string(file.read())
```

### File Download
```python
# Azure
downloader = blob_client.download_blob()
stream = io.BytesIO(downloader.readall())

# GCP
data = blob.download_as_bytes()
stream = io.BytesIO(data)
```

### Metadata Storage
```python
# Azure
table_client.upsert_entity(entity=log_entity, mode=UpdateMode.MERGE)

# GCP
db.collection(collection_name).document(filename).set(log_data, merge=True)
```

### Metadata Retrieval
```python
# Azure
entity = table_client.get_entity(partition_key="Uploads", row_key=filename)

# GCP
doc = db.collection(collection_name).document(filename).get()
if doc.exists:
    data = doc.to_dict()
```

### List Metadata
```python
# Azure
entities = table_client.list_entities()
uploads_list = list(entities)

# GCP
docs = db.collection(collection_name).stream()
uploads_list = [doc.to_dict() for doc in docs]
```

## Environment Variables

### Old (Azure)
```
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_COSMOS_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountEndpoint=...
```

### New (GCP)
```
GCP_PROJECT_ID=your-project-123456
GCP_BUCKET_NAME=cost-reports
```

## Dependencies

### Before (Azure)
```
flask
pandas
numpy
gunicorn
azure-storage-blob
azure-data-tables
```

### After (GCP)
```
flask
pandas
numpy
gunicorn
google-cloud-storage
google-cloud-firestore
```

## Testing Checklist

- [ ] Local development environment runs successfully
- [ ] File upload works and stores in GCS
- [ ] Metadata is saved to Firestore
- [ ] Dashboard loads and displays data correctly
- [ ] CSV parsing and calculations unchanged
- [ ] List view shows all uploaded files
- [ ] Report generation works as expected
- [ ] Deployment to Cloud Run/App Engine succeeds

## Rollback Plan

If you need to revert to Azure:
```bash
git checkout HEAD -- app.py requirements.txt
export AZURE_STORAGE_CONNECTION_STRING=<your-azure-connection-string>
export AZURE_COSMOS_CONNECTION_STRING=<your-cosmos-connection-string>
flask run
```

## Performance Considerations

### GCP Advantages
- **Faster authentication**: Application Default Credentials vs connection strings
- **Simpler initialization**: Direct client creation vs parsing connection strings
- **Better scalability**: Cloud Run auto-scales; App Engine has native Python support
- **Lower latency**: GCS and Firestore can be in same region as compute

### Considerations
- **Firestore read/write costs**: May be higher than Table API for high-volume operations
- **Different eventual consistency model**: Firestore is strongly consistent
- **No connection pooling needed**: GCP SDKs handle this automatically

## Next Steps

1. Follow the **GCP_DEPLOYMENT_GUIDE.md** for deployment
2. Update CI/CD pipelines to use GCP services
3. Update infrastructure-as-code (Terraform/Deployment Manager) if applicable
4. Test thoroughly in staging environment
5. Monitor costs during transition period
