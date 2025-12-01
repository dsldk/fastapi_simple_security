# Elasticsearch Backend Configuration

This document describes how to configure and use the Elasticsearch backend for storing API keys instead of the default SQLite database.

## Environment Variables

### Backend Selection

- **`FASTAPI_SIMPLE_SECURITY_BACKEND`**: Set to `elasticsearch` to use Elasticsearch backend (default: `sqlite`)

### Elasticsearch Connection

- **`FASTAPI_SIMPLE_SECURITY_ES_HOSTS`**: Comma-separated list of Elasticsearch hosts (default: `http://localhost:9200`)
- **`FASTAPI_SIMPLE_SECURITY_ES_USER`**: Elasticsearch username (optional, for basic auth)
- **`FASTAPI_SIMPLE_SECURITY_ES_PASSWORD`**: Elasticsearch password (optional, for basic auth)
- **`FASTAPI_SIMPLE_SECURITY_ES_API_KEY`**: Elasticsearch API key (optional, takes precedence over basic auth)

### Other Settings

- **`FAST_API_SIMPLE_SECURITY_AUTOMATIC_EXPIRATION`**: Number of days before API keys expire (default: `15`)

## Installation

To use the Elasticsearch backend, install the elasticsearch package:

```bash
pip install elasticsearch
```

Or install with the optional dependency (when available):

```bash
pip install fastapi_simple_security[elasticsearch]
```

## Usage Example

### Basic Configuration

```python
import os

# Configure Elasticsearch backend
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "http://localhost:9200"

from fastapi import FastAPI
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
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "https://my-es-cluster.com:9200"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_USER"] = "my_user"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_PASSWORD"] = "my_password"
```

### With API Key Authentication

```python
import os

# Configure with Elasticsearch API key
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "https://my-es-cluster.com:9200"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_API_KEY"] = "my_elasticsearch_api_key"
```

## API Key Management with Project Names

When using the Elasticsearch backend, you can now provide additional metadata for API keys:

### Creating API Keys

```python
import requests

# Create a new API key with project information
response = requests.get(
    "http://localhost:8000/auth/new",
    params={
        "name": "user-service-key",
        "project_name": "user-management-service",
        "never_expires": False
    },
    headers={"secret-key": "your-secret-key"}
)

api_key = response.text
print(f"New API key: {api_key}")
```

### Inserting Existing API Keys

```python
import requests

# Insert an existing API key
response = requests.get(
    "http://localhost:8000/auth/insert",
    params={
        "api-key": "existing-uuid-key",
        "name": "legacy-service-key",
        "project_name": "legacy-system",
        "expiration-date": "2025-12-31T23:59:59"
    },
    headers={"secret-key": "your-secret-key"}
)
```

## Elasticsearch Index Structure

The Elasticsearch backend creates an index named `fastapi_simple_security` with the following document structure:

```json
{
  "api_key": "uuid-string",
  "is_active": true,
  "never_expire": false,
  "expiration_date": "2025-12-31T23:59:59",
  "latest_query_date": "2025-12-01T10:30:00",
  "total_queries": 42,
  "name": "service-key-name",
  "project_name": "project-name"
}
```

### Field Descriptions

- **`api_key`**: The unique API key (UUID format)
- **`is_active`**: Whether the key is active or revoked
- **`never_expire`**: If true, the key will never expire
- **`expiration_date`**: ISO 8601 formatted expiration date
- **`latest_query_date`**: Last time the key was used
- **`total_queries`**: Number of times the key has been used
- **`name`**: Short name for the key (e.g., "user-service-key")
- **`project_name`**: Name of the project using this key (e.g., "user-management-service")

## Migration from SQLite to Elasticsearch

To migrate existing API keys from SQLite to Elasticsearch:

1. Export keys from SQLite database
2. Change `FASTAPI_SIMPLE_SECURITY_BACKEND` to `elasticsearch`
3. Use the `/auth/insert` endpoint to import each key with its metadata

## Benefits of Elasticsearch Backend

- **Scalability**: Better handling of large numbers of API keys
- **Distributed**: Can be deployed across multiple nodes
- **Search capabilities**: Advanced querying and filtering of API keys
- **Metadata**: Support for project names and additional context
- **High availability**: Built-in replication and failover

## Backward Compatibility

The SQLite backend remains the default and continues to work without any code changes. All existing functionality is preserved when using SQLite.
