"""PostgreSQL lifecycle for the community board."""

import logging

import asyncpg

from shared.settings import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS posts (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        author      TEXT    NOT NULL,
        body        TEXT    NOT NULL CHECK(length(body) <= 1000),
        thumbs_up   INTEGER NOT NULL DEFAULT 0,
        thumbs_down INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comments (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
        parent_id   INTEGER REFERENCES comments(id) ON DELETE CASCADE,
        author      TEXT    NOT NULL,
        body        TEXT    NOT NULL CHECK(length(body) <= 1000),
        thumbs_up   INTEGER NOT NULL DEFAULT 0,
        thumbs_down INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_id)",
    """
    CREATE TABLE IF NOT EXISTS thumbs (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        target_type TEXT    NOT NULL CHECK(target_type IN ('post','comment')),
        target_id   INTEGER NOT NULL,
        voter       TEXT    NOT NULL,
        direction   INTEGER NOT NULL CHECK(direction IN (1,-1)),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(target_type, target_id, voter)
    )
    """,
]


async def init_db():
    global _pool
    dsn = get_settings().db_url
    logger.info("Connecting to community DB at %s", dsn.split("@")[-1] if "@" in dsn else dsn)
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    async with _pool.acquire() as conn:
        async with conn.transaction():
            for stmt in _SCHEMA_STATEMENTS:
                await conn.execute(stmt)


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Community DB pool closed")


def get_db() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Community DB not initialized — call init_db() first")
    return _pool
