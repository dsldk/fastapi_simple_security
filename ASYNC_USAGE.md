# Async FastAPI Usage Guide

This document explains how the Elasticsearch backend works with async FastAPI applications and best practices for production use.

## Elasticsearch Backend and Async FastAPI

### Current Implementation

The Elasticsearch backend uses **synchronous operations** with the standard `elasticsearch` Python client. While this works with async FastAPI, there are some considerations:

#### ✅ What Works Well

1. **Connection Pooling**: The Elasticsearch client maintains an internal connection pool and is designed to be reused across requests. The client is instantiated once at application startup (when the module is imported).

2. **Caching**: The implementation uses TTL-based caching to minimize Elasticsearch queries during API key validation, reducing I/O operations.

3. **Background Tasks**: Usage statistics updates are done in background threads to avoid blocking request handling.

#### ⚠️ Considerations

1. **Synchronous I/O**: Elasticsearch operations are synchronous and will block the async event loop during I/O. However, the impact is minimal for most use cases due to:
   - Caching reduces the frequency of Elasticsearch queries
   - Most Elasticsearch operations are fast (< 10ms for simple queries)
   - Only API key validation happens in the request path; other operations (create/revoke/renew) are admin operations

2. **Connection Lifecycle**: The Elasticsearch client connection should be properly closed on application shutdown.

### Recommended Setup

Use FastAPI's lifespan context manager to ensure proper cleanup:

```python
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi_simple_security import api_key_router, api_key_security

# Configure Elasticsearch backend
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "http://localhost:9200"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure proper startup/shutdown handling"""
    # Startup
    print("Application starting...")
    yield
    # Shutdown
    print("Application shutting down...")
    from fastapi_simple_security._backend_factory import storage_backend
    storage_backend.close()
    print("Elasticsearch connection closed")


app = FastAPI(lifespan=lifespan)
app.include_router(api_key_router, prefix="/auth", tags=["auth"])


@app.get("/secure-data")
async def get_data(api_key: str = Depends(api_key_security)):
    return {"data": "secure information"}
```

### Performance Optimization

The implementation includes several optimizations for async environments:

1. **TTL Cache**: Configure cache settings to reduce Elasticsearch queries:

   ```python
   # Cache API key validation results for 1 hour (default)
   os.environ["FASTAPI_SIMPLE_SECURITY_CACHE_TTL"] = "3600"
   
   # Maximum 10,000 cached keys (default)
   os.environ["FASTAPI_SIMPLE_SECURITY_CACHE_MAXSIZE"] = "10000"
   ```

2. **Background Updates**: Usage statistics are updated in background threads, not blocking the request.

3. **Index Refresh**: Elasticsearch index is refreshed only after write operations (create/revoke/renew), not during reads.

### When to Consider Async Elasticsearch

For high-throughput applications (>1000 req/s) with frequent cache misses, consider upgrading to the async Elasticsearch client:

```python
# Future enhancement - would require:
pip install elasticsearch[async]
```

This would involve:

- Using `AsyncElasticsearch` client
- Converting all methods to async/await
- Updating endpoints to be async
- Using `asyncio.create_task()` instead of threading for background tasks

For most use cases, the current synchronous implementation with caching is sufficient and simpler to maintain.

### Production Checklist

- ✅ Configure caching appropriately for your traffic patterns
- ✅ Use lifespan context manager for proper shutdown
- ✅ Monitor cache hit rates and adjust TTL/maxsize if needed
- ✅ Ensure Elasticsearch cluster is properly sized for your load
- ✅ Use Elasticsearch authentication (basic auth or API key)
- ✅ Consider read replicas for high-availability setups

### Troubleshooting

**Slow API Key Validation**:

- Increase cache TTL to reduce Elasticsearch queries
- Verify Elasticsearch cluster performance
- Check network latency between app and Elasticsearch

**Memory Issues**:

- Reduce `FASTAPI_SIMPLE_SECURITY_CACHE_MAXSIZE`
- Implement cache eviction monitoring

**Connection Errors**:

- Ensure Elasticsearch is accessible from your application
- Verify authentication credentials
- Check firewall/network settings
