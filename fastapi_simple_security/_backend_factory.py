"""Factory for selecting the appropriate storage backend."""

import os
import warnings
from fastapi_simple_security._storage_backend import StorageBackend


def get_storage_backend() -> StorageBackend:
    """
    Returns the configured storage backend.

    Always uses SQLite as the storage backend. If FASTAPI_ES_APIKEY_STORAGE_INDEX
    is provided, API keys will be loaded from Elasticsearch into SQLite at startup.

    Environment variables:
        FASTAPI_ES_APIKEY_STORAGE_INDEX: Elasticsearch index to load API keys from (optional)
        FASTAPI_SIMPLE_SECURITY_BACKEND: Deprecated - SQLite is always used

    Returns:
        An instance of SQLiteAccess storage backend
    """
    from fastapi_simple_security._sqlite_access import SQLiteAccess

    # Warn if deprecated BACKEND variable is set to elasticsearch
    backend_type = os.environ.get("FASTAPI_SIMPLE_SECURITY_BACKEND", "sqlite").lower()
    if backend_type == "elasticsearch":
        warnings.warn(
            "FASTAPI_SIMPLE_SECURITY_BACKEND=elasticsearch is deprecated. "
            "SQLite is now always used as the storage backend. "
            "Use FASTAPI_ES_APIKEY_STORAGE_INDEX to load keys from Elasticsearch.",
            DeprecationWarning,
            stacklevel=2,
        )

    warnings.warn(
        "Using SQLite backend for API key storage",
        UserWarning,
    )
    return SQLiteAccess()


# Create a single instance to be used throughout the application
storage_backend = get_storage_backend()
