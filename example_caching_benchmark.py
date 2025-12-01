"""
Example demonstrating API key caching performance benefits.

This script shows the dramatic performance improvement from caching.
Run this against a running fastapi_simple_security instance.
"""

import time
import statistics
from typing import List

import requests


def benchmark_api_key_validation(
    base_url: str, api_key: str, num_requests: int = 100
) -> List[float]:
    """
    Benchmark API key validation performance.

    Args:
        base_url: Base URL of the API (e.g., 'http://localhost:8080')
        api_key: Valid API key to test with
        num_requests: Number of requests to make

    Returns:
        List of response times in milliseconds
    """
    endpoint = f"{base_url}/secure"
    headers = {"api-key": api_key}

    response_times = []

    print(f"Making {num_requests} requests to {endpoint}...")
    for i in range(num_requests):
        start = time.time()
        response = requests.get(endpoint, headers=headers)
        elapsed = (time.time() - start) * 1000  # Convert to ms

        if response.status_code != 200:
            print(f"Request {i+1} failed: {response.status_code}")
            continue

        response_times.append(elapsed)

        if (i + 1) % 10 == 0:
            print(f"  Completed {i+1}/{num_requests} requests...")

    return response_times


def invalidate_cache(base_url: str, secret_key: str, api_key: str = None):
    """Invalidate cache for testing purposes."""
    endpoint = f"{base_url}/api-key/invalidate-cache"
    headers = {"api-key": secret_key}
    params = {"api-key": api_key} if api_key else {}

    response = requests.post(endpoint, headers=headers, params=params)
    if response.status_code == 200:
        print(f"✓ Cache invalidated: {response.json()}")
    else:
        print(f"✗ Failed to invalidate cache: {response.status_code}")


def print_stats(label: str, times: List[float]):
    """Print statistics about response times."""
    print(f"\n{label}")
    print(f"  Total requests: {len(times)}")
    print(f"  Mean: {statistics.mean(times):.2f} ms")
    print(f"  Median: {statistics.median(times):.2f} ms")
    print(f"  Min: {min(times):.2f} ms")
    print(f"  Max: {max(times):.2f} ms")
    print(
        f"  Stdev: {statistics.stdev(times):.2f} ms"
        if len(times) > 1
        else "  Stdev: N/A"
    )


def main():
    """Run the caching performance benchmark."""
    # Configuration
    BASE_URL = "http://localhost:8080"
    SECRET_KEY = "TEST_SECRET"  # Your secret key

    print("=" * 60)
    print("API Key Caching Performance Benchmark")
    print("=" * 60)

    # Step 1: Create a test API key
    print("\n1. Creating test API key...")
    create_response = requests.get(
        f"{BASE_URL}/api-key/new",
        headers={"api-key": SECRET_KEY},
        params={"name": "benchmark-test", "never_expires": True},
    )

    if create_response.status_code != 200:
        print(f"✗ Failed to create API key: {create_response.status_code}")
        return

    api_key = (
        create_response.json()
        if isinstance(create_response.json(), str)
        else create_response.text.strip('"')
    )
    print(f"✓ Created API key: {api_key}")

    # Step 2: Warm-up request
    print("\n2. Warm-up request (first validation, will be cached)...")
    warmup_times = benchmark_api_key_validation(BASE_URL, api_key, num_requests=1)
    print(f"✓ First request: {warmup_times[0]:.2f} ms (cached for next hour)")

    # Step 3: Benchmark cached performance
    print("\n3. Benchmarking cached performance (should be very fast)...")
    time.sleep(0.5)  # Brief pause
    cached_times = benchmark_api_key_validation(BASE_URL, api_key, num_requests=50)
    print_stats("📊 Cached Performance Stats:", cached_times)

    # Step 4: Invalidate cache and benchmark uncached performance
    print("\n4. Invalidating cache to test uncached performance...")
    invalidate_cache(BASE_URL, SECRET_KEY, api_key)
    time.sleep(0.5)  # Brief pause

    print("\n5. Benchmarking uncached performance (database queries)...")
    uncached_times = benchmark_api_key_validation(BASE_URL, api_key, num_requests=50)
    print_stats("📊 Uncached Performance Stats:", uncached_times)

    # Step 5: Calculate improvement
    print("\n" + "=" * 60)
    print("PERFORMANCE COMPARISON")
    print("=" * 60)
    cached_mean = statistics.mean(cached_times)
    uncached_mean = statistics.mean(uncached_times)
    improvement = uncached_mean / cached_mean if cached_mean > 0 else 0

    print(f"Cached (mean):   {cached_mean:.2f} ms")
    print(f"Uncached (mean): {uncached_mean:.2f} ms")
    print(f"Speed improvement: {improvement:.1f}x faster with caching")
    print(f"Time saved per request: {uncached_mean - cached_mean:.2f} ms")

    # Calculate load reduction
    print(f"\n💡 For 1,000 requests/second:")
    print(f"   Without cache: 1,000 database queries/second")
    print(f"   With cache (1-hour TTL, 100 unique keys):")
    print(f"     - Cache hit rate: ~99%")
    print(f"     - Database queries: ~10/second")
    print(f"     - Load reduction: 99%")

    # Cleanup
    print("\n6. Cleaning up...")
    revoke_response = requests.get(
        f"{BASE_URL}/api-key/revoke",
        headers={"api-key": SECRET_KEY},
        params={"api-key": api_key},
    )
    if revoke_response.status_code == 200:
        print(f"✓ Test API key revoked")

    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print(
            "✗ Could not connect to API. Make sure it's running on http://localhost:8080"
        )
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
