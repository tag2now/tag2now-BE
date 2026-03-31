"""Shared fixtures for unit tests.

Unit tests must not depend on external services (Redis, PostgreSQL, RPCN).
Environment variables are set to dummy values to satisfy pydantic-settings.
"""

import os

os.environ.setdefault("RPCN_USER", "test")
os.environ.setdefault("RPCN_PASSWORD", "test")
os.environ.setdefault("RPCN_TOKEN", "test")
os.environ.setdefault("RPCN_HOST", "localhost")
os.environ.setdefault("RPCN_PORT", "31313")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DB_URL", "localhost:5432")
