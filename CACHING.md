# API Key Caching

## Overview

To improve performance and reduce database load, `fastapi_simple_security` implements a **TTL-based in-memory cache** for API key validation. This is particularly beneficial for high-traffic applications with a relatively small number of API keys.

## Benefits

- **Performance**: In-memory lookups are orders of magnitude faster than database queries
- **Reduced Load**: Significantly fewer queries to Elasticsearch/SQLite
- **Cost Savings**: Lower infrastructure costs from reduced database operations
- **Better Response Times**: Cached validations complete in microseconds vs milliseconds

## Configuration

Cache behavior is controlled via environment variables:

### Cache TTL (Time To Live)

```bash
export FASTAPI_SIMPLE_SECURITY_CACHE_TTL=3600  # Cache duration in seconds (default: 3600 = 1 hour)
```

**Recommended values:**

- **High security, frequent key changes**: `300` (5 minutes)
- **Balanced** (recommended): `3600` (1 hour)
- **Performance-critical, stable keys**: `7200` (2 hours)

### Cache Size Limit

```bash
export FASTAPI_SIMPLE_SECURITY_CACHE_MAXSIZE=10000  # Maximum cached keys (default: 10000)
```

When the cache reaches this limit, the least recently used (LRU) entries are automatically evicted.

⚠️ **Security consideration**: Longer cache TTL means changes to keys (revocation, expiration) take longer to propagate. Balance performance with your security requirements.

## How It Works

The implementation uses [`cachetools.TTLCache`](https://github.com/tkem/cachetools/) which provides:

- **Automatic TTL expiration**: No manual timestamp checking needed
- **LRU eviction**: When cache is full, least recently used entries are removed
- **Thread-safe operations**: Built-in locking mechanisms
- **Memory bounded**: Prevents unlimited cache growth

1. **First Request**: API key is validated against the database and cached
2. **Subsequent Requests**: Served from in-memory cache until TTL expires
3. **Cache Expiry**: After TTL, next request triggers database validation and cache refresh
4. **Automatic Invalidation**: Cache is automatically cleared when keys are revoked or renewed

## Cache Invalidation

### Automatic Invalidation

The cache is automatically invalidated when:
- A key is **revoked** via `/api-key/revoke`
- A key is **renewed** via `/api-key/renew`
- Cache entry **expires** after TTL

### Manual Invalidation Endpoint

For immediate cache clearing (requires secret-based authentication):

```bash
# Invalidate specific key
POST /api-key/invalidate-cache?api-key=YOUR_API_KEY_HERE
Header: api-key: YOUR_SECRET_KEY

# Clear entire cache
POST /api-key/invalidate-cache
Header: api-key: YOUR_SECRET_KEY
```

**Use cases for manual invalidation:**
- Direct database modifications outside the API
- Emergency key revocation requiring immediate effect
- Testing or troubleshooting cache behavior

## Implementation Details

### Caching Library

Uses [`cachetools.TTLCache`](https://github.com/tkem/cachetools/) - a production-ready caching library with:

- Automatic TTL-based expiration
- LRU eviction when cache is full
- Thread-safe operations
- Zero external dependencies (pure Python)

### Thread Safety

- Uses `cachetools.TTLCache` with `threading.Lock()` for thread-safe operations
- Safe for concurrent requests in production environments
- Proper lock ordering prevents deadlocks

### Memory Usage

- Cache stores: `{api_key: bool}` (is_valid flag)
- Memory footprint: ~50 bytes per cached key
- Example: 10,000 keys ≈ 500 KB memory
- Maximum size configurable via `FASTAPI_SIMPLE_SECURITY_CACHE_MAXSIZE`

### LRU Eviction

When cache reaches `maxsize`, least recently used entries are automatically removed:

- Ensures bounded memory usage
- Keeps most frequently accessed keys in cache
- No manual cleanup required

### Usage Statistics

- Usage counters are updated in background threads
- Cache hits still increment usage statistics
- No impact on usage tracking accuracy

## Example Usage

```python
from fastapi import FastAPI, Depends
from fastapi_simple_security import api_key_router, api_key_security

app = FastAPI()
app.include_router(api_key_router, prefix="/api-key", tags=["API Key Management"])

@app.get("/protected")
async def protected_endpoint(api_key: str = Depends(api_key_security)):
    # First call: validates against database (~10-50ms)
    # Subsequent calls within 1 hour: served from cache (~0.01ms)
    return {"message": "Access granted", "api_key": api_key}
```

## Performance Impact

**Without caching:**
- Every request: Database query + validation logic
- ~10-50ms per validation (Elasticsearch/SQLite)

**With caching (1-hour TTL):**
- First request: ~10-50ms (database query + cache write)
- Subsequent requests: ~0.01-0.1ms (memory lookup)
- **~100-1000x faster** for cached keys

**Example calculation for high-traffic scenario:**
- 1,000 requests/second
- 100 unique API keys
- Cache hit rate: ~99%
- Database queries reduced from 1,000/sec to ~10/sec
- **99% reduction in database load**

## Best Practices

1. **Set appropriate TTL**: Balance security and performance based on your use case
2. **Monitor cache hit rate**: Log cache performance in production
3. **Use manual invalidation**: For emergency key revocations
4. **Consider key count**: Caching is most effective with < 10,000 unique keys
5. **Test TTL behavior**: Verify revoked keys are blocked within acceptable time

## Monitoring

To monitor cache effectiveness, consider adding metrics for:
- Cache hit/miss ratio
- Average validation time (cached vs uncached)
- Cache size and memory usage
- Time since last cache invalidation

## Security Considerations

⚠️ **Important**: Cached keys remain valid until TTL expires or manual invalidation occurs.

**Mitigation strategies:**
1. Use shorter TTL for high-security applications
2. Immediately call `/invalidate-cache` after emergency revocations
3. Implement additional security layers (rate limiting, IP allowlisting)
4. Monitor key usage patterns for anomalies

## Troubleshooting

**Keys still work after revocation:**
- Cache TTL hasn't expired yet
- Solution: Call `/invalidate-cache` endpoint

**Performance not improving:**
- Check cache TTL configuration
- Verify many unique keys aren't bypassing cache
- Ensure proper environment variable setup

**Memory usage concerns:**
- Review number of unique API keys
- Consider shorter TTL to reduce cache size
- Monitor with process memory metrics
