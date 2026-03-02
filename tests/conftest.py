"""
Shared pytest fixtures and setup for the test suite.

DATABASE_URL is overridden to an in-memory SQLite database so tests
never touch the production volume and run without Docker.
"""

import os

# Override DB before any web module is imported.
# This ensures create_session_factory() builds an in-memory engine.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
