# Loading API Keys from Elasticsearch

This document describes how to load API keys from an Elasticsearch index into the SQLite backend at startup.

**Note:** As of the current version, Elasticsearch is **no longer used as a storage backend**. SQLite is always used for API key storage. However, you can configure the system to load API keys from an existing Elasticsearch index at application startup.

## Overview

The system always uses SQLite as the storage backend for performance and simplicity. However, if you have existing API keys stored in an Elasticsearch index, you can configure the application to load them into SQLite at startup.

This is useful for:

- Migrating from a previous Elasticsearch-based deployment
- Synchronizing API keys from a centralized Elasticsearch store
- Loading API keys from an external system that writes to Elasticsearch

## Environment Variables

### Required for Loading from Elasticsearch

- **`FASTAPI_ES_APIKEY_STORAGE_INDEX`**: Name of the Elasticsearch index to load API keys from
  - If not set, no keys will be loaded from Elasticsearch
  - Keys are loaded once at application startup

### Elasticsearch Connection (Optional)

- **`FASTAPI_SIMPLE_SECURITY_ES_HOSTS`**: Comma-separated list of Elasticsearch hosts (default: `http://localhost:9200`)
- **`FASTAPI_SIMPLE_SECURITY_ES_USER`**: Elasticsearch username (optional, for basic auth)
- **`FASTAPI_SIMPLE_SECURITY_ES_PASSWORD`**: Elasticsearch password (optional, for basic auth)
- **`FASTAPI_SIMPLE_SECURITY_ES_API_KEY`**: Elasticsearch API key (optional, takes precedence over basic auth)

### Deprecated

- **`FASTAPI_SIMPLE_SECURITY_BACKEND`**: Previously allowed selection between `sqlite` and `elasticsearch`
  - Now deprecated - SQLite is always used
  - Setting this to `elasticsearch` will trigger a deprecation warning

## Installation

To load keys from Elasticsearch, install the elasticsearch package:

```bash
pip install elasticsearch
```

## Usage Example

### Basic Configuration

```python
import os
from fastapi import FastAPI, Depends

# Configure to load API keys from Elasticsearch index
os.environ["FASTAPI_ES_APIKEY_STORAGE_INDEX"] = "my_apikeys_index"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "http://localhost:9200"

# Import after setting environment variables
from fastapi_simple_security import api_key_router, api_key_security

app = FastAPI()

# Include the API key management endpoints
app.include_router(api_key_router, prefix="/auth", tags=["authentication"])


@app.get("/secure-endpoint")
async def secure_endpoint(api_key: str = Depends(api_key_security)):
    return {"message": "This is a secure endpoint", "api_key": api_key}
```

### With Authentication

```python
import os

# Configure with basic auth
os.environ["FASTAPI_ES_APIKEY_STORAGE_INDEX"] = "my_apikeys_index"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "https://my-es-cluster.com:9200"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_USER"] = "my_user"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_PASSWORD"] = "my_password"
```

### With API Key Authentication

```python
import os

# Configure with Elasticsearch API key
os.environ["FASTAPI_ES_APIKEY_STORAGE_INDEX"] = "my_apikeys_index"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "https://my-es-cluster.com:9200"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_API_KEY"] = "my_elasticsearch_api_key"
```

## Elasticsearch Index Setup

### Index Mappings

Create your Elasticsearch index with the following mappings to match the CSV file format (`name;api_key;expiration_date`):

```json
PUT /my_apikeys_index
{
  "mappings": {
    "properties": {
      "name": {
        "type": "keyword"
      },
      "api_key": {
        "type": "keyword"
      },
      "expiration_date": {
        "type": "date",
        "format": "strict_date_time||strict_date_time_no_millis||epoch_millis"
      }
    }
  }
}
```

**Field Types:**

- **`name`**: `keyword` - Short name/identifier for the API key (e.g., "production-service", "user-api")
- **`api_key`**: `keyword` - The actual API key value (UUID or custom string)
- **`expiration_date`**: `date` - ISO 8601 formatted expiration date (e.g., "2025-12-31T23:59:59")

**Note:** While the deprecated Elasticsearch backend used additional fields (`is_active`, `never_expire`, `latest_query_date`, `total_queries`, `project_name`), only the three fields above are used when loading keys into SQLite.

## Expected Elasticsearch Document Structure

The Elasticsearch index should contain documents matching the CSV format (`name;api_key;expiration_date`):

```json
{
  "name": "production-service",
  "api_key": "550e8400-e29b-41d4-a716-446655440000",
  "expiration_date": "2025-12-31T23:59:59"
}
```

### Example: Indexing Multiple Keys

```json
POST /my_apikeys_index/_bulk
{"index": {"_id": "550e8400-e29b-41d4-a716-446655440000"}}
{"name": "production-service", "api_key": "550e8400-e29b-41d4-a716-446655440000", "expiration_date": "2025-12-31T23:59:59"}
{"index": {"_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"}}
{"name": "staging-service", "api_key": "6ba7b810-9dad-11d1-80b4-00c04fd430c8", "expiration_date": "2026-06-30T23:59:59"}
{"index": {"_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"}}
{"name": "test-api", "api_key": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "expiration_date": ""}
```

### Field Descriptions

- **`name`**: Short name/identifier for the key (required) - corresponds to first field in CSV
- **`api_key`**: The unique API key value (required) - corresponds to second field in CSV
- **`expiration_date`**: ISO 8601 formatted expiration date (optional, can be empty string) - corresponds to third field in CSV
  - If empty or not provided, a default expiration will be set based on `FAST_API_SIMPLE_SECURITY_AUTOMATIC_EXPIRATION`

### CSV File Format Equivalence

The document structure directly matches the CSV file format used by `FASTAPI_SIMPLE_SECURITY_API_KEY_FILE`:

```csv
# CSV format: name;api_key;expiration_date
production-service;550e8400-e29b-41d4-a716-446655440000;2025-12-31T23:59:59
staging-service;6ba7b810-9dad-11d1-80b4-00c04fd430c8;2026-06-30T23:59:59
test-api;7c9e6679-7425-40de-944b-e07fc1f90ae7;
```

## How It Works

1. At application startup, if `FASTAPI_ES_APIKEY_STORAGE_INDEX` is set, the system connects to Elasticsearch
2. All documents from the specified index are retrieved
3. Each API key is inserted into the SQLite database using the same logic as loading from a file
4. If a key already exists in SQLite, it is renewed with the expiration date from Elasticsearch
5. The Elasticsearch connection is closed after loading is complete
6. All subsequent API key operations (validation, creation, revocation) use only SQLite

## Migration from Elasticsearch Backend

If you previously used Elasticsearch as the storage backend (deprecated):

1. Set `FASTAPI_ES_APIKEY_STORAGE_INDEX` to your existing Elasticsearch index name
2. Remove or ignore `FASTAPI_SIMPLE_SECURITY_BACKEND` (it's deprecated)
3. Start your application - all keys will be loaded into SQLite
4. All new API key operations will use SQLite
5. You can continue to update the Elasticsearch index externally and reload by restarting the application

## Benefits of SQLite Backend

- **Performance**: Faster API key validation, especially with caching
- **Simplicity**: No external dependencies for basic operation
- **Reliability**: Local storage, no network dependencies during operation
- **Portability**: Single file database, easy to backup and migrate

## Limitations

- API keys are loaded only at startup - changes to the Elasticsearch index require an application restart
- The Elasticsearch index is read-only - no writes occur to Elasticsearch
- Maximum of 10,000 keys can be loaded from Elasticsearch in one query (Elasticsearch limitation)
