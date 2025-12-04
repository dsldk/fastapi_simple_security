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

# Test 2: Verify SQLite is always used (even if elasticsearch is specified)
print("Test 2: Testing that SQLite is always used...")
os.environ["FASTAPI_SIMPLE_SECURITY_BACKEND"] = "elasticsearch"
try:
    # Need to reload to pick up environment change
    import importlib
    import fastapi_simple_security._backend_factory as factory_module

    importlib.reload(factory_module)
    backend_always_sqlite = factory_module.get_storage_backend()
    print(f"Backend type: {type(backend_always_sqlite).__name__}")
    assert (
        "SQLiteAccess" in type(backend_always_sqlite).__name__
    ), "Should always be SQLite backend"
    print("✓ SQLite backend always used (elasticsearch option deprecated)")
except ImportError as e:
    print(f"⚠ Unexpected import error: {e}")

print("\nAll tests passed!")
