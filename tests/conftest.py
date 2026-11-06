"""Fixtures shared by unit and integration tests."""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

# Signed-in routes need a key to sign test tokens with. Set before any test
# module imports shared.settings, whose get_settings() is cached for the run; an
# environment variable outranks the profile's env file, so this also holds
# locally, unless JWT_SECRET is already exported.
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-bytes-long")


@pytest.fixture
def auth_headers():
    """Build Authorization headers for a user, without asking RPCN.

    auth_headers("alice") signs a token the app accepts as alice; each call can
    name a different user, which is how ownership tests play two people.
    """
    from auth.models import AuthUser
    from auth.tokens import issue_token

    def make(username: str = "tester", online_name: str | None = None, admin: bool = False) -> dict[str, str]:
        token, _ = issue_token(AuthUser(username=username, online_name=online_name or username, admin=admin))
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def sessions():
    """A session factory for services whose fake repositories ignore the session."""
    session = AsyncMock()

    @asynccontextmanager
    async def begin():
        yield

    session.begin = begin

    @asynccontextmanager
    async def open_session():
        yield session

    return open_session


class MemoryIdempotencyStore:
    """The PostgreSQL store's rules over a dict, for services whose session is fake."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    async def claim(self, session, subject, key, fingerprint):
        from idempotency.exceptions import IdempotencyKeyReusedError

        row = self.rows.setdefault((subject, key), {"fingerprint": fingerprint, "response": None})
        if row["fingerprint"] != fingerprint:
            raise IdempotencyKeyReusedError("이미 다른 요청에 쓰인 요청 키입니다. 새로고침 후 다시 시도해 주세요.")
        return row["response"]

    async def complete(self, session, subject, key, response):
        self.rows[(subject, key)]["response"] = response


@pytest.fixture
def idempotency():
    from idempotency.service import IdempotencyService

    return IdempotencyService(MemoryIdempotencyStore())


@pytest.fixture
def send_idempotency_keys():
    """Make a test client give every POST a fresh Idempotency-Key unless the test set one, as the frontend does."""
    from uuid import uuid4

    def add_key(request):
        if request.method == "POST" and "Idempotency-Key" not in request.headers:
            request.headers["Idempotency-Key"] = str(uuid4())

    def install(client):
        client.event_hooks["request"].append(add_key)
        return client

    return install
