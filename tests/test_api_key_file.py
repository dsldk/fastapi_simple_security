"""Test API key file handling functionality."""

import os
import tempfile

import pytest

from fastapi_simple_security._sqlite_access import SQLiteAccess


class TestAPIKeyFileHandling:
    """Test suite for API key file handling."""

    def test_handle_api_key_file_sqlite(self):
        """Test handling API key file with SQLite backend."""
        # Create a temporary API key file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_file = f.name
            # Write test API keys
            f.write("# This is a comment\n")
            f.write("TestKey1;test-key-123;2026-12-31T23:59:59\n")
            f.write("TestKey2;test-key-456;\n")  # Empty expiration date
            f.write("\n")  # Empty line
            f.write("TestKey3;test-key-789;2027-01-15T12:00:00\n")

        # Use a temporary file instead of :memory: to avoid connection issues
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            # Create SQLite backend instance
            os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"] = temp_db.name
            backend = SQLiteAccess()

            # Handle the API key file
            backend.handle_api_key_file(temp_file)

            # Verify the keys were inserted
            stats = backend.get_usage_stats()
            assert len(stats) == 3, f"Expected 3 keys, got {len(stats)}"

            # Check first key
            key1 = [s for s in stats if s[0] == "test-key-123"][0]
            assert key1[6] == "TestKey1"  # name
            assert key1[1] == 1  # is_active (SQLite stores as integer)
            assert "2026-12-31" in key1[3]  # expiration_date

            # Check second key (empty expiration date should use default)
            key2 = [s for s in stats if s[0] == "test-key-456"][0]
            assert key2[6] == "TestKey2"  # name
            assert key2[1] == 1  # is_active

            # Check third key
            key3 = [s for s in stats if s[0] == "test-key-789"][0]
            assert key3[6] == "TestKey3"  # name
            assert "2027-01-15" in key3[3]  # expiration_date

        finally:
            # Clean up
            os.unlink(temp_file)
            os.unlink(temp_db.name)
            if "FASTAPI_SIMPLE_SECURITY_DB_LOCATION" in os.environ:
                del os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"]

    def test_handle_api_key_file_invalid_format(self):
        """Test handling API key file with invalid format."""
        # Create a temporary API key file with invalid content
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_file = f.name
            f.write("InvalidLine\n")  # Missing semicolons

        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"] = temp_db.name
            backend = SQLiteAccess()

            # Should raise ValueError for invalid format
            with pytest.raises(ValueError, match="API Key file line.*is invalid"):
                backend.handle_api_key_file(temp_file)

        finally:
            os.unlink(temp_file)
            os.unlink(temp_db.name)
            if "FASTAPI_SIMPLE_SECURITY_DB_LOCATION" in os.environ:
                del os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"]

    def test_handle_api_key_file_not_found(self):
        """Test handling non-existent API key file."""
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"] = temp_db.name
            backend = SQLiteAccess()

            # Should raise FileNotFoundError
            with pytest.raises(FileNotFoundError, match="API Key file.*does not exist"):
                backend.handle_api_key_file("/nonexistent/file.txt")

        finally:
            os.unlink(temp_db.name)
            if "FASTAPI_SIMPLE_SECURITY_DB_LOCATION" in os.environ:
                del os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"]

    def test_handle_api_key_file_duplicate_keys(self):
        """Test handling API key file with duplicate keys."""
        # Create a temporary API key file with duplicate keys
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_file = f.name
            f.write("TestKey1;test-key-123;2026-12-31T23:59:59\n")
            f.write(
                "TestKey1Updated;test-key-123;2027-12-31T23:59:59\n"
            )  # Same key, different name and date

        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"] = temp_db.name
            backend = SQLiteAccess()

            # Handle the API key file
            backend.handle_api_key_file(temp_file)

            # Verify only one key exists (should be renewed)
            stats = backend.get_usage_stats()
            assert len(stats) == 1, f"Expected 1 key, got {len(stats)}"

            # The key should have the updated expiration date
            key = stats[0]
            assert key[0] == "test-key-123"
            assert "2027-12-31" in key[3]  # Updated expiration_date

        finally:
            os.unlink(temp_file)
            os.unlink(temp_db.name)
            if "FASTAPI_SIMPLE_SECURITY_DB_LOCATION" in os.environ:
                del os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"]

    def test_handle_api_key_file_comments_and_whitespace(self):
        """Test handling API key file with various comment styles and whitespace."""
        # Create a temporary API key file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_file = f.name
            f.write("# Header comment\n")
            f.write("   # Indented comment\n")
            f.write("\n")
            f.write("  \n")  # Whitespace only
            f.write(
                "   TestKey1;test-key-123;2026-12-31T23:59:59   \n"
            )  # Leading/trailing whitespace

        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"] = temp_db.name
            backend = SQLiteAccess()

            # Handle the API key file
            backend.handle_api_key_file(temp_file)

            # Verify only one key was inserted
            stats = backend.get_usage_stats()
            assert len(stats) == 1, f"Expected 1 key, got {len(stats)}"
            assert stats[0][0] == "test-key-123"

        finally:
            os.unlink(temp_file)
            os.unlink(temp_db.name)
            if "FASTAPI_SIMPLE_SECURITY_DB_LOCATION" in os.environ:
                del os.environ["FASTAPI_SIMPLE_SECURITY_DB_LOCATION"]


@pytest.mark.skipif(
    os.environ.get("SKIP_ELASTICSEARCH_TESTS") == "1",
    reason="Elasticsearch tests skipped (requires Elasticsearch connection)",
)
class TestAPIKeyFileHandlingElasticsearch:
    """Test suite for API key file handling with Elasticsearch backend."""

    def test_handle_api_key_file_elasticsearch(self):
        """Test handling API key file with Elasticsearch backend."""
        try:
            from fastapi_simple_security._elasticsearch_access import (
                ElasticsearchAccess,
            )
        except ImportError:
            pytest.skip("Elasticsearch package not installed")

        # Create a temporary API key file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_file = f.name
            f.write("# Test API keys\n")
            f.write("ESTestKey1;es-test-key-123;2026-12-31T23:59:59\n")
            f.write("ESTestKey2;es-test-key-456;\n")

        try:
            # Set test environment
            os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = os.environ.get(
                "FASTAPI_SIMPLE_SECURITY_ES_HOSTS", "http://localhost:9200"
            )

            # Create Elasticsearch backend instance
            try:
                backend = ElasticsearchAccess()
            except Exception as e:
                pytest.skip(f"Could not connect to Elasticsearch: {e}")

            # Clean up any existing test keys
            try:
                backend.es.delete(index=backend.index_name, id="es-test-key-123")
            except Exception:
                pass
            try:
                backend.es.delete(index=backend.index_name, id="es-test-key-456")
            except Exception:
                pass
            backend.es.indices.refresh(index=backend.index_name)

            # Handle the API key file
            backend.handle_api_key_file(temp_file)

            # Give Elasticsearch time to index
            backend.es.indices.refresh(index=backend.index_name)

            # Verify the keys were inserted
            stats = backend.get_usage_stats()
            test_keys = [s for s in stats if s[0].startswith("es-test-key")]
            assert len(test_keys) == 2, f"Expected 2 test keys, got {len(test_keys)}"

            # Check first key
            key1 = [s for s in test_keys if s[0] == "es-test-key-123"][0]
            assert key1[6] == "ESTestKey1"  # name
            assert key1[1] is True  # is_active
            assert "2026-12-31" in key1[3]  # expiration_date

            # Clean up
            backend.es.delete(index=backend.index_name, id="es-test-key-123")
            backend.es.delete(index=backend.index_name, id="es-test-key-456")
            backend.es.indices.refresh(index=backend.index_name)

        finally:
            os.unlink(temp_file)

    def test_handle_api_key_file_elasticsearch_invalid_format(self):
        """Test handling API key file with invalid format (Elasticsearch)."""
        try:
            from fastapi_simple_security._elasticsearch_access import (
                ElasticsearchAccess,
            )
        except ImportError:
            pytest.skip("Elasticsearch package not installed")

        # Create a temporary API key file with invalid content
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_file = f.name
            f.write("InvalidLineNoSemicolons\n")

        try:
            try:
                backend = ElasticsearchAccess()
            except Exception as e:
                pytest.skip(f"Could not connect to Elasticsearch: {e}")

            # Should raise ValueError for invalid format
            with pytest.raises(ValueError, match="API Key file line.*is invalid"):
                backend.handle_api_key_file(temp_file)

        finally:
            os.unlink(temp_file)
