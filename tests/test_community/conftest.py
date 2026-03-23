"""Fixtures for community board tests."""

import asyncio
import os

import pytest

# Provide required env vars before any settings import
os.environ.setdefault("RPCN_USER", "test")
os.environ.setdefault("RPCN_PASSWORD", "test")
os.environ.setdefault("RPCN_TOKEN", "test")
os.environ.setdefault("RPCN_HOST", "localhost")
os.environ.setdefault("RPCN_PORT", "31313")


def _truncate_postgresql(db_url: str):
    import asyncpg

    async def _run():
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute(
                "TRUNCATE posts, comments, thumbs RESTART IDENTITY CASCADE"
            )
        finally:
            await conn.close()

    asyncio.run(_run())


@pytest.fixture()
def client():
    """Create a TestClient backed by the configured DB backend and Redis."""
    from fastapi.testclient import TestClient
    from app import app
    from shared.settings import get_settings

    settings = get_settings()

    with TestClient(app) as tc:
        yield tc

    # Clean up after the app pool is closed
    if settings.db_type == "postgresql":
        _truncate_postgresql(settings.db_url)
