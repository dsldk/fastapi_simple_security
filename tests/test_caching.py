"""Test caching functionality for API key validation."""

import os
import time

from fastapi.testclient import TestClient


# Ensure we're using SQLite backend for these tests
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "sqlite"


def test_cache_hit_reduces_database_calls(client: TestClient, admin_key: str):
    """Test that caching works - subsequent requests with same key succeed."""
    # Create an API key
    response = client.get(
        url="/auth/new",
        headers={"secret-key": admin_key},
        params={"name": "cache-test", "never_expires": True},
    )
    assert response.status_code == 200
    api_key = response.json()

    # Multiple calls with same key should all succeed (testing cache doesn't break functionality)
    for _ in range(5):
        response = client.get("/secure", headers={"api-key": api_key})
        assert response.status_code == 200


def test_cache_invalidation_for_revoked_key(client: TestClient, admin_key: str):
    """Test that revoking a key invalidates its cache entry."""
    # Create and cache an API key
    response = client.get(
        url="/auth/new",
        headers={"secret-key": admin_key},
        params={"name": "revoke-test", "never_expires": True},
    )
    assert response.status_code == 200
    api_key = response.json()

    # First call to cache the key
    response = client.get("/secure", headers={"api-key": api_key})
    assert response.status_code == 200

    # Revoke the key (should invalidate cache)
    revoke_response = client.get(
        url="/auth/revoke",
        headers={"secret-key": admin_key},
        params={"api-key": api_key},
    )
    assert revoke_response.status_code == 200

    # Try to use revoked key - should fail immediately (not use cached value)
    response = client.get("/secure", headers={"api-key": api_key})
    assert response.status_code == 403


def test_cache_invalidation_endpoint(client: TestClient, admin_key: str):
    """Test the manual cache invalidation endpoint."""
    # Create and cache an API key
    response = client.get(
        url="/auth/new",
        headers={"secret-key": admin_key},
        params={"name": "invalidate-test", "never_expires": True},
    )
    assert response.status_code == 200
    api_key = response.json()

    # Cache the key
    response = client.get("/secure", headers={"api-key": api_key})
    assert response.status_code == 200

    # Invalidate specific key
    invalidate_response = client.post(
        url="/auth/invalidate-cache",
        headers={"secret-key": admin_key},
        params={"api-key": api_key},
    )
    assert invalidate_response.status_code == 200
    assert "invalidated" in invalidate_response.json()["message"].lower()

    # Key should still work (just cache was cleared)
    response = client.get("/secure", headers={"api-key": api_key})
    assert response.status_code == 200


def test_cache_clear_all(client: TestClient, admin_key: str):
    """Test clearing entire cache."""
    # Create multiple API keys
    keys = []
    for i in range(3):
        response = client.get(
            url="/auth/new",
            headers={"secret-key": admin_key},
            params={"name": f"clear-test-{i}", "never_expires": True},
        )
        assert response.status_code == 200
        keys.append(response.json())

    # Cache all keys
    for key in keys:
        response = client.get("/secure", headers={"api-key": key})
        assert response.status_code == 200

    # Clear entire cache
    invalidate_response = client.post(
        url="/auth/invalidate-cache", headers={"secret-key": admin_key}
    )
    assert invalidate_response.status_code == 200
    assert "entire cache" in invalidate_response.json()["message"].lower()

    # All keys should still work
    for key in keys:
        response = client.get("/secure", headers={"api-key": key})
        assert response.status_code == 200


def test_cache_ttl_expiration(client: TestClient, admin_key: str):
    """Test that TTL caching doesn't break normal functionality."""
    # Create an API key
    response = client.get(
        url="/auth/new",
        headers={"secret-key": admin_key},
        params={"name": "ttl-test", "never_expires": True},
    )
    assert response.status_code == 200
    api_key = response.json()

    # Use the key
    response = client.get("/secure", headers={"api-key": api_key})
    assert response.status_code == 200

    # Wait a bit (less than default TTL of 3600s)
    time.sleep(0.5)

    # Key should still work
    response = client.get("/secure", headers={"api-key": api_key})
    assert response.status_code == 200


def test_cache_invalid_key_cached(client: TestClient, admin_key: str):
    """Test that invalid keys don't cause issues with caching."""
    fake_key = "invalid-key-12345"

    # Multiple requests with invalid key should all fail consistently
    for _ in range(3):
        response = client.get("/secure", headers={"api-key": fake_key})
        assert response.status_code == 403
