"""Shared fixtures for integration tests.

Integration tests require external services (Redis, PostgreSQL, RPCN).
Run `docker compose -f compose.test.yml up -d` before executing these tests.
"""

import os

import pytest
from rpcn_client import RpcnClient

# Env defaults for local / CI integration testing
os.environ.setdefault("RPCN_USER", "test")
os.environ.setdefault("RPCN_PASSWORD", "test")
os.environ.setdefault("RPCN_TOKEN", "test")
os.environ.setdefault("RPCN_HOST", "localhost")
os.environ.setdefault("RPCN_PORT", "31313")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DB_URL", "localhost:5432")

HOST = os.environ.get("RPCN_HOST", "rpcn.mynarco.xyz")
PORT = int(os.environ.get("RPCN_PORT", "31313"))
USER = os.environ.get("RPCN_USER", "doStudyForAPI")
PASSWORD = os.environ.get("RPCN_PASSWORD", "")
TOKEN = os.environ.get("RPCN_TOKEN", "")


@pytest.fixture(scope="session")
def session():
    c = RpcnClient(HOST, PORT)
    c.connect()
    info = c.login(USER, PASSWORD, TOKEN)
    yield {"client": c, "login_info": info}
    c.disconnect()
