"""Shared fixtures for integration tests.

Integration tests require external services (Redis, PostgreSQL, RPCN).
Run `docker compose -f compose.test.yml up -d` before executing these tests.
"""

import os

# compose.test.yml's stack, not whatever env/.env.local names: that file is a
# dev server's config, and sharing its database let the server's collector
# write live matches under the tests while their TRUNCATEs wiped its posts.
# Set before get_settings() is first called, which caches for the run; an
# exported variable, as CI sets, still wins.
os.environ.setdefault("DB_URL", "127.0.0.1:5433")
os.environ.setdefault("DB_USER", "tag2now")
os.environ.setdefault("DB_PASSWORD", "tag2now")
os.environ.setdefault("DB_NAME", "tag2now")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/0")

import pytest  # noqa: E402
from rpcn_client import RpcnClient  # noqa: E402
from shared.settings import get_settings  # noqa: E402

_settings = get_settings()
HOST = _settings.rpcn_host
PORT = _settings.rpcn_port
USER = _settings.rpcn_user
PASSWORD = _settings.rpcn_password
TOKEN = _settings.rpcn_token

# Env defaults for local / CI integration testing
# os.environ.setdefault("RPCN_USER", "test")
# os.environ.setdefault("RPCN_PASSWORD", "test")
# os.environ.setdefault("RPCN_TOKEN", "test")
# os.environ.setdefault("RPCN_HOST", "127.0.0.1")
# os.environ.setdefault("RPCN_PORT", "31313")
# os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
# os.environ.setdefault("DB_URL", "127.0.0.1:5432")
#
@pytest.fixture(scope="session")
def session():
    c = RpcnClient(HOST, PORT)
    c.connect()
    info = c.login(USER, PASSWORD, TOKEN)
    yield {"client": c, "login_info": info}
    c.disconnect()
