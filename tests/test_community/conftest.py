"""Fixtures for community board tests."""

import asyncio
import os

import asyncpg
import pytest

# Provide required env vars before any settings import
os.environ.setdefault("RPCN_USER", "test")
os.environ.setdefault("RPCN_PASSWORD", "test")
os.environ.setdefault("RPCN_TOKEN", "test")
os.environ.setdefault("RPCN_HOST", "localhost")
os.environ.setdefault("RPCN_PORT", "31313")


@pytest.fixture()
def client():
    """Create a TestClient backed by running PostgreSQL and Redis."""
    from fastapi.testclient import TestClient
    from app import app
    from shared.settings import get_settings

    pg_url = get_settings().db_url

    with TestClient(app) as tc:
        yield tc

    # Clean up using a fresh connection (app pool is already closed)
    async def _truncate():
        conn = await asyncpg.connect(pg_url)
        try:
            await conn.execute(
                "TRUNCATE posts, comments, thumbs RESTART IDENTITY CASCADE"
            )
        finally:
            await conn.close()

    asyncio.run(_truncate())
