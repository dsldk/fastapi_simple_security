# Implementation Summary: Storage Backend Architecture

## Overview

This project uses SQLite as the storage backend for API keys, with support for loading API keys from Elasticsearch at startup. The Elasticsearch backend implementation is deprecated but kept for backward compatibility.

## Current Architecture

### Storage Backend
- **SQLite**: Always used for storing and validating API keys
- **Elasticsearch**: Optional source for loading API keys at startup (via `FASTAPI_ES_APIKEY_STORAGE_INDEX`)

## Files

### 1. `_storage_backend.py`
- Abstract base class defining the interface for all storage backends
- Methods: `check_key`, `create_key`, `revoke_key`, `renew_key`, `insert_key`, `get_usage_stats`, `invalidate_cache`

### 2. `_sqlite_access.py`
- SQLite implementation of the storage backend (primary backend)
- Supports loading API keys from:
  - File (via `FASTAPI_SIMPLE_SECURITY_API_KEY_FILE`)
  - Elasticsearch index (via `FASTAPI_ES_APIKEY_STORAGE_INDEX`)
- Includes TTL-based caching for performance
- Handles API key validation, creation, renewal, revocation, and usage tracking

### 3. `_elasticsearch_access.py` (Deprecated)
- **DEPRECATED**: No longer used as a storage backend
- Kept for backward compatibility and reference
- Use `FASTAPI_ES_APIKEY_STORAGE_INDEX` in SQLiteAccess to load keys from Elasticsearch instead

### 4. `_backend_factory.py`
- Factory function that always returns SQLiteAccess
- Warns if deprecated `FASTAPI_SIMPLE_SECURITY_BACKEND=elasticsearch` is set
- Creates a singleton instance used throughout the application

### 5. `ELASTICSEARCH.md`
- Documentation for loading API keys from Elasticsearch into SQLite
- Configuration examples
- Expected document structure
- Migration guide from deprecated Elasticsearch backend

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
