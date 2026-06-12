# conftest.py  (project root)
import pytest
import os

def pytest_collection_modifyitems(config, items):
    """
    Automatically skip integration tests unless POSTGRES_URL is set
    AND the --run-integration flag is passed.
    Skip based on marker, not just mark warning.
    """
    skip_integration = pytest.mark.skip(
        reason="Integration tests skipped — no PostgreSQL available. "
               "Run with: pytest -m integration (requires POSTGRES_URL in .env)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)