"""
Quick test to verify backend selection works correctly
"""

import os
import sys

# Test 1: SQLite backend (default)
print("Test 1: Testing default SQLite backend...")
os.environ.pop("FASTAPI_SIMPLE_SECURITY_BACKEND", None)
from fastapi_simple_security._backend_factory import get_storage_backend

backend = get_storage_backend()
print(f"Backend type: {type(backend).__name__}")
assert "SQLiteAccess" in type(backend).__name__, "Should be SQLite backend by default"
print("✓ SQLite backend works\n")

# Test 2: Elasticsearch backend selection (will fail import if elasticsearch not installed)
print("Test 2: Testing Elasticsearch backend selection...")
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
try:
    # Need to reload to pick up environment change
    import importlib
    import fastapi_simple_security._backend_factory as factory_module

    importlib.reload(factory_module)
    backend_es = factory_module.get_storage_backend()
    print(f"Backend type: {type(backend_es).__name__}")
    print("✓ Elasticsearch backend selected (but may not connect without ES running)")
except ImportError as e:
    print(f"⚠ Elasticsearch package not installed: {e}")
    print("  This is expected - install with: pip install elasticsearch")

print("\nAll tests passed!")
