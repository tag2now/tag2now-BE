"""Shared fixtures for unit tests.

Unit tests must not depend on external services (Redis, PostgreSQL, RPCN).
"""

import os
from pathlib import Path

# The profile's env file supplies the values when there is one. CI has none, so
# dummies stand in there — real ones would only be credentials nothing dials.
_PROFILE = os.getenv("FAST_API_PROFILE", "local")
_ENV_FILE = Path(__file__).resolve().parents[2] / "env" / f".env.{_PROFILE}"

if not _ENV_FILE.exists():
    os.environ.setdefault("RPCN_USER", "test")
    os.environ.setdefault("RPCN_PASSWORD", "test")
    os.environ.setdefault("RPCN_TOKEN", "test")
    os.environ.setdefault("RPCN_HOST", "127.0.0.1")
    os.environ.setdefault("RPCN_PORT", "31313")
    os.environ.setdefault("REDIS_URL", "")
    os.environ.setdefault("DB_URL", "127.0.0.1:5432")
