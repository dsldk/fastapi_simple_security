"""Interaction with SQLite database."""

import os
import sqlite3
import threading
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from cachetools import TTLCache
from fastapi import HTTPException
from starlette.status import HTTP_404_NOT_FOUND, HTTP_422_UNPROCESSABLE_ENTITY

from fastapi_simple_security._storage_backend import StorageBackend

try:
    from elasticsearch import Elasticsearch
except ImportError:
    Elasticsearch = None


class SQLiteAccess(StorageBackend):
    """Class handling SQLite connection and writes"""

    # TODO This should not be a class, a fully functional approach is better

    @staticmethod
    def _sqlite_date_to_es_date(sqlite_date: str) -> str:
        """Convert SQLite date format (ISO 8601 with seconds+Z) to ES format (YYYY-MM-DD).

        Args:
            sqlite_date: Date in format 'YYYY-MM-DDTHH:MM:SSZ'

        Returns:
            Date in format 'YYYY-MM-DD'
        """
        if not sqlite_date:
            return ""
        try:
            dt = datetime.fromisoformat(sqlite_date.rstrip("Z"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return ""

    @staticmethod
    def _es_date_to_sqlite_date(es_date: str) -> str:
        """Convert ES date format (YYYY-MM-DD) to SQLite format (ISO 8601 with seconds+Z).

        Args:
            es_date: Date in format 'YYYY-MM-DD' or ISO 8601

        Returns:
            Date in format 'YYYY-MM-DDTHH:MM:SSZ'
        """
        if not es_date:
            return ""
        try:
            # Try parsing as simple date first
            if len(es_date) == 10 and es_date.count("-") == 2:
                dt = datetime.strptime(es_date, "%Y-%m-%d")
            else:
                # Fall back to ISO format parsing
                dt = datetime.fromisoformat(es_date.rstrip("Z"))
            return dt.isoformat(timespec="seconds") + "Z"
        except (ValueError, AttributeError):
            return ""

    @staticmethod
    def _parse_expiration_date(expiration_date: str, expiration_limit: int) -> str:
        """Parse and normalize an expiration date to SQLite format.

        Args:
            expiration_date: Input date string (can be empty, YYYY-MM-DD, or ISO 8601)
            expiration_limit: Number of days to add if no date provided

        Returns:
            Date in SQLite format 'YYYY-MM-DDTHH:MM:SSZ'

        Raises:
            HTTPException: If date cannot be parsed
        """
        if not expiration_date:
            return (datetime.utcnow() + timedelta(days=expiration_limit)).isoformat(
                timespec="seconds"
            ) + "Z"

        try:
            # Try simple date format first
            if len(expiration_date) == 10 and expiration_date.count("-") == 2:
                dt = datetime.strptime(expiration_date, "%Y-%m-%d")
            else:
                dt = datetime.fromisoformat(expiration_date.rstrip("Z"))
            return dt.isoformat(timespec="seconds") + "Z"
        except ValueError as exc:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The expiration date could not be parsed. Please use ISO 8601 or YYYY-MM-DD format.",
            ) from exc

    def __init__(self):
        try:
            self.db_location = os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"]
        except KeyError:
            self.db_location = "sqlite.db"

        try:
            self.expiration_limit = int(
                os.environ["FAST_API_SIMPLE_SECURITY_AUTOMATIC_EXPIRATION"]
            )
        except KeyError:
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

        # ThreadPoolExecutor for bounded ES sync operations (max 5 concurrent syncs)
        self._es_sync_executor = ThreadPoolExecutor(
            max_workers=5, thread_name_prefix="es_sync"
        )

        # Set es_index early to avoid race conditions with background threads
        try:
            self.es_index = os.environ["FASTAPI_ES_APIKEY_STORAGE_INDEX"]
        except KeyError:
            self.es_index = None

        # Deferred ES loading flag - load on first check_key call
        self._es_keys_loaded = False
        self._es_loading_lock = threading.Lock()

        self.init_db()

        # Store API key file path for deferred loading
        try:
            self.api_key_file = os.environ["FASTAPI_SIMPLE_SECURITY_API_KEY_FILE"]
        except KeyError:
            self.api_key_file = None

        # Both API key file and ES loading are now deferred to first check_key call
        # to avoid connection issues during initialization (especially in AWS setups)

    def init_db(self):
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()
            # Create database
            c.execute(
                """
        CREATE TABLE IF NOT EXISTS fastapi_simple_security (
            api_key TEXT PRIMARY KEY,
            is_active INTEGER,
            never_expire INTEGER,
            expiration_date TEXT,
            latest_query_date TEXT,
            total_queries INTEGER)
        """
            )
            connection.commit()
            # Migration: Add api key name
            try:
                c.execute("ALTER TABLE fastapi_simple_security ADD COLUMN name TEXT")
                connection.commit()
            except sqlite3.OperationalError:
                pass  # Column already exist

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

    def load_keys_from_elasticsearch(self, index_name: str) -> None:
        """Load API keys from Elasticsearch index into SQLite with retry logic.

        Args:
            index_name (str): Name of the Elasticsearch index to load keys from.
        """
        if Elasticsearch is None:
            raise ImportError(
                "elasticsearch package is required to load keys from Elasticsearch. "
                "Install it with: pip install elasticsearch"
            )

        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            es = None
            try:
                es = self._get_elasticsearch_client()
                if es is None:
                    warnings.warn(
                        f"Failed to connect to Elasticsearch (attempt {attempt + 1}/{max_retries}). "
                        "Skipping key loading.",
                        UserWarning,
                    )
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        continue
                    return

                # Verify connection
                if not es.ping():
                    raise ConnectionError("Elasticsearch ping failed")

                # Ensure index exists with proper mappings
                self._ensure_es_index_exists(es, index_name)

                # Query all documents from the index
                result = es.search(
                    index=index_name,
                    body={
                        "query": {"match_all": {}},
                        "size": 10000,
                    },
                )

                keys_loaded = 0
                loaded_keys = []
                for hit in result["hits"]["hits"]:
                    doc = hit["_source"]
                    api_key = doc.get("api_key")
                    name = doc.get("name", "")
                    es_date = doc.get("expiration_date", "")
                    # Convert ES date (YYYY-MM-DD) to SQLite format
                    expiration_date = (
                        self._es_date_to_sqlite_date(es_date) if es_date else ""
                    )

                    if api_key:
                        try:
                            self.insert_key(api_key, name, expiration_date)
                            keys_loaded += 1
                            loaded_keys.append(api_key)
                        except Exception as e:
                            warnings.warn(
                                f"Failed to load API key '{name}' from Elasticsearch: {e}",
                                UserWarning,
                            )

                warnings.warn(
                    f"Loaded {keys_loaded} API keys from Elasticsearch index '{index_name}'",
                    UserWarning,
                )

                # Warm cache with loaded keys for better cold-start performance
                self._warm_cache(loaded_keys)

                # Success - break retry loop
                break

            except Exception as e:
                warnings.warn(
                    f"Error loading API keys from Elasticsearch (attempt {attempt + 1}/{max_retries}): {e}",
                    UserWarning,
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    warnings.warn(
                        "Failed to load API keys from Elasticsearch after all retries. "
                        "Application will start with empty/existing database.",
                        UserWarning,
                    )
            finally:
                # Always close ES connection
                if es is not None:
                    try:
                        es.close()
                    except Exception:
                        pass  # Ignore errors during cleanup

    def _get_elasticsearch_client(self):
        """Get an Elasticsearch client with timeouts and proper configuration.

        Returns:
            Elasticsearch client or None if not configured/available
        """
        if Elasticsearch is None:
            return None

        try:
            es_hosts = os.environ.get(
                "FASTAPI_SIMPLE_SECURITY_ES_HOSTS", "http://localhost:9200"
            )
            es_user = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_USER")
            es_password = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_PASSWORD")
            es_api_key = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_API_KEY")

            # Connection timeout configuration for AWS/Docker environments
            connection_params = {
                "request_timeout": 30,  # 30 seconds for requests
                "max_retries": 2,
                "retry_on_timeout": True,
            }

            if es_api_key:
                return Elasticsearch(
                    es_hosts.split(","), api_key=es_api_key, **connection_params
                )
            elif es_user and es_password:
                # Build authenticated host URLs
                auth_hosts = []
                for host in es_hosts.split(","):
                    if "://" in host:
                        protocol, rest = host.split("://", 1)
                    else:
                        protocol = "http"
                        rest = host
                    auth_hosts.append(f"{protocol}://{es_user}:{es_password}@{rest}")
                return Elasticsearch(
                    auth_hosts, verify_certs=False, **connection_params
                )
            else:
                return Elasticsearch(es_hosts.split(","), **connection_params)
        except Exception as e:
            warnings.warn(
                f"Failed to create Elasticsearch client: {e}",
                UserWarning,
            )
            return None

    def _ensure_es_index_exists(self, es, index_name: str) -> None:
        """Ensure Elasticsearch index exists with proper mappings.

        Args:
            es: Elasticsearch client
            index_name: Name of the index to create
        """
        if not es.indices.exists(index=index_name):
            mapping = {
                "mappings": {
                    "properties": {
                        "name": {"type": "keyword"},
                        "api_key": {"type": "keyword"},
                        "expiration_date": {
                            "type": "date",
                            "format": "strict_date||epoch_millis",
                        },
                        "is_active": {"type": "boolean"},
                    }
                }
            }
            es.indices.create(index=index_name, body=mapping)

    def _sync_to_elasticsearch(
        self, api_key: str, name: str, expiration_date: str, is_active: bool = True
    ):
        """Sync an API key to Elasticsearch using bounded thread pool.

        Args:
            api_key: The API key
            name: The key name
            expiration_date: SQLite format expiration date (YYYY-MM-DDTHH:MM:SSZ)
            is_active: Whether the key is active (for revocation)
        """

        def _sync():
            if self.es_index is None:
                return

            es = None
            try:
                es = self._get_elasticsearch_client()
                if es is None:
                    return

                # Verify connection before operations
                if not es.ping():
                    warnings.warn(
                        "Elasticsearch connection not available for sync",
                        UserWarning,
                    )
                    return

                # Ensure index exists with proper mappings
                self._ensure_es_index_exists(es, self.es_index)

                # Convert SQLite date to simple ES date format (YYYY-MM-DD)
                es_date = self._sqlite_date_to_es_date(expiration_date)

                # Index or update the document
                doc = {
                    "name": name,
                    "api_key": api_key,
                    "expiration_date": es_date,
                    "is_active": is_active,
                }
                es.index(index=self.es_index, id=api_key, document=doc)
                es.indices.refresh(index=self.es_index)
            except Exception as e:
                warnings.warn(
                    f"Failed to sync API key to Elasticsearch: {e}",
                    UserWarning,
                )
            finally:
                # Always close connection
                if es is not None:
                    try:
                        es.close()
                    except Exception:
                        pass  # Ignore cleanup errors

        # Use bounded thread pool instead of unbounded thread creation
        self._es_sync_executor.submit(_sync)

    def create_key(self, name, never_expire, project_name: Optional[str] = None) -> str:
        api_key = str(uuid.uuid4())
        expiration_date = (
            datetime.utcnow() + timedelta(days=self.expiration_limit)
        ).isoformat(timespec="seconds") + "Z"

        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()
            c.execute(
                """
                INSERT INTO fastapi_simple_security
                (api_key, is_active, never_expire, expiration_date, \
                    latest_query_date, total_queries, name)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    api_key,
                    1,
                    1 if never_expire else 0,
                    expiration_date,
                    None,
                    0,
                    name,
                ),
            )
            connection.commit()

        # Sync to Elasticsearch if configured
        self._sync_to_elasticsearch(api_key, name, expiration_date, is_active=True)

        return api_key

    def insert_key(
        self,
        api_key: str,
        name: str,
        expiration_date: str,
        project_name: Optional[str] = None,
    ) -> str | None:
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()
            # We run the query like check_key but will use the response differently
            c.execute(
                """
            SELECT is_active, total_queries, expiration_date, never_expire
            FROM fastapi_simple_security
            WHERE api_key = ?""",
                (api_key,),
            )

            response = c.fetchone()
            if response:
                return self.renew_key(api_key, expiration_date)

            # Parse and normalize the expiration date
            parsed_expiration_date = self._parse_expiration_date(
                expiration_date, self.expiration_limit
            )

            c.execute(
                """
                INSERT INTO fastapi_simple_security
                (api_key, is_active, never_expire, expiration_date, \
                    latest_query_date, total_queries, name)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    api_key,
                    1,
                    0,
                    parsed_expiration_date,
                    None,
                    0,
                    name,
                ),
            )
            connection.commit()

            # Sync to Elasticsearch if configured
            self._sync_to_elasticsearch(
                api_key, name, parsed_expiration_date, is_active=True
            )

            return f"Key {name} inserted with expiration date {parsed_expiration_date}"

    def renew_key(self, api_key: str, new_expiration_date: str) -> Optional[str]:
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            # We run the query like check_key but will use the response differently
            c.execute(
                """
            SELECT is_active, total_queries, expiration_date, never_expire
            FROM fastapi_simple_security
            WHERE api_key = ?""",
                (api_key,),
            )

            response = c.fetchone()

            # API key not found
            if not response:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND, detail="API key not found"
                )

            response_lines = []

            # Previously revoked key. Issue a text warning and reactivate it.
            if response[0] == 0:
                response_lines.append(
                    "This API key was revoked and has been reactivated."
                )

            # Parse and normalize the expiration date
            parsed_expiration_date = self._parse_expiration_date(
                new_expiration_date, self.expiration_limit
            )

            c.execute(
                """
            UPDATE fastapi_simple_security
            SET expiration_date = ?, is_active = 1
            WHERE api_key = ?
            """,
                (
                    parsed_expiration_date,
                    api_key,
                ),
            )

            connection.commit()

            # Get the key name for Elasticsearch sync
            c.execute(
                "SELECT name FROM fastapi_simple_security WHERE api_key = ?",
                (api_key,),
            )
            key_name = c.fetchone()
            name = key_name[0] if key_name else ""

        # Invalidate cache for this key since status changed
        self.invalidate_cache(api_key)

        # Sync to Elasticsearch if configured
        self._sync_to_elasticsearch(
            api_key, name, parsed_expiration_date, is_active=True
        )

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
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            # Get current key info for Elasticsearch sync
            c.execute(
                "SELECT name, expiration_date FROM fastapi_simple_security WHERE api_key = ?",
                (api_key,),
            )
            key_info = c.fetchone()
            name = key_info[0] if key_info else ""
            expiration_date = key_info[1] if key_info else ""

            c.execute(
                """
            UPDATE fastapi_simple_security
            SET is_active = 0
            WHERE api_key = ?
            """,
                (api_key,),
            )

            connection.commit()

        # Invalidate cache for this key
        self.invalidate_cache(api_key)

        # Sync revocation to Elasticsearch if configured
        if name and expiration_date:
            self._sync_to_elasticsearch(api_key, name, expiration_date, is_active=False)

    def check_key(self, api_key: str) -> bool:
        """
        Checks if an API key is valid (with TTL caching)

        Args:
             api_key: the API key to validate
        """
        # Lazy load API key file and ES keys on first check_key call
        if not self._es_keys_loaded:
            with self._es_loading_lock:
                # Double-check pattern to avoid race conditions
                if not self._es_keys_loaded:
                    # Load API key file first (if configured)
                    if self.api_key_file:
                        self.handle_api_key_file(self.api_key_file)

                    # Then load from Elasticsearch (if configured)
                    if self.es_index:
                        self.load_keys_from_elasticsearch(self.es_index)

                    self._es_keys_loaded = True

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

        # Cache miss - check database
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            c.execute(
                """
            SELECT is_active, total_queries, expiration_date, never_expire
            FROM fastapi_simple_security
            WHERE api_key = ?""",
                (api_key,),
            )

            response = c.fetchone()

            if (
                # Cannot fetch a row
                not response
                # Inactive
                or response[0] != 1
                # Expired key
                or (
                    (not response[3])
                    and (
                        datetime.fromisoformat(response[2].replace("Z", "+00:00"))
                        < datetime.now(timezone.utc)
                    )
                )
            ):
                # The key is not valid
                self._update_cache(api_key, False)
                return False
            else:
                # The key is valid
                self._update_cache(api_key, True)

                # We run the logging in a separate thread as writing takes some time
                threading.Thread(
                    target=self._update_usage,
                    args=(
                        api_key,
                        response[1],
                    ),
                ).start()

                # We return directly
                return True

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
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            # If we get there, this means it's an active API key that's in the database.\
            #   We update the table.
            c.execute(
                """
            UPDATE fastapi_simple_security
            SET total_queries = ?, latest_query_date = ?
            WHERE api_key = ?
            """,
                (
                    usage_count + 1,
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    api_key,
                ),
            )

            connection.commit()

    def _update_usage_from_cache(self, api_key: str):
        """
        Updates usage statistics for a cached key (fetches current count first)

        Args:
            api_key: the API key to update
        """
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            c.execute(
                """
            SELECT total_queries
            FROM fastapi_simple_security
            WHERE api_key = ?""",
                (api_key,),
            )

            response = c.fetchone()
            if response:
                self._update_usage(api_key, response[0])

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

    def _warm_cache(self, api_keys: List[str]):
        """Warm the cache with valid API keys for better cold-start performance.

        Args:
            api_keys: List of API keys to warm the cache with
        """
        if not api_keys:
            return

        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            warmed_count = 0
            for api_key in api_keys:
                try:
                    c.execute(
                        """
                    SELECT is_active, expiration_date, never_expire
                    FROM fastapi_simple_security
                    WHERE api_key = ?""",
                        (api_key,),
                    )
                    response = c.fetchone()

                    if response:
                        is_active = response[0]
                        expiration_date = response[1]
                        never_expire = response[2]

                        # Check if key is valid
                        is_valid = is_active == 1 and (
                            never_expire
                            or datetime.fromisoformat(
                                expiration_date.replace("Z", "+00:00")
                            )
                            >= datetime.now(timezone.utc)
                        )

                        # Warm cache
                        with self._cache_lock:
                            self._cache[api_key] = is_valid

                        if is_valid:
                            warmed_count += 1
                except Exception as e:
                    warnings.warn(
                        f"Failed to warm cache for key: {e}",
                        UserWarning,
                    )

        if warmed_count > 0:
            warnings.warn(
                f"Warmed cache with {warmed_count} valid API keys",
                UserWarning,
            )

    def get_usage_stats(
        self,
    ) -> List[Tuple[str, bool, bool, str, str, int, Optional[str], Optional[str]]]:
        """
        Returns usage stats for all API keys

        Returns:
            a list of tuples with values being api_key, is_active, never_expire, expiration_date,
            latest_query_date, total_queries, name, project_name
        """
        with sqlite3.connect(self.db_location) as connection:
            c = connection.cursor()

            c.execute(
                """
            SELECT api_key, is_active, never_expire, expiration_date, \
                latest_query_date, total_queries, name, NULL as project_name
            FROM fastapi_simple_security
            ORDER BY latest_query_date DESC
            """,
            )

            response = c.fetchall()

        return response


sqlite_access = SQLiteAccess()
