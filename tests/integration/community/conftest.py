"""Fixtures for community board integration tests."""

import asyncio

import pytest


def _truncate_postgresql():
    import asyncpg
    from shared.database import build_dsn

    async def _run():
        conn = await asyncpg.connect(build_dsn(driver=""))
        try:
            await conn.execute("TRUNCATE posts, comments, thumbs RESTART IDENTITY CASCADE")
        finally:
            await conn.close()

    asyncio.run(_run())


@pytest.fixture()
def client():
    """Create a TestClient backed by PostgreSQL and Redis."""
    from fastapi.testclient import TestClient
    from app import app
    from shared.cache import cache_delete_pattern

    cache_delete_pattern("community:*")

    with TestClient(app) as tc:
        yield tc

    # Clean up after the app pool is closed
    _truncate_postgresql()
    cache_delete_pattern("community:*")
