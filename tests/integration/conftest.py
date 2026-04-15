"""Integration tests conftest — reset global DB state per test."""
import pytest
import backend.database as db_module


@pytest.fixture(autouse=True)
def reset_db_globals():
    """Reset the global DB engine/session_factory between tests.

    This prevents event loop conflicts when running integration tests
    that use ASGI TestClient (which creates its own event loop).
    """
    # Save originals
    old_engine = db_module._engine
    old_factory = db_module._session_factory

    # Reset
    db_module._engine = None
    db_module._session_factory = None

    yield

    # Restore (don't dispose — the engine may already be closed)
    db_module._engine = old_engine
    db_module._session_factory = old_factory
