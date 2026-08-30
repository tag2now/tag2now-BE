"""Shared fixtures for integration tests.

Integration tests require external services (Redis, PostgreSQL, RPCN).
Run `docker compose -f compose.test.yml up -d` before executing these tests.
"""

import os

import pytest
from rpcn_client import RpcnClient
from shared.settings import get_settings

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
