"""Interaction with Elasticsearch."""

import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from cachetools import TTLCache
from fastapi import HTTPException
from starlette.status import HTTP_404_NOT_FOUND, HTTP_422_UNPROCESSABLE_ENTITY

from fastapi_simple_security._storage_backend import StorageBackend

try:
    from elasticsearch import Elasticsearch
except ImportError:
    Elasticsearch = None


class ElasticsearchAccess(StorageBackend):
    """Class handling Elasticsearch connection and operations"""

    def __init__(self):
        if Elasticsearch is None:
            raise ImportError(
                "elasticsearch package is required for Elasticsearch backend. "
                "Install it with: pip install elasticsearch"
            )

        # Get Elasticsearch connection details from environment
        es_hosts = os.environ.get(
            "FASTAPI_SIMPLE_SECURITY_ES_HOSTS", "http://localhost:9200"
        )
        es_user = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_USER")
        es_password = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_PASSWORD")
        es_api_key = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_API_KEY")

        # Initialize Elasticsearch client
        if es_api_key:
            self.es = Elasticsearch(es_hosts.split(","), api_key=es_api_key)
        elif es_user and es_password:
            self.es = Elasticsearch(
                es_hosts.split(","), basic_auth=(es_user, es_password)
            )
        else:
            self.es = Elasticsearch(es_hosts.split(","))

        self.index_name = "fastapi_simple_security"

        try:
            self.expiration_limit = int(
                os.environ.get("FAST_API_SIMPLE_SECURITY_AUTOMATIC_EXPIRATION", "15")
            )
        except ValueError:
            self.expiration_limit = 15

        # Cache configuration
        try:
            cache_ttl = int(os.environ.get("FASTAPI_SIMPLE_SECURITY_CACHE_TTL", "3600"))
        except ValueError:
            cache_ttl = 3600  # Default 1 hour

        try:
            cache_maxsize = int(
                os.environ.get("FASTAPI_SIMPLE_SECURITY_CACHE_MAXSIZE", "10000")
            )
        except ValueError:
            cache_maxsize = 10000

        # TTLCache: automatically handles expiration and LRU eviction
        self._cache: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._cache_lock = threading.Lock()

        # Create index if it doesn't exist
        self._init_index()

        try:
            api_key_file = os.environ["FASTAPI_SIMPLE_SECURITY_API_KEY_FILE"]
        except KeyError:
            api_key_file = None

        if api_key_file:
            self.handle_api_key_file(api_key_file)

    def handle_api_key_file(self, filepath: str) -> None:
        """Handle API key file.

        Args:
            filepath (str): Path to the API key file.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"API Key file {filepath} does not exist")
        keys = []
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    continue
                if line:
                    try:
                        name, api_key, expiration_date = line.split(";")
                    except ValueError:
                        raise ValueError(f'API Key file line "{line}" is invalid')
                    else:
                        if api_key and name:
                            keys.append((api_key, name, expiration_date))

        for api_key, name, expiration_date in keys:
            print(self.insert_key(api_key, name, expiration_date))

    def _init_index(self):
        """Initialize the Elasticsearch index with proper mappings"""
        if not self.es.indices.exists(index=self.index_name):
            mapping = {
                "mappings": {
                    "properties": {
                        "api_key": {"type": "keyword"},
                        "is_active": {"type": "boolean"},
                        "never_expire": {"type": "boolean"},
                        "expiration_date": {"type": "date"},
                        "latest_query_date": {"type": "date"},
                        "total_queries": {"type": "integer"},
                        "name": {"type": "keyword"},
                        "project_name": {"type": "keyword"},
                    }
                }
            }
            self.es.indices.create(index=self.index_name, body=mapping)

    def create_key(
        self, name: str, never_expire: bool, project_name: Optional[str] = None
    ) -> str:
        """
        Creates a new API key

        Args:
            name: short name for the key
            never_expire: if True, the key will never expire
            project_name: name of the project using this key

        Returns:
            the newly created API key
        """
        api_key = str(uuid.uuid4())

        doc = {
            "api_key": api_key,
            "is_active": True,
            "never_expire": never_expire,
            "expiration_date": (
                datetime.utcnow() + timedelta(days=self.expiration_limit)
            ).isoformat(timespec="seconds"),
            "latest_query_date": None,
            "total_queries": 0,
            "name": name,
            "project_name": project_name,
        }

        self.es.index(index=self.index_name, id=api_key, document=doc)
        self.es.indices.refresh(index=self.index_name)

        return api_key

    def insert_key(
        self,
        api_key: str,
        name: str,
        expiration_date: str,
        project_name: Optional[str] = None,
    ) -> str | None:
        """
        Inserts a known API key

        Args:
            api_key: the API key to insert
            name: short name for the key
            expiration_date: the expiration date in ISO format
            project_name: name of the project using this key

        Returns:
            a message describing the insertion result
        """
        # Check if key already exists
        try:
            existing = self.es.get(index=self.index_name, id=api_key)
            if existing["found"]:
                return self.renew_key(api_key, expiration_date)
        except Exception:
            pass  # Key doesn't exist, proceed with insertion

        # Parse expiration date
        if not expiration_date:
            parsed_expiration_date = (
                datetime.utcnow() + timedelta(days=self.expiration_limit)
            ).isoformat(timespec="seconds")
        else:
            try:
                parsed_expiration_date = datetime.fromisoformat(
                    expiration_date
                ).isoformat(timespec="seconds")
            except ValueError as exc:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The expiration date could not be parsed. Please use ISO 8601.",
                ) from exc

        doc = {
            "api_key": api_key,
            "is_active": True,
            "never_expire": False,
            "expiration_date": parsed_expiration_date,
            "latest_query_date": None,
            "total_queries": 0,
            "name": name,
            "project_name": project_name,
        }

        self.es.index(index=self.index_name, id=api_key, document=doc)
        self.es.indices.refresh(index=self.index_name)

        return f"Key {name} inserted with expiration date {parsed_expiration_date}"

    def renew_key(self, api_key: str, new_expiration_date: str) -> Optional[str]:
        """
        Renews an API key

        Args:
            api_key: the API key to renew
            new_expiration_date: the new expiration date in ISO format

        Returns:
            a message describing the renewal result
        """
        try:
            result = self.es.get(index=self.index_name, id=api_key)
            if not result["found"]:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND, detail="API key not found"
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail="API key not found"
            )

        doc = result["_source"]
        response_lines = []

        # Previously revoked key
        if not doc.get("is_active", True):
            response_lines.append("This API key was revoked and has been reactivated.")

        # Parse expiration date
        if not new_expiration_date:
            parsed_expiration_date = (
                datetime.utcnow() + timedelta(days=self.expiration_limit)
            ).isoformat(timespec="seconds")
        else:
            try:
                parsed_expiration_date = datetime.fromisoformat(
                    new_expiration_date
                ).isoformat(timespec="seconds")
            except ValueError as exc:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The expiration date could not be parsed. Please use ISO 8601.",
                ) from exc

        # Update the document
        self.es.update(
            index=self.index_name,
            id=api_key,
            doc={"expiration_date": parsed_expiration_date, "is_active": True},
        )
        self.es.indices.refresh(index=self.index_name)
        # Invalidate cache for this key since status changed
        self.invalidate_cache(api_key)

        response_lines.append(
            f"The new expiration date for the API key is {parsed_expiration_date}"
        )

        return " ".join(response_lines)

    def revoke_key(self, api_key: str):
        """
        Revokes an API key

        Args:
            api_key: the API key to revoke
        """
        self.es.update(
            index=self.index_name,
            id=api_key,
            doc={"is_active": False},
        )
        self.es.indices.refresh(index=self.index_name)
        # Invalidate cache for this key
        self.invalidate_cache(api_key)

    def check_key(self, api_key: str) -> bool:
        """
        Checks if an API key is valid (with TTL caching)

        Args:
            api_key: the API key to validate

        Returns:
            True if the key is valid, False otherwise
        """
        # Check cache first (TTLCache handles expiration automatically)
        with self._cache_lock:
            cached_result = self._cache.get(api_key)

        if cached_result is not None:
            # Cache hit
            if cached_result:
                # Update usage in background for valid keys
                threading.Thread(
                    target=self._update_usage_from_cache,
                    args=(api_key,),
                ).start()
            return cached_result

        # Cache miss - check Elasticsearch
        try:
            result = self.es.get(index=self.index_name, id=api_key)
            if not result["found"]:
                self._update_cache(api_key, False)
                return False

            doc = result["_source"]

            # Check if key is active
            if not doc.get("is_active", False):
                self._update_cache(api_key, False)
                return False

            # Check if key is expired
            if not doc.get("never_expire", False):
                expiration_date = datetime.fromisoformat(doc["expiration_date"])
                if expiration_date < datetime.utcnow():
                    self._update_cache(api_key, False)
                    return False

            # Key is valid, update cache and usage
            self._update_cache(api_key, True)
            threading.Thread(
                target=self._update_usage,
                args=(api_key, doc.get("total_queries", 0)),
            ).start()

            return True

        except Exception:
            self._update_cache(api_key, False)
            return False

    def _update_cache(self, api_key: str, is_valid: bool):
        """
        Updates the cache with validation result

        Args:
            api_key: the API key
            is_valid: whether the key is valid
        """
        with self._cache_lock:
            self._cache[api_key] = is_valid

    def _update_usage(self, api_key: str, usage_count: int):
        """
        Updates usage statistics for an API key

        Args:
            api_key: the API key to update
            usage_count: current usage count
        """
        try:
            self.es.update(
                index=self.index_name,
                id=api_key,
                doc={
                    "total_queries": usage_count + 1,
                    "latest_query_date": datetime.utcnow().isoformat(
                        timespec="seconds"
                    ),
                },
            )
        except Exception:
            pass  # Silently fail on usage update errors

    def _update_usage_from_cache(self, api_key: str):
        """
        Updates usage statistics for a cached key (fetches current count first)

        Args:
            api_key: the API key to update
        """
        try:
            result = self.es.get(index=self.index_name, id=api_key)
            if result["found"]:
                doc = result["_source"]
                self._update_usage(api_key, doc.get("total_queries", 0))
        except Exception:
            pass  # Silently fail on usage update errors

    def invalidate_cache(self, api_key: Optional[str] = None):
        """
        Invalidates the cache for a specific key or all keys

        Args:
            api_key: the API key to invalidate, or None to clear entire cache
        """
        with self._cache_lock:
            if api_key:
                self._cache.pop(api_key, None)
            else:
                self._cache.clear()

    def get_usage_stats(
        self,
    ) -> List[Tuple[str, bool, bool, str, str, int, Optional[str], Optional[str]]]:
        """
        Returns usage stats for all API keys

        Returns:
            a list of tuples with values being api_key, is_active, never_expire, expiration_date,
            latest_query_date, total_queries, name, project_name
        """
        # Query all documents
        result = self.es.search(
            index=self.index_name,
            body={
                "query": {"match_all": {}},
                "size": 10000,
                "sort": [{"latest_query_date": {"order": "desc", "missing": "_last"}}],
            },
        )

        stats = []
        for hit in result["hits"]["hits"]:
            doc = hit["_source"]
            stats.append(
                (
                    doc.get("api_key", ""),
                    doc.get("is_active", False),
                    doc.get("never_expire", False),
                    doc.get("expiration_date", ""),
                    doc.get("latest_query_date", ""),
                    doc.get("total_queries", 0),
                    doc.get("name"),
                    doc.get("project_name"),
                )
            )

        return stats
