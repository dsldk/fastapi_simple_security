"""Interaction with SQLite database."""

import os
import sqlite3
import threading
import uuid
import warnings
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


class SQLiteAccess(StorageBackend):
    """Class handling SQLite connection and writes"""

    # TODO This should not be a class, a fully functional approach is better

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

        # Set es_index early to avoid race conditions with background threads
        try:
            self.es_index = os.environ["FASTAPI_ES_APIKEY_STORAGE_INDEX"]
        except KeyError:
            self.es_index = None

        self.init_db()

        try:
            api_key_file = os.environ["FASTAPI_SIMPLE_SECURITY_API_KEY_FILE"]
        except KeyError:
            api_key_file = None

        if api_key_file:
            self.handle_api_key_file(api_key_file)

        if self.es_index:
            self.load_keys_from_elasticsearch(self.es_index)

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
        """Load API keys from Elasticsearch index into SQLite.

        Args:
            index_name (str): Name of the Elasticsearch index to load keys from.
        """
        if Elasticsearch is None:
            raise ImportError(
                "elasticsearch package is required to load keys from Elasticsearch. "
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
        try:
            if es_api_key:
                es = Elasticsearch(es_hosts.split(","), api_key=es_api_key)
            elif es_user and es_password:
                credited_hosts = []
                for host_name in es_hosts.split(","):
                    if "://" in host_name:
                        protocol, rest = host_name.split("://", 1)
                    else:
                        protocol = "http"
                        rest = host_name
                    host_name = f"{protocol}://{es_user}:{es_password}@{rest}"
                    credited_hosts.append(host_name)
                es_hosts = ",".join(credited_hosts)
                es = Elasticsearch(
                    es_hosts.split(","),
                    verify_certs=False,
                )
            else:
                es = Elasticsearch(es_hosts.split(","))

            # Check if index exists, create it if not
            if not es.indices.exists(index=index_name):
                warnings.warn(
                    f"Elasticsearch index '{index_name}' does not exist. Creating it with default mappings.",
                    UserWarning,
                )

                # Create index with mappings matching CSV format: name;api_key;expiration_date
                mapping = {
                    "mappings": {
                        "properties": {
                            "name": {"type": "keyword"},
                            "api_key": {"type": "keyword"},
                            "expiration_date": {
                                "type": "date",
                                "format": "strict_date_time||strict_date_time_no_millis||epoch_millis",
                            },
                        }
                    }
                }
                es.indices.create(index=index_name, body=mapping)
                warnings.warn(
                    f"Created Elasticsearch index '{index_name}' with mappings for name, api_key, and expiration_date",
                    UserWarning,
                )

            # Query all documents from the index
            result = es.search(
                index=index_name,
                body={
                    "query": {"match_all": {}},
                    "size": 10000,
                },
            )

            keys_loaded = 0
            for hit in result["hits"]["hits"]:
                doc = hit["_source"]
                api_key = doc.get("api_key")
                name = doc.get("name", "")
                expiration_date = doc.get("expiration_date", "")

                if api_key:
                    try:
                        self.insert_key(api_key, name, expiration_date)
                        keys_loaded += 1
                    except Exception as e:
                        warnings.warn(
                            f"Failed to load API key '{name}' from Elasticsearch: {e}",
                            UserWarning,
                        )

            warnings.warn(
                f"Loaded {keys_loaded} API keys from Elasticsearch index '{index_name}'",
                UserWarning,
            )

            # Close the Elasticsearch connection
            es.close()

        except Exception as e:
            warnings.warn(
                f"Error connecting to Elasticsearch to load API keys: {e}",
                UserWarning,
            )

    def _get_elasticsearch_client(self):
        """Get an Elasticsearch client if configured and available.

        Returns:
            Elasticsearch client or None if not configured/available
        """
        if Elasticsearch is None or not self.es_index:
            return None

        try:
            es_hosts = os.environ.get(
                "FASTAPI_SIMPLE_SECURITY_ES_HOSTS", "http://localhost:9200"
            )
            es_user = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_USER")
            es_password = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_PASSWORD")
            es_api_key = os.environ.get("FASTAPI_SIMPLE_SECURITY_ES_API_KEY")

            if es_api_key:
                return Elasticsearch(es_hosts.split(","), api_key=es_api_key)
            elif es_user and es_password:
                credited_hosts = []
                for host_name in es_hosts.split(","):
                    if "://" in host_name:
                        protocol, rest = host_name.split("://", 1)
                    else:
                        protocol = "http"
                        rest = host_name
                    host_name = f"{protocol}://{es_user}:{es_password}@{rest}"
                    credited_hosts.append(host_name)
                es_hosts = ",".join(credited_hosts)
                return Elasticsearch(es_hosts.split(","), verify_certs=False)
            else:
                return Elasticsearch(es_hosts.split(","))
        except Exception as e:
            warnings.warn(
                f"Failed to connect to Elasticsearch: {e}",
                UserWarning,
            )
            return None

    def _sync_to_elasticsearch(
        self, api_key: str, name: str, expiration_date: str, is_active: bool = True
    ):
        """Sync an API key to Elasticsearch in the background.

        Args:
            api_key: The API key
            name: The key name
            expiration_date: ISO 8601 expiration date
            is_active: Whether the key is active (for revocation)
        """

        def _sync():
            if self.es_index is None:
                return
            es = self._get_elasticsearch_client()
            if es is None:
                return

            try:
                # Ensure index exists with proper mappings
                if not es.indices.exists(index=self.es_index):
                    mapping = {
                        "mappings": {
                            "properties": {
                                "name": {"type": "keyword"},
                                "api_key": {"type": "keyword"},
                                "expiration_date": {
                                    "type": "date",
                                    "format": "strict_date_time||strict_date_time_no_millis||epoch_millis",
                                },
                                "is_active": {"type": "boolean"},
                            }
                        }
                    }
                    es.indices.create(index=self.es_index, body=mapping)

                # Index or update the document
                doc = {
                    "name": name,
                    "api_key": api_key,
                    "expiration_date": expiration_date,
                    "is_active": is_active,
                }
                es.index(index=self.es_index, id=api_key, document=doc)
                es.indices.refresh(index=self.es_index)
                es.close()
            except Exception as e:
                warnings.warn(
                    f"Failed to sync API key to Elasticsearch: {e}",
                    UserWarning,
                )

        # Run sync in background thread to not block
        threading.Thread(target=_sync, daemon=True).start()

    def create_key(self, name, never_expire, project_name: Optional[str] = None) -> str:
        api_key = str(uuid.uuid4())

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
                    (
                        datetime.utcnow() + timedelta(days=self.expiration_limit)
                    ).isoformat(timespec="seconds"),
                    None,
                    0,
                    name,
                ),
            )
            connection.commit()

        # Sync to Elasticsearch if configured
        expiration_date = (
            datetime.utcnow() + timedelta(days=self.expiration_limit)
        ).isoformat(timespec="seconds")
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

            # Without an expiration date, we set it here
            if not expiration_date:
                parsed_expiration_date = (
                    datetime.utcnow() + timedelta(days=self.expiration_limit)
                ).isoformat(timespec="seconds")
            else:
                # Else: insert new key in database
                try:
                    # We parse and re-write to the right timespec
                    parsed_expiration_date = datetime.fromisoformat(
                        expiration_date
                    ).isoformat(timespec="seconds")
                except ValueError as exc:
                    raise HTTPException(
                        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="The expiration date could not be parsed. \
                            Please use ISO 8601.",
                    ) from exc

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

            # Without an expiration date, we set it here
            if not new_expiration_date:
                parsed_expiration_date = (
                    datetime.utcnow() + timedelta(days=self.expiration_limit)
                ).isoformat(timespec="seconds")

            else:
                try:
                    # We parse and re-write to the right timespec
                    parsed_expiration_date = datetime.fromisoformat(
                        new_expiration_date
                    ).isoformat(timespec="seconds")
                except ValueError as exc:
                    raise HTTPException(
                        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="The expiration date could not be parsed. \
                            Please use ISO 8601.",
                    ) from exc

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
                    and (datetime.fromisoformat(response[2]) < datetime.utcnow())
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
                    datetime.utcnow().isoformat(timespec="seconds"),
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
