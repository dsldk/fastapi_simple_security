"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class StorageBackend(ABC):
    """Abstract base class for storage backends"""

    @abstractmethod
    def check_key(self, api_key: str) -> bool:
        """
        Checks if an API key is valid

        Args:
            api_key: the API key to validate

        Returns:
            True if the key is valid, False otherwise
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def revoke_key(self, api_key: str):
        """
        Revokes an API key

        Args:
            api_key: the API key to revoke
        """
        pass

    @abstractmethod
    def renew_key(self, api_key: str, new_expiration_date: str) -> Optional[str]:
        """
        Renews an API key

        Args:
            api_key: the API key to renew
            new_expiration_date: the new expiration date in ISO format

        Returns:
            a message describing the renewal result
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_usage_stats(
        self,
    ) -> List[Tuple[str, bool, bool, str, str, int, Optional[str], Optional[str]]]:
        """
        Returns usage stats for all API keys

        Returns:
            a list of tuples with values being api_key, is_active, never_expire, expiration_date,
            latest_query_date, total_queries, name, project_name
        """
        pass

    @abstractmethod
    def invalidate_cache(self, api_key: Optional[str] = None):
        """
        Invalidates the cache for a specific key or all keys

        Args:
            api_key: the API key to invalidate, or None to clear entire cache
        """
        pass
