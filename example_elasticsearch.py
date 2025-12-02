"""
Example application demonstrating Elasticsearch backend usage
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi_simple_security import api_key_router, api_key_security

# Configure to use Elasticsearch backend
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
os.environ["FASTAPI_SIMPLE_SECURITY_ES_HOSTS"] = "http://localhost:9200"

# Optional: Configure authentication
# os.environ["FASTAPI_SIMPLE_SECURITY_ES_USER"] = "elastic"
# os.environ["FASTAPI_SIMPLE_SECURITY_ES_PASSWORD"] = "changeme"
# OR use API key:
# os.environ["FASTAPI_SIMPLE_SECURITY_ES_API_KEY"] = "your-es-api-key"

# Configure secret for managing API keys
os.environ["FASTAPI_SIMPLE_SECURITY_SECRET"] = "your-admin-secret"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for proper startup/shutdown handling.
    Ensures Elasticsearch connection is properly closed on shutdown.
    """
    # Startup
    print("Application starting up...")
    yield
    # Shutdown
    print("Application shutting down...")
    from fastapi_simple_security._backend_factory import storage_backend

    storage_backend.close()
    print("Elasticsearch connection closed")


app = FastAPI(
    title="Example API with Elasticsearch Backend",
    description="Demonstrates fastapi_simple_security with Elasticsearch",
    lifespan=lifespan,
)

# Include the API key management endpoints
app.include_router(api_key_router, prefix="/auth", tags=["authentication"])


@app.get("/")
async def root():
    """Public endpoint"""
    return {
        "message": "Welcome to the API",
        "backend": "elasticsearch",
        "docs": "/docs",
    }


@app.get("/secure/data")
async def get_secure_data(api_key: str = Depends(api_key_security)):
    """
    Secured endpoint - requires valid API key

    Pass API key as:
    - Query parameter: ?api-key=your-key
    - Header: api-key: your-key
    """
    return {"message": "This is secure data", "authenticated_with": api_key}


@app.get("/secure/user-info")
async def get_user_info(api_key: str = Depends(api_key_security)):
    """Another secured endpoint"""
    return {
        "user": "authenticated_user",
        "api_key": api_key,
        "permissions": ["read", "write"],
    }


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("Starting API with Elasticsearch Backend")
    print("=" * 60)
    print("\nTo create an API key, use:")
    print(
        "  curl -X GET 'http://localhost:8000/auth/new?name=my-key&project_name=my-project' \\"
    )
    print("       -H 'secret-key: your-admin-secret'")
    print("\nTo use an API key:")
    print("  curl -X GET 'http://localhost:8000/secure/data?api-key=YOUR_API_KEY'")
    print("\nAPI Documentation:")
    print("  http://localhost:8000/docs")
    print("\n" + "=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
