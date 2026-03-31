"""Fixtures for community board integration tests."""

import asyncio

import pytest


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
