# Implementation Summary: Elasticsearch Backend Support

## Overview

Added support for using Elasticsearch as an alternative backend for storing API keys, while maintaining full backward compatibility with the existing SQLite backend.

## Files Created

### 1. `_storage_backend.py`
- Abstract base class defining the interface for all storage backends
- Methods: `check_key`, `create_key`, `revoke_key`, `renew_key`, `insert_key`, `get_usage_stats`

### 2. `_elasticsearch_access.py`
- Elasticsearch implementation of the storage backend
- Uses index name: `fastapi_simple_security`
- Supports connection via:
  - Basic authentication (username/password)
  - API key authentication
  - Unauthenticated (for local development)
- Handles API key validation, creation, renewal, revocation, and usage tracking

### 3. `_backend_factory.py`
- Factory function to select the appropriate backend based on environment variable
- Creates a singleton instance used throughout the application

### 4. `ELASTICSEARCH.md`
- Comprehensive documentation for Elasticsearch backend usage
- Configuration examples
- Migration guide
- API usage examples

## Files Modified

### 1. `_sqlite_access.py`
- Now inherits from `StorageBackend` abstract base class
- Updated method signatures to support `project_name` parameter
- Modified `get_usage_stats()` to return `project_name` (always NULL for SQLite)

### 2. `endpoints.py`
- Changed from importing `sqlite_access` to `storage_backend`
- Updated all endpoint functions to use `storage_backend` instead of `sqlite_access`
- Added `project_name` parameter to `/new` and `/insert` endpoints
- Updated `UsageLog` model to include `project_name` field
- Modified logs endpoint to handle the additional field

### 3. `security_api_key.py`
- Changed from importing `sqlite_access` to `storage_backend`
- Updated API key validation to use `storage_backend`

### 4. `requirements.txt`
- Added `elasticsearch>=8.0.0` as an optional dependency

## Environment Variables

### New Variables

- **`FASTAPI_SIMPLE_SECURITY_BACKEND`**: Select backend (`sqlite` or `elasticsearch`)
- **`FASTAPI_SIMPLE_SECURITY_ES_HOSTS`**: Elasticsearch connection URLs
- **`FASTAPI_SIMPLE_SECURITY_ES_USER`**: Elasticsearch username
- **`FASTAPI_SIMPLE_SECURITY_ES_PASSWORD`**: Elasticsearch password
- **`FASTAPI_SIMPLE_SECURITY_ES_API_KEY`**: Elasticsearch API key

### Existing Variables (Still Supported)

- `FASTAPI_SIMPLE_SECURITY_DB_LOCATION`: SQLite database location
- `FAST_API_SIMPLE_SECURITY_AUTOMATIC_EXPIRATION`: Default expiration days

## New API Parameters

### `/new` Endpoint
- Added `project_name` (optional): Name of the project using this API key

### `/insert` Endpoint
- Added `project_name` (optional): Name of the project using this API key

## Elasticsearch Index Structure

```json
{
  "api_key": "uuid",
  "is_active": true/false,
  "never_expire": true/false,
  "expiration_date": "ISO 8601 date",
  "latest_query_date": "ISO 8601 date",
  "total_queries": 0,
  "name": "short-key-name",
  "project_name": "project-name"
}
```

## Key Features

1. **Pluggable Architecture**: Easy to add more storage backends in the future
2. **Backward Compatible**: Existing SQLite functionality unchanged
3. **Optional Dependency**: Elasticsearch package only needed if using that backend
4. **Metadata Support**: Project names and key names for better organization
5. **Thread-Safe Usage Tracking**: Background updates for usage statistics
6. **Automatic Index Creation**: Elasticsearch index created with proper mappings

## Usage Example

```python
import os

# Use Elasticsearch backend
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "http://localhost:9200"

from fastapi import FastAPI, Depends
from fastapi_simple_security import api_key_router, api_key_security

app = FastAPI()
app.include_router(api_key_router, prefix="/auth")

@app.get("/secure")
async def secure_endpoint(api_key: str = Depends(api_key_security)):
    return {"status": "authenticated"}
```

## Testing

To test the implementation:

1. **SQLite (default)**:
   ```bash
   # No environment variables needed
   python app/main.py
   ```

2. **Elasticsearch**:
   ```bash
   export FASTAPI_SIMPLE_SECURITY_BACKEND=elasticsearch
   export FASTAPI_SIMPLE_SECURITY_ES_HOSTS=http://localhost:9200
   python app/main.py
   ```

## Notes

- The implementation maintains the exact same API for both backends
- SQLite backend does not store `project_name` but returns NULL for compatibility
- Elasticsearch provides better scalability for high-volume applications
- All existing tests should continue to work with SQLite backend
