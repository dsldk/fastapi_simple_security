"""Factory for selecting the appropriate storage backend."""

import os
import warnings
from fastapi_simple_security._storage_backend import StorageBackend


def get_storage_backend() -> StorageBackend:
    """
    Returns the configured storage backend based on environment variable.

    Environment variables:
        FASTAPI_SIMPLE_SECURITY_BACKEND: 'sqlite' (default) or 'elasticsearch'

    Returns:
        An instance of the configured storage backend
    """
    backend_type = os.environ.get("FASTAPI_SIMPLE_SECURITY_BACKEND", "sqlite").lower()

    if backend_type == "elasticsearch":
        from fastapi_simple_security._elasticsearch_access import ElasticsearchAccess

        warnings.warn(
            "Using Elasticsearch backend for API key storage",
        )
        return ElasticsearchAccess()
    else:
        from fastapi_simple_security._sqlite_access import SQLiteAccess

        warnings.warn(
            "Using SQLite backend for API key storage",
            UserWarning,
        )
        return SQLiteAccess()


# Create a single instance to be used throughout the application
storage_backend = get_storage_backend()
